from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MEDIA_INPUTS, MEDIA_INPUT_DISPLAYS

NEUTRAL_OPTION = "Select Input"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    proxy = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [CrestronMediaInputSelect(proxy, display) for display in MEDIA_INPUT_DISPLAYS]
    )


class CrestronMediaInputSelect(SelectEntity):
    """Command selector that returns to a neutral state after each route command."""

    _attr_has_entity_name = True

    def __init__(self, proxy, display: dict) -> None:
        self.proxy = proxy
        self.display = display
        self._attr_unique_id = f"{proxy.entry.entry_id}_media_input_{display['key']}"
        self._attr_name = f"{display['name']} Input"
        self._attr_options = [NEUTRAL_OPTION, *(item["name"] for item in MEDIA_INPUTS)]
        self._attr_current_option = NEUTRAL_OPTION
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, proxy.entry.entry_id)},
            name="Crestron AV3",
            manufacturer="Crestron",
            model="AV3 CIP Bridge",
        )

    @property
    def available(self) -> bool:
        return self.proxy.connected

    async def async_select_option(self, option: str) -> None:
        """Send a captured route command, leaving the selector at its prompt."""
        if option == NEUTRAL_OPTION:
            return
        source = next((item for item in MEDIA_INPUTS if item["name"] == option), None)
        if source is None:
            raise ValueError(f"Unsupported media input: {option}")

        await self.proxy.async_select_media_input(
            self.display["smart_object"],
            source["analog_value"],
            source["digital_join"],
        )
        # current_option intentionally remains neutral: AV source feedback was
        # not observed, and every input must remain re-selectable.
        self.async_write_ha_state()
