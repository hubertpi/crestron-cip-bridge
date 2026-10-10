from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    DOMAIN,
    PRESENTATION_INPUTS,
    PRESENTATION_OFF_JOIN,
    PRESENTATION_OFF_PULSE,
    SCENES,
)
from .discovered import DiscoveredButton

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    proxy = hass.data[DOMAIN][entry.entry_id]
    points = entry.options.get("configured_points", [])
    scenes = [CrestronSceneButton(proxy, scene) for scene in SCENES]
    presentation = [CrestronPresentationButton(proxy, source) for source in PRESENTATION_INPUTS]
    presentation.append(CrestronPresentationOffButton(proxy))
    discovered = [DiscoveredButton(proxy, p) for p in points if p.get("entity_type") == "button"]
    async_add_entities([*scenes, *presentation, *discovered])


class CrestronSceneButton(ButtonEntity):
    """A captured Object 65 scene press, named for the wall switch."""

    _attr_has_entity_name = True

    def __init__(self, proxy, scene: dict) -> None:
        self.proxy = proxy
        self.scene = scene
        self._attr_unique_id = f"{proxy.entry.entry_id}_scene_{scene['key']}"
        self._attr_name = scene["wall_name"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, proxy.entry.entry_id)},
            name="Crestron AV3",
            manufacturer="Crestron",
            model="AV3 Smart Object 65",
        )

    async def async_press(self) -> None:
        await self.proxy.async_activate_scene(self.scene["key"])


class CrestronPresentationButton(ButtonEntity):
    """A global presentation source action captured on Smart Object 20."""

    _attr_has_entity_name = True

    def __init__(self, proxy, source: dict) -> None:
        self.proxy = proxy
        self.source = source
        self._attr_unique_id = f"{proxy.entry.entry_id}_presentation_{source['key']}"
        self._attr_name = source["name"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, proxy.entry.entry_id)},
            name="Crestron AV3",
            manufacturer="Crestron",
            model="AV3 Smart Object 20",
        )

    async def async_press(self) -> None:
        await self.proxy.async_activate_presentation(self.source["key"])


class CrestronPresentationOffButton(ButtonEntity):
    """Send the captured All Off confirmation directly, without a prompt."""

    _attr_has_entity_name = True
    _attr_name = "Presentation All Off"

    def __init__(self, proxy) -> None:
        self.proxy = proxy
        self._attr_unique_id = f"{proxy.entry.entry_id}_presentation_all_off"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, proxy.entry.entry_id)},
            name="Crestron AV3",
            manufacturer="Crestron",
            model="AV3",
        )

    async def async_press(self) -> None:
        await self.proxy.async_pulse_digital_join(
            PRESENTATION_OFF_JOIN, pulse_duration=PRESENTATION_OFF_PULSE
        )
