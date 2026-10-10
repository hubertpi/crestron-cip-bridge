"""Previously configured generic CIP switches."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .discovered import DiscoveredSwitch


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    proxy = hass.data[DOMAIN][entry.entry_id]
    points = entry.options.get("configured_points", [])
    async_add_entities([
        DiscoveredSwitch(proxy, point)
        for point in points if point.get("entity_type") == "switch"
    ])
