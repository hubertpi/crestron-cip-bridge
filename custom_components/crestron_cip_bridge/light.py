from __future__ import annotations

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, LIGHTS, SIGNAL_UPDATE
from .proxy import CrestronProxy, LightState


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    proxy: CrestronProxy = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CrestronLight(proxy, light) for light in LIGHTS)


class CrestronLight(LightEntity):
    _attr_has_entity_name = True
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(self, proxy: CrestronProxy, light: dict) -> None:
        self.proxy = proxy
        self.light = light
        self._attr_unique_id = f"{proxy.entry.entry_id}_{light['key']}"
        self._attr_name = proxy.entry.options.get("object61_names", {}).get(light["key"], light["name"])
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, proxy.entry.entry_id)},
            name="Crestron AV3",
            manufacturer="Crestron",
            model="AV3 Smart Object 61",
        )

    @property
    def available(self) -> bool:
        return self.proxy.connected

    @property
    def is_on(self) -> bool | None:
        if self.light.get("mapping_verified") is False and not self._state.received_feedback:
            return None
        return self._state.is_on

    @property
    def brightness(self) -> int | None:
        if self.light.get("mapping_verified") is False and not self._state.received_feedback:
            return None
        return self._state.brightness

    @property
    def extra_state_attributes(self):
        return {"crestron_feedback_received": self._state.received_feedback,
                "crestron_restore_brightness": self._state.restore_brightness,
                "crestron_mapping_verified": self.light.get("mapping_verified", True)}

    @property
    def _state(self) -> LightState:
        return self.proxy.states[self.light["key"]]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update))

    def _handle_update(self, _signal=None) -> None:
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get("brightness")
        if brightness is None:
            await self.proxy.async_command(self.light["key"], turn_on=True)
        else:
            await self.proxy.async_command(self.light["key"], brightness=brightness)

    async def async_turn_off(self, **kwargs) -> None:
        await self.proxy.async_command(self.light["key"], turn_on=False)
