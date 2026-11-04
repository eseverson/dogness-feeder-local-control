"""Constants for the Dogness feeder camera."""

from typing import Final

DOMAIN: Final = "dogness_feeder"

CONF_DEVICE_ID: Final = "device_id"

DEFAULT_USERNAME: Final = "root"
# Matches catd's `device_id` default in /etc/catd.conf.
DEFAULT_DEVICE_ID: Final = "feeder-1"

RTSP_PORT: Final = 554
# Majestic's main stream; it advertises the ONVIF audio back-channel when
# `rtsp.backchannel: true` is set in /etc/majestic.yaml.
RTSP_PATH: Final = "stream=0"
SNAPSHOT_PATH: Final = "/image.jpg"
