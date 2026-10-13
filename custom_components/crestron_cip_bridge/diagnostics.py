"""Export observed joins for commissioning without sending CIP commands."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from homeassistant.loader import async_get_integration

from .const import DOMAIN, LIGHTS
from .profiles import object61_candidates

_POINT_FIELDS = ("id", "smart_object", "type", "join", "value", "updates", "last_seen")


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    """Return an in-memory snapshot; do not reconnect or operate equipment."""
    proxy = getattr(entry, "runtime_data", None)
    if proxy is None:
        proxy = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    points = []
    if proxy is not None:
        for point in proxy.discovered_points.values():
            points.append({key: deepcopy(point[key]) for key in _POINT_FIELDS if key in point})
    points.sort(key=lambda p: (
        -1 if p.get("smart_object") is None else int(p["smart_object"]),
        str(p.get("type", "")), int(p.get("join", 0)),
    ))
    objects = {}
    for point in points:
        owner = "cip" if point.get("smart_object") is None else f"so{point['smart_object']}"
        objects.setdefault(owner, []).append(point)
    configured = [
        {key: deepcopy(point[key]) for key in (*_POINT_FIELDS, "name", "entity_type") if key in point}
        for point in entry.options.get("configured_points", [])
    ]
    integration = await async_get_integration(hass, DOMAIN)
    return {
        "diagnostics_schema_version": 1,
        "integration_version": integration.manifest.get("version"),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "runtime_available": proxy is not None,
        "connection": {
            "configured_mode": proxy.mode if proxy else None,
            "current_mode": proxy.display_mode if proxy else None,
            "connected": bool(proxy and proxy.connected),
        },
        "inventory": {
            "total_points": len(points),
            "counts_by_type": dict(Counter(p.get("type", "unknown") for p in points)),
            "counts_by_object": {key: len(value) for key, value in objects.items()},
            "points_by_object": objects,
        },
        "smart_object_61_reference": {
            "known_light_mappings": deepcopy(list(LIGHTS)),
            "naming_candidates": object61_candidates({p["id"]: p for p in points}),
            "applied_names": dict(entry.options.get("object61_names", {})),
            "observed_points": objects.get("so61", []),
            "light_states": {key: asdict(value) for key, value in proxy.states.items()} if proxy else {},
            "note": "Serial labels are observations; associations with controls have not been inferred.",
        },
        "configured_points": configured,
        "action_capture": proxy.capture.snapshot() if proxy and hasattr(proxy, "capture") else None,
        "notes": [
            "Action recording is passive, limited to five minutes or 2000 events, and lost on integration reload. Start replaces the previous recording.",
            "iPad commands are visible only when the iPad connects through this proxy. Recordings include light commands and manually configured digital commands from HA. Raw frame capture uses the existing data-frame parser; unsupported framing may be absent. Standalone feedback contains decoded joins only.",
            "Only points observed since the current integration load are included; absence is not proof that a join does not exist.",
            "Values are the last received values, not an active read at export time. See last_seen and connection status.",
            "Serial values and user-assigned names are included for identification and may contain private display text.",
            "Connection settings and authentication packets are omitted. Explicit action recordings include parsed CIP data frames and may contain private display text.",
        ],
    }
