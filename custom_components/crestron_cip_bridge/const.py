from __future__ import annotations

DOMAIN = "crestron_cip_bridge"
PLATFORMS = ["light", "sensor", "binary_sensor", "switch", "button", "number", "select"]

CONF_AV3_HOST = "av3_host"
CONF_AV3_CIP_PORT = "av3_cip_port"
CONF_LISTEN_ADDRESS = "listen_address"
CONF_CIP_LISTEN_PORT = "cip_listen_port"
CONF_HTTP_PROXY = "http_proxy"
CONF_HTTP_LISTEN_PORT = "http_listen_port"
CONF_AV3_HTTP_PORT = "av3_http_port"
CONF_CONNECTION_MODE = "connection_mode"

DEFAULT_AV3_HOST = "172.26.219.35"
DEFAULT_CIP_PORT = 41794
DEFAULT_LISTEN_ADDRESS = "0.0.0.0"
DEFAULT_HTTP_PORT = 80
DEFAULT_HTTP_LISTEN_PORT = 8001
MODE_PROXY = "proxy"
MODE_STANDALONE = "standalone"
MODE_AUTO = "auto"
AV3_IP_ID = 0x03

SIGNAL_UPDATE = f"{DOMAIN}_update"

# Six mapped dimmers plus the user-requested, inferred Coves row in Object 61.
LIGHTS = (
    # The dimmer-interaction joins follow each light's three-join button group.
    # Pendant (4013) and Linear (4016) were observed directly in captures.
    # Rows 3–6 follow the same sequence as their on/off joins and remain inferred.
    {"key": "pendant", "name": "Pendant", "row": 1, "on_join": 4011, "off_join": 4012, "brightness_join": 11, "analog_index": 0x000A, "on_code": 0xAA, "off_code": 0xAB, "dimmer_code": 0xAC},
    {"key": "linear", "name": "Linear", "row": 2, "on_join": 4014, "off_join": 4015, "brightness_join": 12, "analog_index": 0x000B, "on_code": 0xAD, "off_code": 0xAE, "dimmer_code": 0xAF},
    {"key": "table_task", "name": "Table Task", "row": 3, "on_join": 4017, "off_join": 4018, "brightness_join": 13, "analog_index": 0x000C, "on_code": 0xB0, "off_code": 0xB1, "dimmer_code": 0xB2},
    {"key": "bench_task", "name": "Bench Task", "row": 4, "on_join": 4020, "off_join": 4021, "brightness_join": 14, "analog_index": 0x000D, "on_code": 0xB3, "off_code": 0xB4, "dimmer_code": 0xB5},
    {"key": "soffit", "name": "Soffit", "row": 5, "on_join": 4023, "off_join": 4024, "brightness_join": 15, "analog_index": 0x000E, "on_code": 0xB6, "off_code": 0xB7, "dimmer_code": 0xB8},
    {"key": "night_lights", "name": "Night Lights", "row": 6, "on_join": 4026, "off_join": 4027, "brightness_join": 16, "analog_index": 0x000F, "on_code": 0xB9, "off_code": 0xBA, "dimmer_code": 0xBB},
    # Object 61 analog join 18 tracked the Coves level across the captured
    # scenes (full in All On/High/Med, zero in Low/Off). Individual Coves
    # commands are still unverified; the old join-17 readback was always zero.
    {"key": "coves", "name": "Coves", "row": 7, "on_join": 4029, "off_join": 4030, "brightness_join": 18, "analog_index": 0x0011, "on_code": 0xBC, "off_code": 0xBD, "mapping_verified": False},
)

LIGHTS_BY_ANALOG = {light["analog_index"]: light["key"] for light in LIGHTS}
LIGHTS_BY_DIGITAL = {
    code: (light["key"], is_on)
    for light in LIGHTS
    for code, is_on in ((light["on_code"], True), (light["off_code"], False))
}

# Object 65 scene controls observed from the iPad. Expose the wall-switch names
# in Home Assistant; the iPad labels differ by position.
SCENES = (
    {"key": "all_on", "wall_name": "All On", "ipad_name": "High", "digital_join": 4011},
    {"key": "high", "wall_name": "High", "ipad_name": "Medium", "digital_join": 4013},
    {"key": "med", "wall_name": "Med", "ipad_name": "Low", "digital_join": 4015},
    {"key": "low", "wall_name": "Low", "ipad_name": "AV", "digital_join": 4017},
    {"key": "off", "wall_name": "Off", "ipad_name": "Off", "digital_join": 4019},
)

# Captured top-level CIP button joins. These are separate ON and OFF commands;
# no AV3 feedback was present, so the HA entity state remains unknown.
MEDIA_POWER_SWITCHES = (
    {"key": "projector", "name": "Projector", "on_join": 703, "off_join": 704,
     "on_pulse": 0.043, "off_pulse": 0.032},
    {"key": "sharp_touch", "name": "Sharp Touch", "on_join": 708, "off_join": 709,
     "on_pulse": 0.029, "off_pulse": 0.036},
    {"key": "sony_tv_left", "name": "Sony TV Left", "on_join": 711, "off_join": 712,
     "on_pulse": 0.034, "off_pulse": 0.034},
    {"key": "sony_tv_right", "name": "Sony TV Right", "on_join": 714, "off_join": 715,
     "on_pulse": 0.033, "off_pulse": 0.099},
)

# All four output Smart Objects were individually captured while selecting
# the same four inputs. Each selection sends analog join 1 first, then pulses
# the corresponding digital input join.
MEDIA_INPUTS = (
    {"key": "room_pc", "name": "Room PC", "analog_value": 3, "digital_join": 13},
    {"key": "showcase_l", "name": "Showcase L", "analog_value": 4, "digital_join": 14},
    {"key": "showcase_r", "name": "Showcase R", "analog_value": 5, "digital_join": 15},
    {"key": "table_input", "name": "Table Input", "analog_value": 6, "digital_join": 16},
)

# Global presentation controls from Smart Object 20. These differ from the
# individual display source buttons above: the AV3 interprets each as a
# presentation action, including turning displays on when required.
PRESENTATION_INPUTS = (
    {"key": "room_pc", "name": "Present Room PC", "analog_value": 3, "digital_join": 4013},
    {"key": "showcase_l", "name": "Present Showcase L", "analog_value": 4, "digital_join": 4014},
    {"key": "showcase_r", "name": "Present Showcase R", "analog_value": 5, "digital_join": 4015},
    {"key": "table_input", "name": "Present Table Input", "analog_value": 6, "digital_join": 4016},
)

PRESENTATION_OFF_JOIN = 102
PRESENTATION_OFF_PULSE = 0.32

MEDIA_INPUT_DISPLAYS = (
    {"key": "projector", "name": "Projector", "smart_object": 75},
    {"key": "sharp_touch", "name": "Sharp Touch", "smart_object": 76},
    {"key": "sony_tv_left", "name": "Sony TV Left", "smart_object": 77},
    {"key": "sony_tv_right", "name": "Sony TV Right", "smart_object": 78},
)
