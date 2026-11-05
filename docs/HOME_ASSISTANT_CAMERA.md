# Home Assistant camera with two-way audio

`catd` gives Home Assistant everything except a usable camera. MQTT cameras can only show stills pushed over a topic, so they can't stream video or take talk-back audio. The `dogness_feeder` custom integration in [`custom_components/dogness_feeder/`](../custom_components/dogness_feeder/) adds one camera entity that does both.

## How the audio gets to the speaker

```
browser mic ──WebRTC/Opus──▶ HA's go2rtc ──RTSP back-channel, PCMU/8000──▶ Majestic ──▶ AO ──▶ speaker amp (GPIO 51)
```

* The camera's `stream_source()` is Majestic's main RTSP stream (`rtsp://<feeder>:554/stream=0`), and the entity declares `CameraEntityCapabilities(two_way_audio=True)`.
* HA's built-in go2rtc pulls that stream. When Majestic advertises an ONVIF back-channel, go2rtc sets it up and transcodes the browser's Opus mic audio to PCMU/8000 for it.
* Majestic plays the audio out the codec's AO and raises `audio.speakerPin` (GPIO 51, the stock firmware's mute bit at `0x201A0020`) while it plays.

The back-channel needs Majestic newer than 2026-05-24 (`master+025b6f6` from 2026-11-04 was tested) with these settings in `/etc/majestic.yaml`. Both are in the overlay patch [`0007`](../patches/firmware/0007-overlay-system-config-REDACTED.patch):

```yaml
audio:
  outputEnabled: true
  speakerPin: 51
rtsp:
  backchannel: true
```

To check a running feeder, send a DESCRIBE with `Require: www.onvif.org/ver20/backchannel`. The SDP should end with `m=audio 0 RTP/AVP 0`, `a=rtpmap:0 PCMU/8000`, `a=sendonly`, `a=control:audio-backchannel`.

Majestic builds that new link mbedtls 3.6, which the OpenIPC tree has carried since 2026-10-01. The `firmware` submodule is pinned past that (#6), so a build from this repo pulls a matching Majestic.

## Install

1. Copy `custom_components/dogness_feeder/` into your HA config's `custom_components/`, or add this repo to HACS as a custom repository. Restart HA.
2. **Settings → Devices & services → Add integration → Dogness Feeder Camera.** Enter the Majestic login (`root` plus the password you set) and catd's `device_id` (default `feeder-1`). For the address, either fill in **Host** with a fixed IP, or leave it empty and keep **Host entity** at `sensor.cat_feeder_stream_url`: the camera then takes the feeder's address from the stream URL catd publishes over MQTT, every time a stream or snapshot starts, so a new DHCP lease needs no reconfiguring.
3. Turn on the camera integration's **Two-way audio** preview feature under **Settings → System → Labs**.
4. Open HA over HTTPS, because browsers only allow microphone access on secure origins. Then open the camera's live view and use the mic button.

The camera appears as its own **Cat Feeder Camera** device, next to the MQTT **Cat Feeder** device. HA 2026.11 no longer lets one integration attach entities to another integration's device, so put both in the same area instead.

Requires Home Assistant 2026.11 or later, with `go2rtc` loaded (it is part of `default_config`). Two-way audio is WebRTC-only, so it won't appear on HLS.

## Limits

* **One viewer.** On 32 MB of RAM, Majestic budgets for about one concurrent live session. Let HA's go2rtc be the only RTSP client and have everything else watch through HA.
* **No echo cancellation.** The feeder's mic picks up its own speaker, so you will hear yourself on the incoming audio.
* **PCMU/8000, RTSP over TCP only.** That's all Majestic's back-channel supports. go2rtc negotiates it on its own.

## Tests

```sh
uv sync --group test
.venv/bin/pytest
```

The tests use `pytest-homeassistant`, HA core's own harness, pinned to 2026.11.0b6 with `homeassistant` overridden to 2026.11.0.
