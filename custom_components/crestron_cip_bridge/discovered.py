"""Entities backed by user-selected, observed CIP joins."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, SIGNAL_UPDATE


class DiscoveredPointEntity:
    _attr_has_entity_name = True

    def __init__(self, proxy, point):
        self.proxy = proxy
        self.point_id = point["id"]
        self._attr_name = point.get("name") or f"CIP {point['type']} {point['join']}"
        self._attr_unique_id = f"{proxy.entry.entry_id}_{self.point_id.replace(':', '_')}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, proxy.entry.entry_id)},
            name="Crestron AV3",
            manufacturer="Crestron",
            model="AV3 CIP Bridge",
        )

    @property
    def available(self):
        return self.proxy.connected

    @property
    def point(self):
        return self.proxy.discovered_points.get(self.point_id, {})

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update))

    def _handle_update(self, _signal=None):
        self.async_write_ha_state()


class DiscoveredValueSensor(DiscoveredPointEntity, SensorEntity):
    @property
    def native_value(self):
        return self.point.get("value")


class DiscoveredBinarySensor(DiscoveredPointEntity, BinarySensorEntity):
    @property
    def is_on(self):
        value = self.point.get("value")
        return None if value is None else bool(value)


class DiscoveredSwitch(DiscoveredPointEntity, SwitchEntity):
    @property
    def is_on(self):
        value = self.point.get("value")
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs):
        await self.proxy.async_set_discovered_point(self.point_id, True)

    async def async_turn_off(self, **kwargs):
        await self.proxy.async_set_discovered_point(self.point_id, False)


class DiscoveredButton(DiscoveredPointEntity, ButtonEntity):
    async def async_press(self):
        await self.proxy.async_test_discovered_point(self.point_id)


class DiscoveredNumber(DiscoveredPointEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 65535
    _attr_native_step = 1

    @property
    def native_value(self):
        value = self.point.get("value")
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    async def async_set_native_value(self, value):
        await self.proxy.async_set_discovered_point(self.point_id, int(value))
