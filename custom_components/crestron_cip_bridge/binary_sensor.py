from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN
from .discovered import DiscoveredBinarySensor

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    proxy = hass.data[DOMAIN][entry.entry_id]
    points = entry.options.get("configured_points", [])
    async_add_entities([DiscoveredBinarySensor(proxy, p) for p in points if p.get("entity_type") == "binary_sensor"])
