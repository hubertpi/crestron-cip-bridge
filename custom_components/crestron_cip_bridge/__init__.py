from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS
from .proxy import CrestronProxy

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    registry = er.async_get(hass)
    retired_ids = {
        f"{entry.entry_id}_media_{kind}_{display}"
        for kind in ("power", "input")
        for display in ("projector", "sharp_touch", "sony_tv_left", "sony_tv_right")
    }
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (entity.platform == DOMAIN and entity.domain in ("switch", "select")
                and entity.unique_id in retired_ids):
            registry.async_remove(entity.entity_id)
    proxy = CrestronProxy(hass, entry)
    try:
        await proxy.async_start()
    except OSError as err:
        _LOGGER.error("Could not start Crestron proxy listeners: %s", err)
        return False
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = proxy
    entry.runtime_data = proxy
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    proxy: CrestronProxy = hass.data[DOMAIN].pop(entry.entry_id)
    await proxy.async_stop()
    entry.runtime_data = None
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
