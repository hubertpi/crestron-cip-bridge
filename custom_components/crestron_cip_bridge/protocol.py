"""Framing helpers for the unencrypted CIP stream used by the AV3 project."""
from __future__ import annotations

from collections.abc import Iterator

CLIENT_KEEPALIVE_FRAME = bytes.fromhex("0d00020000")
CLIENT_KEEPALIVE_INTERVAL = 10.0


def _ha_brightness(raw: int) -> int:
    if raw <= 0:
        return 0
    return max(1, round(raw * 255 / 65535))


class CipFrameBuffer:
    """Extract captured CIP messages with the 05 00 LEN framing prefix."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> Iterator[bytes]:
        self.buffer.extend(data)
        while True:
            start = self.buffer.find(b"\x05\x00")
            if start < 0:
                # Retain a trailing 0x05 in case the marker is split across reads.
                keep = self.buffer[-1:] if self.buffer.endswith(b"\x05") else b""
                self.buffer[:] = keep
                return
            if start:
                del self.buffer[:start]
            if len(self.buffer) < 3:
                return
            # Captured CIP stream framing: 05 00 LEN followed by LEN bytes.
            frame_size = 3 + self.buffer[2]
            if frame_size < 6 or frame_size > 65537:
                del self.buffer[0]
                continue
            if len(self.buffer) < frame_size:
                return
            frame = bytes(self.buffer[:frame_size])
            del self.buffer[:frame_size]
            yield frame


def decode_light_updates(frame: bytes) -> list[tuple[str, str, int | bool]]:
    """Return (key, attribute, value) readbacks for known Smart Object 61 signals."""
    updates: list[tuple[str, str, int | bool]] = []
    # Decode with the same framing logic used by the diagnostic inventory.
    # Object 61 readbacks arrive as individual joins, initial snapshots, and
    # grouped fade packets whose group size varies (2, 3, 5, or 6 joins were
    # observed). Handle them all by the decoded one-based analog join.
    from .const import LIGHTS
    from .discovery import decode_cip_updates

    key_by_join = {light["brightness_join"]: light["key"] for light in LIGHTS}
    for update in decode_cip_updates(frame):
        if update.get("smart_object") != 61 or update.get("type") != "analog":
            continue
        key = key_by_join.get(update["join"])
        if key:
            updates.append((key, "brightness", _ha_brightness(update["value"])))
    if updates:
        return updates

    # Captured digital packet: 05 00 0c 00 09 38 00 00 00 3d 03 27 CODE VALUE.
    # AV3's feedback event is interpreted only from AV3 -> client traffic.
    if (
        len(frame) == 15
        and frame[5:11] == bytes.fromhex("09380000003d")
        and frame[11:13] == bytes.fromhex("0327")
    ):
        code = frame[13]
        value = frame[14]
        from .const import LIGHTS_BY_DIGITAL

        mapped = LIGHTS_BY_DIGITAL.get(code)
        if mapped and value in (0x0F, 0x8F):
            key, is_on = mapped
            updates.append((key, "is_on", is_on))
        return updates

    return updates


def decode_library_join(update) -> list[tuple[str, str, int | bool]]:
    """Translate a pycrestron-cip Smart Object 61 join event into light state."""
    if getattr(update, "smart_object", None) != 61:
        return []
    join_type = getattr(update, "type", "")
    join_type = getattr(join_type, "value", join_type)
    join_type = str(join_type).lower()
    join = int(getattr(update, "join", -1))
    value = getattr(update, "value", None)
    from .const import LIGHTS

    if join_type.startswith("a"):
        light = next((item for item in LIGHTS if item["brightness_join"] == join), None)
        if light:
            return [(light["key"], "brightness", _ha_brightness(int(value)))]
    elif join_type.startswith("d"):
        light = next((item for item in LIGHTS if join in (item["on_join"], item["off_join"])), None)
        if light and bool(value):
            return [(light["key"], "is_on", join == light["on_join"])]
    return []


def select_frame(row: int) -> bytes:
    return bytes.fromhex("05000e00000b380000003d0514000000") + bytes((row,))


def digital_frame(code: int, pressed: bool) -> bytes:
    return bytes.fromhex("05000c000009380000003d0327") + bytes((code, 0x0F if pressed else 0x8F))


def analog_frame(analog_index: int, value: int) -> bytes:
    value = max(0, min(65535, value))
    return (
        bytes.fromhex("05000e00000b380000003d0514")
        + analog_index.to_bytes(2, "big")
        + value.to_bytes(2, "big")
    )


def cip_digital_frame(join: int, value: bool, *, button: bool = False) -> bytes:
    """Encode a top-level CIP digital join (join numbers are one-based)."""
    if not 1 <= int(join) <= 32768:
        raise ValueError("CIP digital joins must be between 1 and 32768")
    zero_based = int(join) - 1
    low = zero_based & 0xFF
    high = (zero_based >> 8) & 0x7F
    if not value:
        high |= 0x80
    subpacket = bytes((0x03, 0x27 if button else 0x00, low, high))
    return bytes((0x05, 0x00, 0x06, 0x00, 0x00)) + subpacket


def cip_analog_frame(join: int, value: int) -> bytes:
    """Encode a top-level CIP analog join (join numbers are one-based)."""
    if not 1 <= int(join) <= 65536:
        raise ValueError("CIP analog joins must be between 1 and 65536")
    value = max(0, min(65535, int(value)))
    payload = bytes((0x14,)) + (int(join) - 1).to_bytes(2, "big") + value.to_bytes(2, "big")
    subpacket = bytes((len(payload),)) + payload
    packet_payload = b"\x00\x00" + subpacket
    return b"\x05" + len(packet_payload).to_bytes(2, "big") + packet_payload


def smart_object_frame(frame: bytes, object_id: int | None) -> bytes:
    """Wrap a simple CIP data subpacket using the captured Object 61 format."""
    if object_id is None:
        return frame
    if not 1 <= int(object_id) <= 65535:
        raise ValueError("Smart Object ID must be between 1 and 65535")
    payload = b"\x38" + int(object_id).to_bytes(4, "big") + frame[5:]
    body = b"\x00\x00" + bytes((len(payload),)) + payload
    return b"\x05" + len(body).to_bytes(2, "big") + body
