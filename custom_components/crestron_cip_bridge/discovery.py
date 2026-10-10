"""Helpers for building a safe, typed inventory of CIP joins."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def normalize_join_type(value: Any) -> str:
    value = getattr(value, "value", value)
    text = str(value).lower()
    for name in ("digital", "analog", "serial"):
        if text.startswith(name[0]) or text.startswith(name):
            return name
    return text


def point_id(smart_object: int | None, join_type: str, join: int) -> str:
    owner = "cip" if smart_object is None else f"so{int(smart_object)}"
    return f"{owner}:{join_type}:{int(join)}"


def normalize_update(update: Any, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a JSON-safe point record from pycrestron-cip's JoinUpdate."""
    smart_object = getattr(update, "smart_object", None)
    signal_type = normalize_join_type(getattr(update, "type", "unknown"))
    join = int(getattr(update, "join", -1))
    value = getattr(update, "value", None)
    if isinstance(value, bytes):
        shown_value: str | int | float | bool = value.decode("utf-8", errors="replace")
    elif isinstance(value, (str, int, float, bool)) or value is None:
        shown_value = value
    else:
        shown_value = repr(value)
    record = dict(previous or {})
    record.update(
        {
            "id": point_id(smart_object, signal_type, join),
            "smart_object": int(smart_object) if smart_object is not None else None,
            "type": signal_type,
            "join": join,
            "value": shown_value,
            "updates": int(record.get("updates", 0)) + 1,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }
    )
    return record


def describe_point(point: dict[str, Any]) -> str:
    """Build a compact label for Home Assistant's point selector."""
    owner = f"Smart Object {point['smart_object']}" if point.get("smart_object") is not None else "CIP"
    value = point.get("value")
    if isinstance(value, str):
        value_text = value.replace("\n", " ").strip()
        if len(value_text) > 36:
            value_text = value_text[:33] + "..."
    else:
        value_text = repr(value)
    return f"{owner} · {point['type']} join {point['join']} · {value_text}"


def decode_cip_updates(frame: bytes, smart_object: int | None = None) -> list[dict[str, Any]]:
    """Decode observed typed CIP joins, including ordinary 0x05 data frames.

    Unknown/private sub-packets are ignored. Smart Object writes are not inferred
    from incoming values; this only inventories what the processor sends.
    """
    if not frame or frame[0] not in (0x05, 0x12) or len(frame) < 5:
        return []
    return _decode_subpackets(frame[5:], smart_object)


def _decode_subpackets(data: bytes, smart_object: int | None) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    offset = 0
    while offset + 2 <= len(data):
        length = data[offset]
        end = offset + 1 + length
        if length < 1 or end > len(data):
            break
        packet_type = data[offset + 1]
        payload = data[offset + 2 : end]
        offset = end
        if packet_type in (0x38, 0x39) and len(payload) >= 4:
            object_id = int.from_bytes(payload[:4], "big")
            updates.extend(_decode_subpackets(payload[4:], object_id))
        elif packet_type in (0x00, 0x27) and len(payload) >= 2 and len(payload) % 2 == 0:
            for index in range(0, len(payload), 2):
                zero_based_join = (payload[index + 1] & 0x7F) << 8 | payload[index]
                updates.append(
                    {
                        "smart_object": smart_object,
                        "type": "digital",
                        "join": zero_based_join + 1,
                        "value": not bool(payload[index + 1] & 0x80),
                    }
                )
        elif (
            packet_type == 0x14
            and smart_object is not None
            and len(payload) >= 8
            and payload[:2] == b"\x00\x02"
        ):
            # Smart Object analog snapshot: 0002, item count, then index/value pairs.
            # Some AV3 snapshots under-report this count; the nested packet
            # length is authoritative and bounds the available join records.
            count = (len(payload) - 4) // 4
            for index in range(count):
                offset = 4 + index * 4
                if offset + 4 > len(payload):
                    break
                updates.append(
                    {
                        "smart_object": smart_object,
                        "type": "analog",
                        "join": int.from_bytes(payload[offset : offset + 2], "big") + 1,
                        "value": int.from_bytes(payload[offset + 2 : offset + 4], "big"),
                    }
                )
        elif packet_type == 0x14 and len(payload) >= 4 and len(payload) % 4 == 0:
            for index in range(0, len(payload), 4):
                updates.append(
                    {
                        "smart_object": smart_object,
                        "type": "analog",
                        "join": int.from_bytes(payload[index : index + 2], "big") + 1,
                        "value": int.from_bytes(payload[index + 2 : index + 4], "big"),
                    }
                )
        elif packet_type in (0x15, 0x34) and len(payload) >= 3:
            flags = payload[2]
            if flags & 0x03 == 0x03:
                encoding = "utf-16-le" if flags & 0x04 else "utf-8"
                value = payload[3:].decode(encoding, errors="replace").rstrip("\x00")
                updates.append(
                    {
                        "smart_object": smart_object,
                        "type": "serial",
                        "join": int.from_bytes(payload[:2], "big") + 1,
                        "value": value,
                    }
                )
    return updates
