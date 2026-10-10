from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
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


def connection_schema(settings):
    """Use the same connection fields for initial setup and later changes."""
    return vol.Schema(
        {
            vol.Required(CONF_AV3_HOST, default=settings.get(CONF_AV3_HOST, DEFAULT_AV3_HOST)): vol.All(str, vol.Strip, vol.Length(min=1)),
            vol.Required(CONF_AV3_CIP_PORT, default=settings.get(CONF_AV3_CIP_PORT, DEFAULT_CIP_PORT)): vol.All(int, vol.Range(min=1, max=65535)),
            vol.Required(CONF_CONNECTION_MODE, default=settings.get(CONF_CONNECTION_MODE, MODE_AUTO)): vol.In(
                {MODE_AUTO: "Auto", MODE_PROXY: "Proxy", MODE_STANDALONE: "Standalone"}
            ),
            vol.Required(CONF_LISTEN_ADDRESS, default=settings.get(CONF_LISTEN_ADDRESS, DEFAULT_LISTEN_ADDRESS)): vol.All(str, vol.Strip, vol.Length(min=1)),
            vol.Required(CONF_CIP_LISTEN_PORT, default=settings.get(CONF_CIP_LISTEN_PORT, DEFAULT_CIP_PORT)): vol.All(int, vol.Range(min=1, max=65535)),
            vol.Required(CONF_HTTP_PROXY, default=settings.get(CONF_HTTP_PROXY, True)): bool,
            vol.Required(CONF_HTTP_LISTEN_PORT, default=settings.get(CONF_HTTP_LISTEN_PORT, DEFAULT_HTTP_LISTEN_PORT)): vol.All(int, vol.Range(min=1, max=65535)),
            vol.Required(CONF_AV3_HTTP_PORT, default=settings.get(CONF_AV3_HTTP_PORT, DEFAULT_HTTP_PORT)): vol.All(int, vol.Range(min=1, max=65535)),
        }
    )


class CrestronAV3ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(f"{user_input[CONF_AV3_HOST]}:{user_input[CONF_AV3_CIP_PORT]}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Crestron CIP Bridge", data=user_input)

        schema = connection_schema({})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        # Home Assistant injects the ConfigEntry onto OptionsFlow itself.
        return CrestronAV3OptionsFlow()


class CrestronAV3OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["connection", "capture"])


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
                vol.Optional("label", default="iPad action"): str,
            }),
            description_placeholders={"status": snapshot["status"],
                                      "count": str(len(snapshot["events"])),
                                      "mode": proxy.display_mode},
        )


    async def async_step_connection(self, user_input=None):
        errors = {}
        settings = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            endpoint = (user_input[CONF_AV3_HOST].strip().casefold(), user_input[CONF_AV3_CIP_PORT])
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.entry_id == self.config_entry.entry_id:
                    continue
                other = {**entry.data, **entry.options}
                if (other[CONF_AV3_HOST].strip().casefold(), other[CONF_AV3_CIP_PORT]) == endpoint:
                    errors["base"] = "already_configured"
                    break
            if not errors:
                options = dict(self.config_entry.options)
                options.update(user_input)
                # Update endpoint identity and options together; the existing
                # update listener reloads the proxy with the new settings.
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    unique_id=f"{user_input[CONF_AV3_HOST]}:{user_input[CONF_AV3_CIP_PORT]}",
                    options=options,
                )
                return self.async_create_entry(title="", data=options)
            settings.update(user_input)
        return self.async_show_form(
            step_id="connection",
            data_schema=connection_schema(settings),
            errors=errors,
        )

    @property
    def proxy(self):
        return getattr(self.config_entry, "runtime_data", None)
