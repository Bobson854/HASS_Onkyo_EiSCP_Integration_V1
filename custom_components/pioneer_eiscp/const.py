"""Constants for the Pioneer eISCP integration."""

DOMAIN = "pioneer_eiscp"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"
CONF_MODEL = "model"

DEFAULT_PORT = 60128
DEFAULT_NAME = "Pioneer AVR"
DEFAULT_MODEL = "VSX-1131"

PORT_MIN = 1
PORT_MAX = 65535


def normalize_port(port: int | float | str) -> int:
    """Convert config-flow or legacy entry port values to a valid TCP port int.

    Home Assistant NumberSelector commonly returns floats (e.g. 60128.0).
    """
    try:
        value = int(port)
    except (TypeError, ValueError) as err:
        msg = f"Invalid port: {port!r}"
        raise ValueError(msg) from err
    if not PORT_MIN <= value <= PORT_MAX:
        msg = f"Port out of range: {value}"
        raise ValueError(msg)
    return value

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
RECONNECT_INTERVAL = 30.0
RECOVERY_QUERY_INTERVAL = 300.0

# Setup-time validation (read-only PWRQSTN probe)
VALIDATION_TIMEOUT = 10.0
VALIDATION_READ_TIMEOUT = 5.0

# ISCP command prefixes (3-letter codes)
CMD_POWER = "PWR"
CMD_VOLUME = "MVL"
CMD_MUTE = "AMT"
CMD_INPUT = "SLI"
CMD_LISTENING_MODE = "LMD"
CMD_AUDIO_INFO = "IFA"
CMD_VIDEO_INFO = "IFV"
CMD_HDMI_OUTPUT = "HDO"
CMD_ZONE2_POWER = "ZPW"
CMD_ZONE2_INPUT = "SLZ"
CMD_ZONE2_VOLUME = "ZVL"

QUERY_SUFFIX = "QSTN"

# Queries sent on connect / reconnect (not polled aggressively)
STARTUP_QUERIES: tuple[str, ...] = (
    f"{CMD_POWER}{QUERY_SUFFIX}",
    f"{CMD_VOLUME}{QUERY_SUFFIX}",
    f"{CMD_MUTE}{QUERY_SUFFIX}",
    f"{CMD_INPUT}{QUERY_SUFFIX}",
    f"{CMD_LISTENING_MODE}{QUERY_SUFFIX}",
    f"{CMD_AUDIO_INFO}{QUERY_SUFFIX}",
    f"{CMD_VIDEO_INFO}{QUERY_SUFFIX}",
)

# Main-zone input selector codes (subset; extend via diagnostics / NRI later)
INPUT_SOURCES: dict[str, str] = {
    "00": "video1",
    "01": "video2",
    "02": "tv_cable",
    "03": "video3",
    "04": "video4",
    "05": "video5",
    "06": "video6",
    "07": "video7",
    "08": "extra1",
    "09": "extra2",
    "10": "bd_dvd",
    "11": "strm_box",
    "12": "game",
    "13": "pc",
    "15": "aux",
    "17": "cd",
    "18": "tuner",
    "19": "phono",
    "20": "usb",
    "22": "network",
    "23": "bluetooth",
    "24": "usbdac",
    "25": "hdmi5",
    "26": "hdmi6",
    "27": "hdmi7",
    "28": "optical",
    "29": "coaxial",
    "30": "hdmi1",
    "31": "hdmi2",
    "32": "hdmi3",
    "33": "hdmi4",
}

INPUT_SOURCE_TO_CODE: dict[str, str] = {v: k for k, v in INPUT_SOURCES.items()}

# Listening modes (subset for VSX-class receivers)
LISTENING_MODES: dict[str, str] = {
    "00": "stereo",
    "01": "direct",
    "02": "surround",
    "03": "film",
    "04": "music",
    "05": "game",
    "06": "thx",
    "07": "stereo_thx",
    "08": "theater_dimensional",
    "0C": "pure_audio",
    "0D": "pure_direct",
    "0E": "auto_surround",
    "0F": "whole_house",
}

LISTENING_MODE_TO_CODE: dict[str, str] = {v: k for k, v in LISTENING_MODES.items()}

# Platform lists
PLATFORMS = [
    "media_player",
    "sensor",
    "select",
    "switch",
]

SERVICE_SEND_RAW = "send_raw"
SERVICE_PROBE_CAPABILITIES = "probe_capabilities"

ATTR_ISCP_COMMAND = "iscp_command"
ATTR_RESPONSE = "response"
ATTR_ENTRY_ID = "entry_id"
