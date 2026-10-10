from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    AV3_IP_ID,
    CONF_AV3_CIP_PORT,
    CONF_AV3_HOST,
    CONF_AV3_HTTP_PORT,
    CONF_CIP_LISTEN_PORT,
    CONF_CONNECTION_MODE,
    CONF_HTTP_LISTEN_PORT,
    CONF_HTTP_PROXY,
    CONF_LISTEN_ADDRESS,
    LIGHTS,
    MODE_AUTO,
    MODE_PROXY,
    MODE_STANDALONE,
    PRESENTATION_INPUTS,
    SCENES,
    SIGNAL_UPDATE,
)
from .protocol import (
    CLIENT_KEEPALIVE_FRAME,
    CLIENT_KEEPALIVE_INTERVAL,
    CipFrameBuffer,
    cip_analog_frame,
    cip_digital_frame,
    analog_frame,
    decode_library_join,
    decode_light_updates,
    digital_frame,
    select_frame,
    smart_object_frame,
)
from .capture import ActionCapture
from .discovery import decode_cip_updates, normalize_join_type, normalize_update, point_id as make_point_id

_LOGGER = logging.getLogger(__name__)


@dataclass
class LightState:
    is_on: bool = False
    brightness: int = 0
    received_feedback: bool = False
    restore_brightness: int | None = None
    preserve_brightness: bool = False


class CrestronProxy:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.config = entry.data
        self.mode = entry.options.get(
            CONF_CONNECTION_MODE,
            self.config.get(CONF_CONNECTION_MODE, MODE_PROXY),
        )
        self.states = {light["key"]: LightState() for light in LIGHTS}
        self.discovered_points: dict[str, dict] = {}
        self.capture = ActionCapture()
        self._servers: list[asyncio.AbstractServer] = []
        self._client_task: asyncio.Task | None = None
        self._cip_lock = asyncio.Lock()
        self._upstream_reader: asyncio.StreamReader | None = None
        self._upstream_writer: asyncio.StreamWriter | None = None
        self._downstream_writer: asyncio.StreamWriter | None = None
        self._upstream_pump_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._direct_panel = None
        self._direct_task: asyncio.Task | None = None
        self._stop_direct = asyncio.Event()
        self._pause_direct = asyncio.Event()
        self._write_lock = asyncio.Lock()
        # Keep the Smart Object dimmer button pressed across a slider gesture.
        # The iPad sends one press, a stream of analog levels, then one release.
        self._active_dimmers: dict[str, int] = {}
        self._dimmer_release_tasks: dict[str, asyncio.Task] = {}
        self.connected = False

    @property
    def display_mode(self) -> str:
        downstream_connected = bool(self._downstream_writer and not self._downstream_writer.is_closing())
        upstream_connected = bool(self._upstream_writer and not self._upstream_writer.is_closing())
        direct_connected = bool(self._direct_panel and self._direct_panel.available)
        if downstream_connected:
            return "iPad proxy"
        if upstream_connected:
            return "proxy idle"
        if direct_connected:
            return "standalone"
        if self.mode == MODE_AUTO and self._pause_direct.is_set():
            return "switching connection"
        if self.mode in (MODE_AUTO, MODE_STANDALONE):
            return "standalone connecting"
        return "waiting for iPad"

    async def async_start(self) -> None:
        address = self.config[CONF_LISTEN_ADDRESS]
        if self.mode in (MODE_STANDALONE, MODE_AUTO):
            _LOGGER.info("Connecting to AV3 as CIP IP ID 03 (%s mode)", self.mode)
            self._direct_task = asyncio.create_task(self._run_direct_client())
        try:
            if self.mode in (MODE_PROXY, MODE_AUTO):
                cip_server = await asyncio.start_server(self._handle_cip, address, self.config[CONF_CIP_LISTEN_PORT])
                self._servers.append(cip_server)
                if self.config[CONF_HTTP_PROXY]:
                    http_server = await asyncio.start_server(
                        self._handle_http,
                        address,
                        self.config[CONF_HTTP_LISTEN_PORT],
                    )
                    self._servers.append(http_server)
        except OSError:
            for server in self._servers:
                server.close()
            await asyncio.gather(*(server.wait_closed() for server in self._servers), return_exceptions=True)
            self._servers.clear()
            self._stop_direct.set()
            if self._direct_task and not self._direct_task.done():
                self._direct_task.cancel()
                await asyncio.gather(self._direct_task, return_exceptions=True)
            raise
        if self.mode in (MODE_PROXY, MODE_AUTO):
            _LOGGER.info(
                "Crestron proxy listening for CIP on %s:%s (HTTP proxy %s)",
                address,
                self.config[CONF_CIP_LISTEN_PORT],
                "enabled" if self.config[CONF_HTTP_PROXY] else "disabled",
            )

    async def async_stop(self) -> None:
        await self._release_all_dimmers()
        self._stop_direct.set()
        self._pause_direct.set()
        if self._direct_panel:
            await self._direct_panel.close()
        if self._direct_task and not self._direct_task.done():
            self._direct_task.cancel()
            await asyncio.gather(self._direct_task, return_exceptions=True)
        for server in self._servers:
            server.close()
        await asyncio.gather(*(server.wait_closed() for server in self._servers), return_exceptions=True)
        self._servers.clear()
        if self._client_task and not self._client_task.done():
            self._client_task.cancel()
            await asyncio.gather(self._client_task, return_exceptions=True)
        await self._close_session()

    async def _run_direct_client(self) -> None:
        from pycrestron_cip import CipClient

        while not self._stop_direct.is_set() and not self._pause_direct.is_set():
            panel = CipClient(
                self.config[CONF_AV3_HOST],
                AV3_IP_ID,
                port=self.config[CONF_AV3_CIP_PORT],
                reconnect=True,
            )
            self._direct_panel = panel
            unsubscribe = panel.subscribe(self._handle_direct_join)
            panel.subscribe_state(lambda _state: self._set_connected(bool(panel.available)))
            try:
                await panel.connect()
                await panel.wait_ready()
                self._set_connected(bool(panel.available))
                stop_waiter = asyncio.create_task(self._stop_direct.wait())
                pause_waiter = asyncio.create_task(self._pause_direct.wait())
                _, pending = await asyncio.wait(
                    (stop_waiter, pause_waiter), return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # reconnect after a failed initial registration
                _LOGGER.warning("CIP client failed to connect: %s", err)
                self._set_connected(False)
                if not self._stop_direct.is_set() and not self._pause_direct.is_set():
                    try:
                        await asyncio.wait_for(self._stop_direct.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        pass
            finally:
                unsubscribe()
                await panel.close()
                if self._direct_panel is panel:
                    self._direct_panel = None
                self._set_connected(False)
        if self.mode == MODE_AUTO and not self._stop_direct.is_set() and not self._pause_direct.is_set():
            self._direct_task = None

    async def _pause_auto_direct(self) -> None:
        if self.mode != MODE_AUTO:
            return
        self._pause_direct.set()
        panel = self._direct_panel
        if panel:
            await panel.close()
        task = self._direct_task
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._direct_task = None
        self._direct_panel = None

    def _resume_auto_direct(self) -> None:
        if self.mode != MODE_AUTO or self._stop_direct.is_set():
            return
        if self._direct_task and not self._direct_task.done():
            return
        self._pause_direct.clear()
        self._direct_task = asyncio.create_task(self._run_direct_client())
        self._dispatch_all()

    def _set_connected(self, connected: bool) -> None:
        if self.connected != connected:
            self.connected = connected
            self._dispatch_all()

    def _handle_direct_join(self, update) -> None:
        self.capture.record("av3_to_ha", self.display_mode, [normalize_update(update)])
        self._record_discovered_point(update)
        updates = decode_library_join(update)
        if updates:
            _LOGGER.debug("AV3 Smart Object 61 readback: %s", updates)
        self._apply_updates(updates, from_feedback=True)

    def _record_discovered_point(self, update) -> None:
        smart_object = getattr(update, "smart_object", None)
        join_type = normalize_join_type(getattr(update, "type", "unknown"))
        join = int(getattr(update, "join", -1))
        key = make_point_id(smart_object, join_type, join)
        record = normalize_update(update, self.discovered_points.get(key))
        if record["id"] not in self.discovered_points and len(self.discovered_points) >= 3000:
            return
        self.discovered_points[record["id"]] = record
        self._dispatch_all()

    def _get_command_point(self, point_id):
        # A configured command need not have been echoed back by the AV3.
        point = next((p for p in self.entry.options.get("configured_points", [])
                      if p["id"] == point_id), None)
        return point or self.discovered_points.get(point_id)

    async def _send_digital_point(self, point, value, *, pulse=False, pulse_duration=0.15):
        panel = self._direct_panel if self._direct_panel and self._direct_panel.available else None
        writer = self._upstream_writer
        if panel is None and (not writer or writer.is_closing()):
            raise RuntimeError("CIP is not connected")
        def frame(state):
            return smart_object_frame(cip_digital_frame(point["join"], state, button=pulse),
                                      point.get("smart_object"))
        async def send(state):
            data = frame(state)
            if panel is not None:
                panel._write(data)
            else:
                writer.write(data)
                await writer.drain()
            self.capture.record("ha_to_av3", self.display_mode, decode_cip_updates(data), data)
        async with self._write_lock:
            await send(value)
            if pulse:
                try:
                    await asyncio.sleep(pulse_duration)
                finally:
                    await send(False)

    async def async_pulse_digital_join(self, join: int, *, pulse_duration: float = 0.035) -> None:
        """Pulse an observed top-level CIP button join using its captured timing."""
        if not 1 <= int(join) <= 32768:
            raise ValueError("CIP digital joins must be between 1 and 32768")
        await self._send_digital_point(
            {"smart_object": None, "join": int(join)},
            True,
            pulse=True,
            pulse_duration=pulse_duration,
        )

    async def async_test_discovered_point(self, point_id: str, value: int | None = None) -> None:
        """Send one deliberate digital pulse or analog value for commissioning."""
        point = self._get_command_point(point_id)
        if not point:
            raise ValueError("That discovered point is no longer in the inventory")
        if point["type"] == "digital":
            await self._send_digital_point(point, True, pulse=True)
            return
        if point.get("smart_object") is not None:
            raise ValueError("Generic Smart Object analog writes are not supported")
        if point["type"] not in ("digital", "analog"):
            raise ValueError("Only digital and analog joins can be tested")
        join = int(point["join"])
        panel = self._direct_panel if self._direct_panel and self._direct_panel.available else None
        writer = self._upstream_writer
        if panel is None and (not writer or writer.is_closing()):
            raise RuntimeError("CIP is not connected; wait for standalone or proxy mode to connect")
        if point["type"] == "digital":
            if panel:
                await panel.pulse(join)
            else:
                async with self._write_lock:
                    writer.write(cip_digital_frame(join, True, button=True))
                    await writer.drain()
                    await asyncio.sleep(0.15)
                    writer.write(cip_digital_frame(join, False, button=True))
                    await writer.drain()
        else:
            if value is None:
                raise ValueError("An analog test needs a value between 0 and 65535")
            value = max(0, min(65535, int(value)))
            if panel:
                panel.set_analog(join, value)
            else:
                async with self._write_lock:
                    writer.write(cip_analog_frame(join, value))
                    await writer.drain()

    async def async_set_discovered_point(self, point_id: str, value: int | bool) -> None:
        """Write a configured digital point or top-level analog point."""
        point = self._get_command_point(point_id)
        if not point:
            raise ValueError("That discovered point is no longer in the inventory")
        if point["type"] == "digital":
            await self._send_digital_point(point, bool(value))
            return
        if point.get("smart_object") is not None:
            raise ValueError("Generic Smart Object analog writes are not supported")
        panel = self._direct_panel if self._direct_panel and self._direct_panel.available else None
        writer = self._upstream_writer
        if panel is None and (not writer or writer.is_closing()):
            raise RuntimeError("CIP is not connected")
        join = int(point["join"])
        async with self._write_lock:
            if point["type"] == "digital":
                if panel:
                    panel.set_digital(join, bool(value))
                else:
                    writer.write(cip_digital_frame(join, bool(value)))
                    await writer.drain()
            elif point["type"] == "analog":
                raw = max(0, min(65535, int(value)))
                if panel:
                    panel.set_analog(join, raw)
                else:
                    writer.write(cip_analog_frame(join, raw))
                    await writer.drain()
            else:
                raise ValueError("Only digital and analog joins can be controlled")

    async def _close_session(self) -> None:
        tasks = (self._upstream_pump_task, self._keepalive_task)
        self._upstream_pump_task = None
        self._keepalive_task = None
        for task in tasks:
            if task and task is not asyncio.current_task() and not task.done():
                task.cancel()
        writers = (self._upstream_writer, self._downstream_writer)
        self._upstream_reader = None
        self._upstream_writer = None
        self._downstream_writer = None
        self.connected = False
        for writer in writers:
            if writer and not writer.is_closing():
                writer.close()
        await asyncio.gather(
            *(writer.wait_closed() for writer in writers if writer is not None),
            return_exceptions=True,
        )
        await asyncio.gather(
            *(task for task in tasks if task and task is not asyncio.current_task()),
            return_exceptions=True,
        )

    async def _handle_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await self._relay_connection(reader, writer, self.config[CONF_AV3_HTTP_PORT], inspect=False)

    async def _handle_cip(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        upstream_writer = None
        try:
            async with self._cip_lock:
                if self._downstream_writer and not self._downstream_writer.is_closing():
                    _LOGGER.warning("Rejecting extra CIP client %s; one iPad is supported at a time", peer)
                    writer.close()
                    await writer.wait_closed()
                    return
                # A reconnecting app needs a clean CIP registration. If an idle
                # app left the upstream session parked, replace that session.
                if self._upstream_writer:
                    await self._close_session()
                await self._pause_auto_direct()
                upstream_reader, upstream_writer = await asyncio.open_connection(
                    self.config[CONF_AV3_HOST], self.config[CONF_AV3_CIP_PORT]
                )
                self._upstream_reader = upstream_reader
                self._upstream_writer = upstream_writer
                self._downstream_writer = writer
                self._client_task = asyncio.current_task()
                self.connected = True
                self._upstream_pump_task = asyncio.create_task(
                    self._pump_av3_to_client(upstream_reader, upstream_writer)
                )
                self._dispatch_all()

            await self._relay(reader, upstream_writer, inspect=True, from_feedback=False)
        except (OSError, asyncio.TimeoutError) as err:
            _LOGGER.warning("Crestron upstream connection failed on port %s: %s", self.config[CONF_AV3_CIP_PORT], err)
            writer.close()
            await asyncio.gather(writer.wait_closed(), return_exceptions=True)
        except asyncio.CancelledError:
            raise
        finally:
            async with self._cip_lock:
                if self._downstream_writer is writer:
                    self._downstream_writer = None
                    writer.close()
                    await asyncio.gather(writer.wait_closed(), return_exceptions=True)
                    if self._upstream_writer and not self._upstream_writer.is_closing():
                        self._ensure_keepalive()
                    self._dispatch_all()
                if self._client_task is asyncio.current_task():
                    self._client_task = None
                if self.mode == MODE_AUTO and self._upstream_writer is None:
                    self._resume_auto_direct()

    def _ensure_keepalive(self) -> None:
        if not self._keepalive_task or self._keepalive_task.done():
            self._keepalive_task = asyncio.create_task(self._run_keepalive())

    async def _run_keepalive(self) -> None:
        try:
            while self._upstream_writer and not self._upstream_writer.is_closing():
                await asyncio.sleep(CLIENT_KEEPALIVE_INTERVAL)
                writer = self._upstream_writer
                if writer is None or writer.is_closing():
                    return
                if self._downstream_writer is None:
                    try:
                        async with self._write_lock:
                            writer.write(CLIENT_KEEPALIVE_FRAME)
                            await writer.drain()
                    except OSError as err:
                        _LOGGER.debug("CIP keepalive failed: %s", err)
                        writer.close()
                        return
        except asyncio.CancelledError:
            raise
        finally:
            if self._keepalive_task is asyncio.current_task():
                self._keepalive_task = None

    async def _pump_av3_to_client(
        self,
        reader: asyncio.StreamReader,
        upstream_writer: asyncio.StreamWriter,
    ) -> None:
        parser = CipFrameBuffer()
        try:
            while data := await reader.read(8192):
                for frame in parser.feed(data):
                    self._apply_frame(frame, from_feedback=True)
                downstream = self._downstream_writer
                if downstream and not downstream.is_closing():
                    try:
                        downstream.write(data)
                        await downstream.drain()
                    except OSError:
                        downstream.close()
                        if self._downstream_writer is downstream:
                            self._downstream_writer = None
                            self._ensure_keepalive()
        except asyncio.CancelledError:
            raise
        except OSError as err:
            _LOGGER.debug("AV3 CIP stream ended: %s", err)
        finally:
            if self._upstream_writer is upstream_writer:
                self.connected = False
                self._upstream_reader = None
                self._upstream_writer = None
                downstream = self._downstream_writer
                self._downstream_writer = None
                keepalive = self._keepalive_task
                self._keepalive_task = None
                if keepalive and keepalive is not asyncio.current_task():
                    keepalive.cancel()
                    await asyncio.gather(keepalive, return_exceptions=True)
                if downstream and not downstream.is_closing():
                    downstream.close()
                    await asyncio.gather(downstream.wait_closed(), return_exceptions=True)
                upstream_writer.close()
                await asyncio.gather(upstream_writer.wait_closed(), return_exceptions=True)
                self._dispatch_all()
                if self.mode == MODE_AUTO and not self._stop_direct.is_set():
                    self._resume_auto_direct()
                self._dispatch_all()

    async def _relay_connection(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        upstream_port: int,
        *,
        inspect: bool,
    ) -> None:
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(self.config[CONF_AV3_HOST], upstream_port)
            if inspect:
                self._upstream_writer = upstream_writer
                self._downstream_writer = client_writer
                self.connected = True
                self._dispatch_all()
            tasks = [
                asyncio.create_task(
                    self._relay(client_reader, upstream_writer, inspect=inspect, from_feedback=False)
                ),
                asyncio.create_task(
                    self._relay(upstream_reader, client_writer, inspect=inspect, from_feedback=True)
                ),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, *pending, return_exceptions=True)
        except (OSError, asyncio.TimeoutError) as err:
            _LOGGER.warning("Crestron upstream connection failed on port %s: %s", upstream_port, err)
        except asyncio.CancelledError:
            raise
        finally:
            if inspect:
                self.connected = False
                self._upstream_writer = None
                self._downstream_writer = None
                self._dispatch_all()
            client_writer.close()
            if upstream_writer:
                upstream_writer.close()
            await asyncio.gather(client_writer.wait_closed(), return_exceptions=True)
            if upstream_writer:
                await asyncio.gather(upstream_writer.wait_closed(), return_exceptions=True)

    async def _relay(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        inspect: bool,
        from_feedback: bool,
    ) -> None:
        parser = CipFrameBuffer() if inspect else None
        while data := await reader.read(8192):
            if parser:
                for frame in parser.feed(data):
                    self._apply_frame(frame, from_feedback=from_feedback)
            writer.write(data)
            await writer.drain()

    async def async_activate_scene(self, key: str) -> None:
        """Replay the observed iPad scene-selection press and release."""
        scene = next(item for item in SCENES if item["key"] == key)
        panel = self._direct_panel if self.mode in (MODE_STANDALONE, MODE_AUTO) else None
        if panel is not None and not panel.available:
            panel = None
        writer = self._upstream_writer
        if panel is None and (not writer or writer.is_closing()):
            raise RuntimeError("Crestron CIP session is not connected")

        def send(frame: bytes) -> None:
            if panel is not None:
                panel._write(frame)
            else:
                writer.write(frame)
            self.capture.record("ha_to_av3", self.display_mode, decode_cip_updates(frame), frame)

        press = smart_object_frame(
            cip_digital_frame(scene["digital_join"], True, button=True), 65
        )
        release = smart_object_frame(
            cip_digital_frame(scene["digital_join"], False, button=True), 65
        )
        select = smart_object_frame(cip_analog_frame(1, 1), 65)
        async with self._write_lock:
            send(select)
            send(press)
            if panel is None:
                await writer.drain()
            try:
                # The recorded iPad held each scene button for about 100 ms.
                await asyncio.sleep(0.10)
            finally:
                send(release)
                if panel is None:
                    await writer.drain()

    async def async_activate_presentation(self, key: str) -> None:
        """Replay a captured global presentation source button on Object 20."""
        source = next(item for item in PRESENTATION_INPUTS if item["key"] == key)
        panel = self._direct_panel if self.mode in (MODE_STANDALONE, MODE_AUTO) else None
        if panel is not None and not panel.available:
            panel = None
        writer = self._upstream_writer
        if panel is None and (not writer or writer.is_closing()):
            raise RuntimeError("Crestron CIP session is not connected")

        def send(frame: bytes) -> None:
            if panel is not None:
                panel._write(frame)
            else:
                writer.write(frame)
            self.capture.record("ha_to_av3", self.display_mode, decode_cip_updates(frame), frame)

        analog = smart_object_frame(cip_analog_frame(1, source["analog_value"]), 20)
        press = smart_object_frame(
            cip_digital_frame(source["digital_join"], True, button=True), 20
        )
        release = smart_object_frame(
            cip_digital_frame(source["digital_join"], False, button=True), 20
        )
        async with self._write_lock:
            send(analog)
            if panel is None:
                await writer.drain()
            # Captures placed the Object 20 button press about 11 ms after
            # setting analog join 1; observed presses lasted 75–170 ms.
            await asyncio.sleep(0.011)
            send(press)
            if panel is None:
                await writer.drain()
            try:
                await asyncio.sleep(0.10)
            finally:
                send(release)
                if panel is None:
                    await writer.drain()

    async def async_select_media_input(
        self, smart_object: int, analog_value: int, digital_join: int
    ) -> None:
        """Replay a captured display source selection for one output object."""
        if not 75 <= int(smart_object) <= 78:
            raise ValueError("Media output Smart Object must be between 75 and 78")
        if not 3 <= int(analog_value) <= 6 or not 13 <= int(digital_join) <= 16:
            raise ValueError("Unsupported captured media input selection")

        panel = self._direct_panel if self.mode in (MODE_STANDALONE, MODE_AUTO) else None
        if panel is not None and not panel.available:
            panel = None
        writer = self._upstream_writer
        if panel is None and (not writer or writer.is_closing()):
            raise RuntimeError("Crestron CIP session is not connected")

        def send(frame: bytes) -> None:
            if panel is not None:
                panel._write(frame)
            else:
                writer.write(frame)
            self.capture.record("ha_to_av3", self.display_mode, decode_cip_updates(frame), frame)

        analog = smart_object_frame(cip_analog_frame(1, int(analog_value)), int(smart_object))
        press = smart_object_frame(
            cip_digital_frame(int(digital_join), True, button=True), int(smart_object)
        )
        release = smart_object_frame(
            cip_digital_frame(int(digital_join), False, button=True), int(smart_object)
        )
        async with self._write_lock:
            send(analog)
            if panel is None:
                await writer.drain()
            # Captures place the digital press about 20–30 ms after the analog
            # source value; observed presses lasted roughly 70–135 ms.
            await asyncio.sleep(0.025)
            send(press)
            if panel is None:
                await writer.drain()
            try:
                await asyncio.sleep(0.10)
            finally:
                send(release)
                if panel is None:
                    await writer.drain()

    async def async_command(self, key: str, *, turn_on: bool | None = None, brightness: int | None = None) -> None:
        panel = self._direct_panel if self.mode in (MODE_STANDALONE, MODE_AUTO) else None
        if panel is not None and not panel.available:
            panel = None
        writer = self._upstream_writer
        if panel is not None and not panel.available:
            raise RuntimeError("Standalone Crestron CIP session is not connected")
        if panel is None and (not writer or writer.is_closing()):
            raise RuntimeError("Crestron iPad proxy session is not connected")
        light = next(item for item in LIGHTS if item["key"] == key)

        def send(frame: bytes) -> None:
            if panel is not None:
                panel._write(frame)
            else:
                writer.write(frame)
            self.capture.record("ha_to_av3", self.display_mode, decode_cip_updates(frame), frame)

        async with self._write_lock:
            state = self.states[key]
            recall = state.restore_brightness if turn_on else None
            if brightness is not None:
                dimmer_code = light.get("dimmer_code")
                if dimmer_code is None:
                    raise RuntimeError(f"Brightness control for {light['name']} has not been verified")
                brightness = max(0, min(255, brightness))
                raw = round(brightness * 65535 / 255)
                release_task = self._dimmer_release_tasks.pop(key, None)
                if release_task:
                    release_task.cancel()
                # Match the iPad gesture: press/select once, send all slider
                # values while pressed, and release after a short quiet period.
                for active_key in tuple(self._active_dimmers):
                    if active_key != key:
                        await self._release_dimmer_locked(active_key, send)
                if key not in self._active_dimmers:
                    send(digital_frame(dimmer_code, True))
                    send(select_frame(light["row"]))
                    self._active_dimmers[key] = dimmer_code
                send(analog_frame(light["analog_index"], raw))
                if panel is None:
                    await writer.drain()
                self._dimmer_release_tasks[key] = asyncio.create_task(self._release_dimmer_after_quiet(key))
                state.preserve_brightness = brightness == 0
                # Brightness is a physical-state readback. Do not change the
                # displayed level from the requested value; wait for AV3 feedback.
                return
            if turn_on is None:
                return
            await self._release_dimmer_locked(key, send)
            # Keep the saved level intact during OFF ramp-down and the ON
            # button's full-brightness feedback. Snapshot recall before any await.
            state.preserve_brightness = True
            send(select_frame(light["row"]))
            if panel is None:
                await writer.drain()
            await asyncio.sleep(0.05)
            code = light["on_code"] if turn_on else light["off_code"]
            send(digital_frame(code, True))
            if panel is None:
                await writer.drain()
            await asyncio.sleep(0.10)
            send(digital_frame(code, False))
            if panel is None:
                await writer.drain()
            self._apply_updates([(key, "is_on", turn_on)])
            if turn_on:
                if recall is not None and light.get("dimmer_code") is not None:
                    # First operate the proven per-light ON button above, then
                    # replay the unchanged 0.1.6 dimmer sequence at the saved level.
                    send(digital_frame(light["dimmer_code"], True))
                    send(select_frame(light["row"]))
                    send(analog_frame(light["analog_index"], recall * 257))
                    send(digital_frame(light["dimmer_code"], False))
                    if panel is None:
                        await writer.drain()
                    # Restore the last AV3-confirmed level after the ON pulse.
                    # Some programs report the ON button's 100% state but do not
                    # send another analog readback when the recalled level is
                    # already active. A later AV3 report still replaces this.
                    self._apply_updates([(key, "brightness", recall), (key, "is_on", True)])
                state.preserve_brightness = False

    async def _release_dimmer_after_quiet(self, key: str) -> None:
        current = asyncio.current_task()
        try:
            await asyncio.sleep(0.15)
            async with self._write_lock:
                if self._dimmer_release_tasks.get(key) is not current:
                    return
                self._dimmer_release_tasks.pop(key, None)
                code = self._active_dimmers.pop(key, None)
                if code is None:
                    return
                frame = digital_frame(code, False)
                panel = self._direct_panel if self.mode in (MODE_STANDALONE, MODE_AUTO) else None
                if panel is not None and panel.available:
                    panel._write(frame)
                else:
                    writer = self._upstream_writer
                    if not writer or writer.is_closing():
                        return
                    writer.write(frame)
                    await writer.drain()
                self.capture.record("ha_to_av3", self.display_mode, decode_cip_updates(frame), frame)
        except asyncio.CancelledError:
            raise

    async def _release_dimmer_locked(self, key: str, send) -> None:
        task = self._dimmer_release_tasks.pop(key, None)
        if task:
            task.cancel()
        code = self._active_dimmers.pop(key, None)
        if code is not None:
            send(digital_frame(code, False))

    async def _release_all_dimmers(self) -> None:
        tasks = list(self._dimmer_release_tasks.values())
        self._dimmer_release_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if not self._active_dimmers:
            return
        async with self._write_lock:
            for code in self._active_dimmers.values():
                frame = digital_frame(code, False)
                panel = self._direct_panel if self.mode in (MODE_STANDALONE, MODE_AUTO) else None
                if panel is not None and panel.available:
                    panel._write(frame)
                elif self._upstream_writer and not self._upstream_writer.is_closing():
                    self._upstream_writer.write(frame)
            if self._upstream_writer and not self._upstream_writer.is_closing():
                await self._upstream_writer.drain()
            self._active_dimmers.clear()

    def _apply_frame(self, frame: bytes, *, from_feedback: bool) -> None:
        if frame and frame[0] in (0x05, 0x12):
            self.capture.record(
                "av3_to_panel" if from_feedback else "ipad_to_av3",
                self.display_mode, decode_cip_updates(frame), frame,
            )
        if from_feedback:
            for update in decode_cip_updates(frame):
                self._record_discovered_point(SimpleNamespace(**update))
        # Client-to-AV3 analog writes describe the requested slider value, not
        # physical readback. Only the AV3 side is authoritative for light state.
        updates = decode_light_updates(frame) if from_feedback else []
        if updates:
            _LOGGER.debug("Crestron light update (%s): %s", "AV3" if from_feedback else "iPad", updates)
        elif b"\x00\x3d" in frame:
            _LOGGER.debug("Unmapped Smart Object 61 CIP frame: %s", frame.hex())
        self._apply_updates(updates, from_feedback=from_feedback)

    def _apply_updates(self, updates, *, from_feedback: bool = False) -> None:
        if not updates:
            return
        changed = False
        for key, attribute, value in updates:
            state = self.states[key]
            if attribute == "brightness" and int(value) > 0 and not state.preserve_brightness:
                if state.restore_brightness != int(value):
                    state.restore_brightness = int(value)
                    changed = True
            if getattr(state, attribute) != value:
                setattr(state, attribute, value)
                changed = True
            if attribute == "brightness" and from_feedback:
                # Analog readback represents the dimmer's actual level. In
                # particular, zero must clear ON even if an earlier digital
                # button report left power state latched as true.
                inferred_on = int(value) > 0
                if state.is_on != inferred_on:
                    state.is_on = inferred_on
                    changed = True
            if from_feedback and not state.received_feedback:
                state.received_feedback = True
                changed = True
        if changed:
            self._dispatch_update()

    def _dispatch_all(self) -> None:
        self._dispatch_update()

    def _dispatch_update(self) -> None:
        """Notify entities on HA's event loop, even for worker-thread callbacks."""
        self.hass.add_job(async_dispatcher_send, self.hass, SIGNAL_UPDATE, None)
