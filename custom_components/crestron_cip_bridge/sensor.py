from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from .discovered import DiscoveredValueSensor
from .const import DOMAIN, SIGNAL_UPDATE
from .lighting_scene import SCENE_FEEDBACK_JOINS
from .proxy import CrestronProxy


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    proxy: CrestronProxy = hass.data[DOMAIN][entry.entry_id]
    points = entry.options.get("configured_points", [])
    async_add_entities(
        [CrestronConnectionModeSensor(proxy), ActiveLightingSceneSensor(proxy)]
        + [ProjectorLampHoursSensor(proxy)]
        + [DiscoveredValueSensor(proxy, point) for point in points if point.get("entity_type") == "sensor"]
    )


class ProjectorLampHoursSensor(SensorEntity):
    """Numeric view of the observed projector hours string at CIP serial join 25."""

    _attr_has_entity_name = True
    _attr_name = "Projector Lamp Hours"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 0

    def __init__(self, proxy: CrestronProxy) -> None:
        self.proxy = proxy
        self._attr_unique_id = f"{proxy.entry.entry_id}_projector_lamp_hours"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, proxy.entry.entry_id)},
            name="Crestron AV3",
            manufacturer="Crestron",
            model="AV3 CIP Bridge",
        )

    @property
    def native_value(self) -> int | None:
        point = self.proxy.discovered_points.get("cip:serial:25")
        if not point:
            return None
        value = point.get("value")
        try:
            hours = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return hours if hours >= 0 else None

    @property
    def available(self) -> bool:
        return self.proxy.connected and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        point = self.proxy.discovered_points.get("cip:serial:25", {})
        return {
            "crestron_source": "CIP serial join 25",
            "last_received": point.get("last_seen"),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update))

    def _handle_update(self, _signal=None) -> None:
        self.async_write_ha_state()


class CrestronConnectionModeSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "CIP connection mode"
    def __init__(self, proxy: CrestronProxy) -> None:
        self.proxy = proxy
        self._attr_unique_id = f"{proxy.entry.entry_id}_cip_connection_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, proxy.entry.entry_id)},
            name="Crestron AV3",
            manufacturer="Crestron",
            model="AV3 Smart Object 61",
        )

    @property
    def native_value(self) -> str:
        return self.proxy.display_mode

    @property
    def extra_state_attributes(self) -> dict[str, bool | str]:
        direct = self.proxy._direct_panel
        downstream = self.proxy._downstream_writer
        upstream = self.proxy._upstream_writer
        return {
            "configured_mode": self.proxy.mode,
            "av3_connected": self.proxy.connected,
            "ipad_connected": bool(downstream and not downstream.is_closing()),
            "connection_owner": "HA" if direct and direct.available else "iPad proxy" if upstream else "none",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update))

    def _handle_update(self, _signal=None) -> None:
        self.async_write_ha_state()


class ActiveLightingSceneSensor(SensorEntity):
    """Read-only active scene from AV3 Smart Object 65 selection feedback."""

    _attr_has_entity_name = True
    _attr_name = "Active lighting scene"
    _attr_icon = "mdi:lightbulb-group"

    def __init__(self, proxy: CrestronProxy) -> None:
        self.proxy = proxy
        self._attr_unique_id = f"{proxy.entry.entry_id}_active_lighting_scene"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, proxy.entry.entry_id)},
            name="Crestron AV3",
            manufacturer="Crestron",
            model="AV3 Smart Object 65",
        )

    @property
    def native_value(self) -> str | None:
        return self.proxy.active_lighting_scene.state

    @property
    def available(self) -> bool:
        return self.proxy.connected

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        scene = self.proxy.active_lighting_scene.state
        join = next(
            (join for join, label in SCENE_FEEDBACK_JOINS.items() if label == scene),
            None,
        )
        return {
            "feedback_source": "Smart Object 65 digital selection feedback",
            "feedback_join": join,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update))

    def _handle_update(self, _signal=None) -> None:
        self.async_write_ha_state()
