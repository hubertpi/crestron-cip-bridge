from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN, MEDIA_POWER_SWITCHES
from .discovered import DiscoveredSwitch

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    proxy = hass.data[DOMAIN][entry.entry_id]
    points = entry.options.get("configured_points", [])
    async_add_entities([
        *[DiscoveredSwitch(proxy, p) for p in points if p.get("entity_type") == "switch"],
        *[CrestronMediaPowerSwitch(proxy, item) for item in MEDIA_POWER_SWITCHES],
    ])


class CrestronMediaPowerSwitch(SwitchEntity):
    """On/off command control that stays unknown without device feedback."""

    _attr_has_entity_name = True
    _attr_assumed_state = True

    def __init__(self, proxy, item: dict) -> None:
        self.proxy = proxy
        self.item = item
        self._is_on: bool | None = None
        self._attr_unique_id = f"{proxy.entry.entry_id}_media_power_{item['key']}"
        self._attr_name = item["name"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, proxy.entry.entry_id)},
            name="Crestron AV3",
            manufacturer="Crestron",
            model="AV3 CIP Bridge",
        )

    @property
    def available(self) -> bool:
        return self.proxy.connected

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def extra_state_attributes(self):
        return {
            "crestron_feedback_available": False,
            "crestron_state_source": "last HA command; AV3 feedback not observed",
            "crestron_on_join": self.item["on_join"],
            "crestron_off_join": self.item["off_join"],
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.proxy.async_pulse_digital_join(
            self.item["on_join"], pulse_duration=self.item["on_pulse"]
        )
        # This join is a command only. The AV3 does not report display power,
        # so do not keep an assumed on/off state after sending it.
        self._is_on = None
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.proxy.async_pulse_digital_join(
            self.item["off_join"], pulse_duration=self.item["off_pulse"]
        )
        self._is_on = None
        self.async_write_ha_state()
