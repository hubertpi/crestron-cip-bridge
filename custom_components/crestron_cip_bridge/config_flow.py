from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from .discovery import describe_point
from .profiles import object61_candidates
from .const import (
    CONF_AV3_CIP_PORT,
    CONF_AV3_HOST,
    CONF_AV3_HTTP_PORT,
    CONF_CONNECTION_MODE,
    CONF_CIP_LISTEN_PORT,
    CONF_HTTP_LISTEN_PORT,
    CONF_HTTP_PROXY,
    CONF_LISTEN_ADDRESS,
    DEFAULT_AV3_HOST,
    DEFAULT_CIP_PORT,
    DEFAULT_HTTP_PORT,
    DEFAULT_HTTP_LISTEN_PORT,
    DEFAULT_LISTEN_ADDRESS,
    DOMAIN,
    MODE_PROXY,
    MODE_STANDALONE,
    MODE_AUTO,
)


class CrestronAV3ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(f"{user_input[CONF_AV3_HOST]}:{user_input[CONF_AV3_CIP_PORT]}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Crestron CIP Bridge", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_AV3_HOST, default=DEFAULT_AV3_HOST): str,
                vol.Required(CONF_AV3_CIP_PORT, default=DEFAULT_CIP_PORT): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Required(CONF_CONNECTION_MODE, default=MODE_AUTO): vol.In(
                    {MODE_AUTO: "Auto", MODE_PROXY: "Proxy", MODE_STANDALONE: "Standalone"}
                ),
                vol.Required(CONF_LISTEN_ADDRESS, default=DEFAULT_LISTEN_ADDRESS): str,
                vol.Required(CONF_CIP_LISTEN_PORT, default=DEFAULT_CIP_PORT): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Required(CONF_HTTP_PROXY, default=True): bool,
                vol.Required(CONF_HTTP_LISTEN_PORT, default=DEFAULT_HTTP_LISTEN_PORT): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Required(CONF_AV3_HTTP_PORT, default=DEFAULT_HTTP_PORT): vol.All(int, vol.Range(min=1, max=65535)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        # Home Assistant injects the ConfigEntry onto OptionsFlow itself.
        return CrestronAV3OptionsFlow()


class CrestronAV3OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["connection", "discover", "object61", "capture", "digital_control"])

    async def async_step_digital_control(self, user_input=None):
        if user_input is not None:
            obj = user_input["smart_object"] or None
            from .discovery import point_id
            item = {"id": point_id(obj, "digital", user_input["join"]),
                    "smart_object": obj, "type": "digital", "join": user_input["join"],
                    "name": user_input["name"].strip(), "entity_type": user_input["entity_type"],
                    "mapping_verified": False}
            options = dict(self.config_entry.options)
            options["configured_points"] = [p for p in options.get("configured_points", [])
                                            if p["id"] != item["id"]] + [item]
            return self.async_create_entry(title="", data=options)
        points = getattr(self.proxy, "discovered_points", {})
        labels = []
        for point in points.values():
            obj = point.get("smart_object")
            if point["type"] != "serial" or not str(point.get("value", "")).strip():
                continue
            if obj in (20, 65, 70, 75, 76, 77, 78) or (obj is None and 70 <= point["join"] <= 73):
                labels.append(f"- {'CIP' if obj is None else 'Object ' + str(obj)} S{point['join']}: {point['value']}")
        return self.async_show_form(step_id="digital_control", data_schema=vol.Schema({
            vol.Required("name"): str,
            vol.Required("smart_object", default=0): vol.All(int, vol.Range(min=0, max=65535)),
            vol.Required("join"): vol.All(int, vol.Range(min=1, max=32768)),
            vol.Required("entity_type", default="button"): vol.In({"button": "Momentary button", "switch": "Held digital switch"}),
        }), description_placeholders={"labels": "\n".join(sorted(labels)) or "No labels received yet."})

    async def async_step_capture(self, user_input=None):
        proxy = self.proxy
        if proxy is None:
            return self.async_abort(reason="capture_unavailable")
        if user_input is not None:
            if user_input["action"] == "start":
                proxy.capture.start(user_input.get("label", "Unnamed action"),
                                    proxy.discovered_points, proxy.display_mode)
                return self.async_abort(reason="capture_started")
            proxy.capture.stop()
            return self.async_abort(reason="capture_stopped")
        snapshot = proxy.capture.snapshot()
        return self.async_show_form(
            step_id="capture",
            data_schema=vol.Schema({
                vol.Required("action", default="stop" if proxy.capture.active else "start"):
                    vol.In({"start": "Start new recording (replaces previous)", "stop": "Stop recording"}),
                vol.Optional("label", default="Projector - Table Input 1"): str,
            }),
            description_placeholders={"status": snapshot["status"],
                                      "count": str(len(snapshot["events"])),
                                      "mode": proxy.display_mode},
        )

    async def async_step_object61(self, user_input=None):
        if user_input is not None and hasattr(self, "_object61_candidates"):
            options = dict(self.config_entry.options)
            names = dict(options.get("object61_names", {}))
            names.update({p["key"]: p["name"] for p in self._object61_candidates})
            options["object61_names"] = names
            return self.async_create_entry(title="", data=options)
        points = getattr(self.proxy, "discovered_points", {})
        self._object61_candidates = object61_candidates(points)
        if sum(p["mapping_verified"] for p in self._object61_candidates) != 6:
            return self.async_abort(reason="object61_incomplete")
        preview = "\n".join(
            f"- {p['name']}: name S{p['label_join']}, brightness A{p['brightness_join']}, "
            f"on/off D{p['on_join']}/D{p['off_join']}"
            + (" (inferred; unverified)" if not p["mapping_verified"] else "")
            for p in self._object61_candidates
        )
        return self.async_show_form(
            step_id="object61", data_schema=vol.Schema({}),
            description_placeholders={"preview": preview},
        )

    async def async_step_connection(self, user_input=None):
        if user_input is not None:
            options = dict(self.config_entry.options)
            options.update(user_input)
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="connection",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION_MODE,
                        default=self.config_entry.options.get(
                            CONF_CONNECTION_MODE,
                            self.config_entry.data.get(CONF_CONNECTION_MODE, MODE_AUTO),
                        ),
                    ): vol.In({MODE_AUTO: "Auto", MODE_PROXY: "Proxy", MODE_STANDALONE: "Standalone"}),
                }
            ),
        )

    @property
    def proxy(self):
        return getattr(self.config_entry, "runtime_data", None)

    async def async_step_discover(self, user_input=None):
        proxy = self.proxy
        points = getattr(proxy, "discovered_points", {}) if proxy else {}
        if not points:
            return self.async_show_form(
                step_id="discover",
                data_schema=vol.Schema({}),
                errors={"base": "no_points"},
            )
        if user_input is not None:
            self.selected_point = points[user_input["point"]]
            if self.selected_point["type"] == "serial" or (self.selected_point.get("smart_object") is not None and self.selected_point["type"] != "digital"):
                self.read_only = True
                return await self.async_step_name()
            self.read_only = False
            return await self.async_step_test()
        choices = {key: describe_point(point) for key, point in sorted(points.items())}
        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema({vol.Required("point"): vol.In(choices)}),
        )

    async def async_step_test(self, user_input=None):
        point = self.selected_point
        proxy = self.proxy
        if user_input is not None:
            try:
                if user_input.get("send_test"):
                    value = user_input.get("test_value")
                    await proxy.async_test_discovered_point(point["id"], value)
            except (RuntimeError, ValueError, OSError):
                return self.async_show_form(
                    step_id="test",
                    data_schema=self._test_schema(point),
                    errors={"base": "test_failed"},
                )
            return await self.async_step_name()
        return self.async_show_form(step_id="test", data_schema=self._test_schema(point))

    def _test_schema(self, point):
        if point["type"] == "digital":
            return vol.Schema({vol.Optional("send_test", default=False): bool})
        current = point.get("value")
        if not isinstance(current, int):
            current = 0
        return vol.Schema(
            {
                vol.Optional("send_test", default=False): bool,
                vol.Required("test_value", default=current): vol.All(int, vol.Range(min=0, max=65535)),
            }
        )

    async def async_step_name(self, user_input=None):
        point = self.selected_point
        if user_input is not None:
            configured = list(self.config_entry.options.get("configured_points", []))
            entry = {
                **point,
                "name": user_input["name"].strip(),
                "entity_type": user_input["entity_type"],
            }
            configured = [item for item in configured if item["id"] != entry["id"]]
            configured.append(entry)
            options = dict(self.config_entry.options)
            options["configured_points"] = configured
            return self.async_create_entry(title="", data=options)
        point_type = point["type"]
        if self.read_only:
            entity_choices = {"sensor": "Read-only sensor"}
        elif point_type == "digital":
            entity_choices = {
                "binary_sensor": "Read-only binary sensor",
                "switch": "Switch",
                "button": "Momentary button",
            }
        else:
            entity_choices = {"sensor": "Read-only sensor", "number": "Number control"}
        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=f"CIP {point_type} {point['join']}"): str,
                    vol.Required("entity_type", default=next(iter(entity_choices))): vol.In(entity_choices),
                }
            ),
            description_placeholders={
                "point": f"{point.get('smart_object') or 'CIP'} / {point_type} join {point['join']}",
                "test_note": "Smart Object analog and serial points are read-only in this build."
                if self.read_only
                else "Test one point at a time; it may operate physical equipment.",
            },
        )
