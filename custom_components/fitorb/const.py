from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "fitorb"
DEFAULT_NAME = "Fitorb Smart Ring"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONF_HEALTH_POLL_INTERVAL = "health_poll_interval"

DEFAULT_SUMMARY_POLL_INTERVAL = timedelta(minutes=5)
DEFAULT_HEALTH_POLL_INTERVAL = timedelta(minutes=15)
DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_RESPONSE_TIMEOUT = 10.0
DEFAULT_HEALTH_RESPONSE_TIMEOUT = 2.0

CMD_SERVICE_UUID = "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e"
CMD_WRITE_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
CMD_NOTIFY_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
RAW_SERVICE_UUID = "de5bf728-d711-4e47-af26-65e3012a5dc7"
RAW_WRITE_CHAR_UUID = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
RAW_NOTIFY_CHAR_UUID = "de5bf729-d711-4e47-af26-65e3012a5dc7"
