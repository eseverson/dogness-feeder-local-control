# Dogness Pet Feeder — Local Control

Reverse-engineering and re-flashing a cloud-tethered **Dogness pet-feeder camera** (HiSilicon Hi3518EV200) so it runs entirely under local
control — no vendor cloud, no cloud P2P, no Alexa dependency. The stock firmware
is replaced with [OpenIPC](https://openipc.org) plus a small custom daemon,
**`catd`**, that speaks the feeder's MCU protocol directly and bridges it to
MQTT with native Home Assistant auto-discovery.

This repo is the clean write-up: what the device is, how the original firmware
worked, how we got in, what we changed, and what we built. The two upstream
trees (OpenIPC firmware and U-Boot) are pinned as submodules; **every change we
made to them is carried as a patch** under [`patches/`](patches/).

***

## Result

Flash the build and the feeder comes up on WiFi, connects to your MQTT broker,
and Home Assistant auto-discovers a **Cat Feeder** device with:

* **Feed now** (button) + **portion weight** (number), with live **feed status**
  and **result** (success / jam / low-food)

* **Chute blocked** (binary sensor)

* **6 schedule slots** — per-slot time, weight, enable

* **IR LED**, **IR-cut filter**, **status LED**, **light monitor** (auto
  day/night)

* **Motion** (binary sensor) + ambient **brightness**

* **MCU** version / time / clock-drift / time-sync / motor-test

* **Video** (RTSP via Majestic) and **snapshot** / **audio** stream URLs

Everything runs on-device and on your LAN.

***

## The device

| Property     | Value                                                                                                                 |
| ------------ | --------------------------------------------------------------------------------------------------------------------- |
| Product      | F01WH pet-feeder camera (Dogness; several OEM twins — see [`docs/DEVICE_REFERENCE.md`](docs/DEVICE_REFERENCE.md) §17) |
| SoC          | HiSilicon Hi3518EV200 (ARM926EJ-S, ARMv5TE) — \~32 MB RAM                                                             |
| Flash        | 8 MB SPI NOR (W25Q64), **upgraded to 32 MB** (Boya BY25Q256FSSIG) for the OpenIPC build                               |
| Camera       | 720p image sensor (JXH62)                                                                                             |
| WiFi         | Realtek RTL8188FU (internal USB)                                                                                      |
| **Feed MCU** | **STC15W408AS** (8051-class) — drives the feed motor and returns a per-feed status to the SoC                         |
| Cloud        | vendor phone app + cloud; Amazon Alexa support                                                                        |

The important architectural fact: **the SoC has no direct GPIO path to the feed
motor.** All feeding goes over a UART link to the STC15 MCU, which runs the
physical feed cycle and reports the result back. Take over that UART and you own
the feeder. Full hardware reference (flash layout, GPIO map, UART
channels, kernel modules) is in [`docs/DEVICE_REFERENCE.md`](docs/DEVICE_REFERENCE.md).

***

## Original firmware — how it worked

Out of the box this is a cloud device: you drive it — including feeding — from a
phone app, with Amazon Alexa support layered on through an on-device MQTT bridge.
The point that matters for this project: the **application SoC does not run the
feed motor itself.** It relays feed and schedule commands to the STC15 MCU over a
UART (115200 8N1), and the MCU runs the motor and reports back.

### The MCU UART protocol

This is the wire format `catd` speaks and the MCU acts on — binary frames,
`FF FF … 0A`, no checksum, ≤24 bytes. The two that matter:

```
TX MANUAL FEED (14B):
   FF FF 01 0A 3A 09 03 0E 0B <weight> 00 00 00 0A
                  ─────────── manual marker

TX AUTO FEED (14B):
   FF FF 01 0A A5 A7 7F <hh> <mm> <cnt_lo> <cnt_hi> 11 <delay> <weight>
                  ──────── auto marker
```

The MCU replies with a result frame (command echo, a success/fail flag, and
status fields), an unsolicited ASCII version banner on first contact, and an
async `0x05` error frame when a cycle fails (e.g. an empty hopper). Full packet
reference and response parsing: [`docs/MCU_PROTOCOL.md`](docs/MCU_PROTOCOL.md).

> **Gotcha that shaped everything:** the stock feed thread reboots the device
> after a run of unanswered MCU queries (`SUPPORT_FEED_FUNCTION=1`). Any takeover
> has to keep that thread satisfied or stop it running the feed loop.

***

## Initial access

1. **Known-default root.** The stock firmware exposes **telnet on port 23** with
   `root` / **`059AnkJ`** — a generic password baked into many HiSilicon OEM
   camera firmwares and documented online, not unique to this unit. That alone
   is a root shell on the running device over the network or serial console.
2. **Serial console.** UART0 pads on the board give a 115200 8N1 console —
   U-Boot, the Linux boot log, and a login prompt. (Pinout in
   [`docs/DEVICE_REFERENCE.md`](docs/DEVICE_REFERENCE.md) §4; annotated board
   photo in [`images/`](images/).)
3. **Flash dump + RE.** Dumped the 8 MB W25Q64 with a CH341A and a SOIC-8 clip
   (`flashrom`), unpacked the squashfs rootfs, and inspected the vendor binaries
   to work out the MCU serial protocol and the app/MQTT command flow.
4. **GPIO mapping.** Brute-forced the GPIO map by toggling pins and watching the
   hardware — WiFi power (GPIO 38, active-low), status/IR LEDs, the IR-cut
   solenoid, and UART2 (pins 51/52) to the MCU.

***

## What we did — OpenIPC port

Rather than patch the vendor rootfs, we moved the device onto OpenIPC's
buildroot for the hi3518ev200. The non-trivial parts (all carried as patches):

* **32 MB flash upgrade.** The stock 8 MB part is too small for a comfortable
  OpenIPC "ultimate" build, so we swapped in a Boya **BY25Q256FSSIG** (32 MB,
  drop-in SOIC-8). Neither U-Boot nor the kernel recognized its JEDEC ID
  (`0x68 0x49 0x19`), and the stock 32 MB rootfs image was built for NAND
  geometry. The full three-layer fix (U-Boot SPI-NOR table, kernel `spi-nor`
  ID, squashfs-not-UBI rootfs) plus the in-circuit `loady` flashing dance is in
  [`docs/BY25Q256_UPGRADE.md`](docs/BY25Q256_UPGRADE.md).

* **U-Boot patches** — BY25Q256 JEDEC ID, extended baud table + a working PL011
  `setbrg` (so 921600 actually works for \~8× faster YMODEM transfers), env-baud
  re-apply after relocate, uclibc toolchain prefix, 32 MB env defaults.
  ([`patches/u-boot/`](patches/u-boot/))

* **Kernel patches** — add the BY25Q256 SPI-NOR ID (native 4-byte opcodes),
  enable UART1/UART2, disable the unused FEMAC ethernet.
  ([`patches/kernel/`](patches/kernel/), also bundled in firmware patch 0005)

* **WiFi** — RTL8188FU driver package + firmware blob for the internal adapter.

* **Sensor** — the JXH62 720p profile + load script so OpenIPC drives the
  onboard camera.

* **Recovery** — a fallback initramfs + recovery overlay so a bad flash is
  survivable.

See [`patches/firmware/`](patches/firmware/) for the topical breakdown
(`0001` … `0007`).

***

## What we built — `catd`

`catd` is the replacement for that entire vendor stack: one C daemon
(buildroot package, depends only on `mosquitto`) that holds `/dev/ttyAMA2` open,
speaks the MCU protocol directly, drives the LED/IR GPIOs, and bridges
everything to MQTT. Source lives in the firmware patch
[`patches/firmware/0001-catd-mqtt-bridge-package.patch`](patches/firmware/0001-catd-mqtt-bridge-package.patch)
(`general/package/catd/`).

What it does:

* **MCU master.** Opens UART2 once and keeps it open (working around the
  open-glitch where the MCU latches a `0xFF` framing error — `catd` flushes 16
  nulls on connect). Encodes manual/auto feed and time-sync packets; parses
  feed-result, chute-blocked, version, and the async `0x05` feed-error frames.

* **Home Assistant MQTT discovery.** Publishes config to `homeassistant/cat/*`
  so HA stands up the whole **Cat Feeder** device automatically — no YAML. (See
  the entity list under [Result](#result).)

* **GPIO control.** IR LED, IR-cut filter, status LED, and a light-monitor loop
  for automatic day/night switching, all exposed as MQTT switches/sensors.

* **Scheduling.** Six meal slots maintained on-device and pushed to the MCU.

* **Lifecycle.** `S85catd` init with a shutdown path.

Config is a flat `/etc/catd.conf` (broker host/port, device id, UART device,
GPIO numbers, media URLs).

***

## Repository layout

```
README.md                  ← you are here
docs/
  DEVICE_REFERENCE.md       complete hardware reference (flash, GPIO, UART, modules)
  MCU_PROTOCOL.md           STC15 UART protocol (packets, responses)
  BY25Q256_UPGRADE.md       8→32 MB SPI-NOR swap: u-boot/kernel/rootfs fixes + flashing
  INSTALL.md                flashing on a real feeder + recovery
patches/
  firmware/                 our changes to the OpenIPC firmware tree (topical, 0001–0007)
  u-boot/                   our U-Boot patches (BY25Q256, baud, ergonomics)
  kernel/                   BY25Q256 SPI-NOR id (also bundled in firmware/0005)
scripts/                    build.py / flash.py / mcu_tool.sh + helpers
advisories/                 security advisories for the ORIGINAL vendor firmware
images/                     annotated board photo
firmware/                   submodule → openipc/firmware @ b581a5ad (pinned base)
u-boot-hi3516cv200/         submodule → OpenIPC/u-boot-hi3516cv200 @ 77f79d9 (pinned base)
```

***

## Reproduce

```sh
git clone <this-repo> dogness-feeder-local-control
cd dogness-feeder-local-control

# fetch the upstream trees at their pinned base commits
git submodule update --init

# apply our patches on top
( cd u-boot-hi3516cv200 && for p in ../patches/u-boot/*.patch; do git apply "$p"; done )
( cd firmware           && for p in ../patches/firmware/*.patch; do git apply "$p"; done )
```

> **Before you build — set your own credentials.** Patch
> `0007-overlay-system-config-REDACTED.patch` ships with the WiFi PSK, root
> password, and authorized SSH key **removed** (see [Security](#security--redaction)).
> After applying it, edit `firmware/general/overlay/etc/network/interfaces.d/wlan0`
> (set `YOUR_SSID` / `YOUR_WIFI_PASSWORD`) and set a root password / SSH key in
> the overlay, or the image will boot with no usable login.

Build U-Boot and the 32 MB image, then flash, following
[`docs/BY25Q256_UPGRADE.md`](docs/BY25Q256_UPGRADE.md):

```sh
cd firmware
make BOARD=hi3518ev200-nor-ultimate     # buildroot applies the kernel patch automatically
```

That builds the artifacts. Getting them onto an actual feeder — including the
no-soldering telnet path, SSH updates, and the (very recoverable) brick story —
is **[Installing on your own feeder](#installing-on-your-own-feeder)** below.

***

## Installing on your own feeder

Full procedure, every flashing path, and recovery are in
**[`docs/INSTALL.md`](docs/INSTALL.md)**. The short version:

* **32 MB ultimate (recommended).** Swap the stock 8 MB flash for a BY25Q256
  ([`docs/BY25Q256_UPGRADE.md`](docs/BY25Q256_UPGRADE.md)), then write the full
  image with a CH341A + SOIC-8 clip (`flashrom -p ch341a_spi -w full-…bin`).
  Update later over SSH with [`scripts/flash.py`](scripts/flash.py).

* **8 MB lite (no soldering).** The stock firmware's telnet (`root` / `059AnkJ`)
  lets you `wget` + `flashcp` a lite image onto the running device
  ([`scripts/flash_rootfs_telnet.sh`](scripts/flash_rootfs_telnet.sh)) — but the
  32 MB build won't fit the stock chip, and lite was left experimental.

> **You can't really brick it.** Worst case, clip a SOIC-8 onto the flash chip and
> rewrite it with the CH341A — the same write as a clean install. A bad kernel or
> rootfs is recovered from U-Boot over UART; a bad U-Boot, with the clip. Keep a
> known-good image and the clip on hand.

***

## Security & redaction

Patch `0007-overlay-system-config-REDACTED.patch` ships with the WiFi PSK, root password, and authorized SSH key stripped out, and no device UID or TUTK identifier appears anywhere in this repository. Set your own credentials before building — see [Reproduce](#reproduce).

The **stock firmware** has three reported defects of its own, written up as a separate advisory set in [`advisories/`](advisories/): a cleartext cloud plane authenticated by the device UID alone and carrying fleet-wide hardcoded keys, an always-on telnet daemon with a static root password, and an unsigned firmware update fetched over plain HTTP at every boot. None of them apply to the OpenIPC + `catd` build this repository produces — it has no vendor cloud stack, no telnet daemon, and no auto-update client. Start at [`advisories/README.md`](advisories/README.md).

***

## License

Our code (`catd`, scripts, docs) is MIT. The `firmware/` and
`u-boot-hi3516cv200/` submodules are upstream OpenIPC projects under their own
licenses; the patches in [`patches/`](patches/) apply on top of them.
