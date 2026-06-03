# Dogness Pet Feeder — Complete Device Reference

> _Curated from the project's working notes. The OpenIPC build helpers referenced below (`build-uboot.sh`,_ _`build-full-image.sh`,_ _`flash_rootfs_ssh.sh`) live in_ _[`scripts/`](../scripts/)_ _and run from the repo root;_ _`firmware/`_ _and_ _`u-boot-hi3516cv200/`_ _are git submodules pinned to their upstream base commit, with our changes applied from_ _[`patches/`](../patches/)._

## 1. Device Overview

| Property      | Value                                                                                                           |
| ------------- | --------------------------------------------------------------------------------------------------------------- |
| Product       | L8-SI Pet Feeder Camera (Dogness / Wopet)                                                                       |
| SoC           | HiSilicon Hi3518EV200 (ARM926EJ-S, ARMv5TE)                                                                     |
| RAM           | 64 MB (32 MB Linux / 32 MB MMZ media zone)                                                                      |
| Flash         | 8 MB SPI NOR (W25Q64), upgraded to 32 MB (Boya BY25Q256FSSIG) — see [BY25Q256\_UPGRADE.md](BY25Q256_UPGRADE.md) |
| Camera Sensor | SmartSens SC1045, 720p, parallel DVP, I2C control, 24 MHz clock                                                 |
| WiFi          | Realtek RTL8188EU/FU (USB), driver `8188fu.ko`                                                                  |
| MCU           | STC15W408AS (8051-compatible, 8 KB flash) — motor/feed co-controller                                            |
| Audio         | Hi3518E internal codec (TLV320AIC31 present in firmware but unused)                                             |
| Vendor        | Guangzhou Jiake / IPCAME                                                                                        |
| Board Type    | `DOGNESS_PETS_V200_BREAD_DEVICE` (NVRAM), `LIUBINGHUA_PETS_V200_BOARD` (env)                                    |

### Network Access

| Method      | Details                                                         |
| ----------- | --------------------------------------------------------------- |
| SSH         | Dropbear, port 22 (custom ROM)                                  |
| Telnet      | Port 23 (original firmware, root / 059AnkJ)                     |
| HA HTTP API | Port 8088 (`/status`, `/led/{on,off,auto}`, `/feed/{portions}`) |
| P2P / Cloud | TUTK (ThroughTek), UID `<REDACTED-TUTK-UID>`, type `AH264`      |
| MQTT        | `mqtt_alex` binary for Alexa integration (original firmware)    |

***

## 2. Flash Layout

### 8 MB Layout (Original Chip)

| mtd | Offset   | Size    | Name   | Type                        |
| --- | -------- | ------- | ------ | --------------------------- |
| 0   | 0x000000 | 384 KB  | boot   | U-Boot                      |
| 1   | 0x060000 | 1920 KB | kernel | Linux 3.4.35 uImage         |
| 2   | 0x1E0000 | 4864 KB | rootfs | squashfs (RO)               |
| 3   | 0x6C0000 | 256 KB  | ui     | squashfs (RO)               |
| 4   | 0x700000 | 768 KB  | conf   | JFFS2 (RW) at `/mnt/config` |

U-Boot mtdparts: `hi_sfc:384k(boot),1920k(kernel),4864k(rootfs),256k(ui),768k(conf)`

### 32 MB Layout (After BY25Q256 Chip Upgrade, OpenIPC ultimate)

| mtd | Offset   | Size      | Name   | Type / Notes                                                      |
| --- | -------- | --------- | ------ | ----------------------------------------------------------------- |
| 0   | 0x000000 | 320 KB    | boot   | U-Boot 2010.06 (patched for BY25Q256, baud table, env-baud apply) |
| —   | 0x040000 | 64 KB     | (env)  | `CONFIG_ENV_OFFSET=0x40000` — saveenv lives in u-boot region tail |
| 1   | 0x050000 | 64 KB     | env    | mtdparts label only (informational; real env is at 0x40000)       |
| 2   | 0x060000 | 3072 KB   | kernel | Linux 4.9.37 uImage (\~1.8MB)                                     |
| 3   | 0x360000 | \~28.6 MB | rootfs | squashfs (\~6.6MB) + remaining 0xFF                               |

U-Boot mtdparts: `hi_sfc:320k(boot),64k(env),3072k(kernel),-(rootfs)`

U-Boot bootargs (32 MB):

```
mem=32M console=ttyAMA0,115200 panic=20 root=/dev/mtdblock3 rootfstype=squashfs init=/init mtdparts=${mtdparts} ${extras}
```

> **Don't use UBI here.** OpenIPC's prebuilt `full-hi3518ev200-ultimate-32mb.bin`
> ships a UBI rootfs at `0x360000`, but it was built with NAND geometry
> (`min_io_size=2048`, `data_offset=4096`) and will not attach on NOR
> (which expects `data_offset=2112`). Use the squashfs rootfs from
> `openipc.hi3518ev200-nor-ultimate/rootfs.squashfs.hi3518ev200`
> instead — that's what `scripts/build-full-image.sh`
> defaults to.

Build the flashable image:

```sh
./scripts/build-uboot.sh                        # → u-boot-hi3518ev200-by25q256.bin
FLASH_SIZE=32mb ./scripts/build-full-image.sh   # → full-hi3518ev200-ultimate-32mb.bin
```

***

## 3. GPIO Pin Map

| Group | Pin | GPIO# | Function                   | Direction                                              |
| ----- | --- | ----- | -------------------------- | ------------------------------------------------------ |
| 0     | 0   | —     | IR LED                     | Output (reversed if `/mnt/config/irled_revers` exists) |
| 0     | 2   | —     | Status LED (green)         | Output                                                 |
| 4     | 5   | 37    | IR Cut Filter              | Output (reversed if `/mnt/config/ircut_revers` exists) |
| 8     | 0   | —     | IR Cut A (solenoid driver) | Output                                                 |
| 8     | 1   | —     | IR Cut B (complementary)   | Output                                                 |
| —     | —   | 38    | WiFi power (low = on)      | Output                                                 |
| —     | —   | 51    | UART2 TX to MCU            | Mux pin                                                |
| —     | —   | 52    | UART2 RX from MCU          | Mux pin                                                |
| —     | —   | —     | RGB LED(s)                 | Output (board-specific, via `wps_led` binary)          |
| —     | —   | —     | PIR sensor                 | Input (board-specific)                                 |
| —     | —   | —     | Speaker enable             | Output (via `controlSpeakEnable()`)                    |

GPIO control binary: `/usr/sbin/gpio_setting <group> <pin> <type> <dir> <level>`

* type: 0 = standard

* dir: 1 = input, 2 = output

* level: 0 = low, 1 = high

GPIO device: `/dev/higpio` (HiSilicon GPIO driver)

### IR Cut Filter Control

Two-pin solenoid with complementary drive via registers at `0x201C000c`:

| Mode         | GPIO8\_0 | GPIO8\_1 | Data Reg                  |
| ------------ | -------- | -------- | ------------------------- |
| Day (normal) | 0        | 1        | `0x2` then `0x0` after 1s |
| Night (IR)   | 1        | 0        | `0x1` then `0x0` after 1s |

### Audio Mute Control

| Register     | Value | Function                   |
| ------------ | ----- | -------------------------- |
| `0x200f0078` | `0x0` | Pin mux for codec control  |
| `0x201A0400` | `0x8` | Audio codec GPIO direction |
| `0x201A0020` | `0x8` | Mute OFF (audio enabled)   |
| `0x201A0020` | `0x0` | Mute ON                    |

***

## 4. UART Channels

### UART0 — Debug Console

| Property    | Value                                                 |
| ----------- | ----------------------------------------------------- |
| Device node | `/dev/ttyAMA0` / `/dev/ttyS000` (major 204, minor 64) |
| Baud rate   | 115200                                                |
| Purpose     | Linux console login + debug output                    |

### UART1 — Not Used on this Board

UART1 pins (`0x200f00BC`–`0x200f00D0`) are at reset-default mux=0 (UART1 mode). The `i2s_pin_mux()` function exists in `pinmux_hi3518e.sh` to remap these to I2S audio but is **never called** by either original firmware or OpenIPC.

Likely UART1 pin assignments: `0xC4` = UART1\_RXD, `0xC8` = UART1\_TXD (both mux=0).

### UART2 — MCU Communication

| Property         | Value                                                                       |
| ---------------- | --------------------------------------------------------------------------- |
| Physical address | PL011 at `0x200A0000`, IRQ 25                                               |
| Device node      | `/dev/ttyAMA2` (OpenIPC DT kernel), `/dev/ttyAMA1` (original non-DT kernel) |
| Baud rate        | 115200 8N1, no flow control                                                 |
| Purpose          | Binary protocol to STC15W408AS MCU (motor, feed, sensors)                   |
| TX pin           | GPIO 51 (IOCFG `0x200f00CC`), **mux=3** for UART2\_TXD                      |
| RX pin           | GPIO 52 (IOCFG `0x200f00D0`), **mux=3** for UART2\_RXD                      |
| Interrupt mode   | Interrupt-driven (PL011 IMSC=0x50: RX + receive-timeout)                    |

**Pinmux setup (OpenIPC):**

```sh
devmem 0x200f00cc 32 3    # pin 51 → mux=3 (UART2_TXD)
devmem 0x200f00d0 32 3    # pin 52 → mux=3 (UART2_RXD)
stty -F /dev/ttyAMA2 115200 raw -echo cs8 -cstopb -parenb cread clocal -crtscts
```

These pins are GPIO (mux=0) at reset; neither OpenIPC `sys_config.ko` nor original firmware pinmux scripts set them. The original firmware's bootloader or early init configures them.

**UART open glitch:** Opening `/dev/ttyAMA2` causes a line-state transition that makes the MCU latch a framing error as `0xFF`. Fix: keep the fd open persistently and send 16 null bytes on initial open to flush the error byte before any real command.

***

## 5. MCU Protocol

The STC15W408AS MCU drives the feed motor; the SoC has **no direct GPIO path to it**
— every feed goes over **UART2** (`/dev/ttyAMA2`, 115200 8N1) as `FF FF … 0A` framed
binary packets. Example, dispense weight 1:

```
ff ff 01 0a 3a 09 03 0e 0b 01 00 00 00 0a
```

The full packet and response reference — manual / auto-feed, time sync, and the
feed-result / chute / version frames — is in [`MCU_PROTOCOL.md`](MCU_PROTOCOL.md).

***

## 6. Custom ROM

### What It Adds

* **Dropbear SSH** (static ARM, port 22) with persistent host keys in `/mnt/config/dropbear/`

* **BusyBox 1.37** (static ARM) — full-featured shell

* **Clean init system** — modular `S##`-style init.d scripts

* **Camera mode switch** — `/mnt/config/camera_mode`: `ipserver` | `rtsp` | `off`

* **HA HTTP API** on port 8088 (`ha_server.sh` + `ha_handler.sh`)

* **MCU UART daemon** (`mcu_writer.sh`) — persistent ttyAMA2 writer, avoids open-glitch

* All original HiSilicon blobs preserved

### Init Sequence (Custom ROM)

```
/etc/init.d/rcS
  └─ /etc/rc.d/rc.sysinit        Mount tmpfs, devpts, mdev, MTD partitions
  └─ S10hisi                     Load HiSilicon kernel modules (26x .ko)
  │    ├─ pinmux, clkcfg, sysctl scripts
  │    ├─ MMZ, media, video pipeline modules
  │    ├─ Sensor I2C + pinmux for SC1045
  │    ├─ Audio codec modules
  │    └─ MIPI, cipher, RTC, hiuser
  └─ S20wifi                     Load 8188fu.ko, wpa_supplicant, udhcpc
  └─ S30dropbear                 Generate host keys, start SSH server
  └─ S40camera                   Camera mode dispatch + HA HTTP server
  │    ├─ Export env vars (BOARD_TYPE, SUPPORT_FEED_FUNCTION=0, etc.)
  │    ├─ stty -F /dev/ttyAMA2   Configure MCU UART
  │    ├─ ha_server.sh &         Start HA bridge (port 8088)
  │    │    └─ mcu_writer.sh &   Persistent MCU UART writer daemon
  │    └─ Mode dispatch: ipserver / rtsp / off
  └─ S50services                 Watchdog, NTP, LED init
```

**Key change:** `SUPPORT_FEED_FUNCTION=0` prevents IPServer's serial/feed thread, which triggers a reboot after 100 unanswered MCU queries. Feed control is handled directly by `ha_handler.sh` via `/dev/ttyAMA2`.

### HA HTTP API Endpoints

| Endpoint           | Method | Description                                             |
| ------------------ | ------ | ------------------------------------------------------- |
| `/status`          | GET    | Returns `online`                                        |
| `/feed/{portions}` | GET    | Dispense food (1–9 portions). 30s lockout between feeds |
| `/led/on`          | GET    | Turn status LED on (disables `wps_led` control)         |
| `/led/off`         | GET    | Turn status LED off                                     |
| `/led/auto`        | GET    | Return LED to firmware control                          |

### MCU Writer Daemon (`mcu_writer.sh`)

* Keeps `/dev/ttyAMA2` open persistently (fd 3) to avoid per-open glitch

* Reads portion count from `/tmp/mcu_cmd` FIFO

* Sends binary feed packet to MCU

* Flushes 16 null bytes on startup to clear framing error

### Flashing (8 MB, No Hardware Mod)

The custom rootfs (4464 KB) fits in the existing 4864 KB partition:

1. Power on device, let it boot normally
2. Flash via telnet: `scripts/flash_rootfs_telnet.sh flash/rootfs.img`
3. Wait \~60 seconds for flash + reboot
4. SSH in: `ssh root@192.168.1.135`

### Flashing (32 MB Chip Upgrade — OpenIPC)

The custom\_rom flow above is for the original (uClibc) firmware. To run
**OpenIPC** on a BY25Q256-upgraded board, see the full procedure in
[BY25Q256\_UPGRADE.md](BY25Q256_UPGRADE.md). Summary:

1. Build patched U-Boot (BY25Q256 SPI table + extended baud table):
   `./scripts/build-uboot.sh`
2. Build OpenIPC ultimate kernel + squashfs rootfs through buildroot:
   `cd firmware && make BOARD=hi3518ev200-nor-ultimate`
3. Pack a single flashable 32MB image:
   `FLASH_SIZE=32mb ./scripts/build-full-image.sh`
4. Desolder W25Q64, solder BY25Q256FSSIG (same SOIC-8 footprint, same 3.3V).
5. Program via CH341A: `flashrom -p ch341a_spi -w openipc/full-hi3518ev200-ultimate-32mb.bin`
6. First boot at U-Boot prompt: `setenv` mtdparts/bootargs/bootcmd per
   the doc, then `saveenv`. (Or use the loady-only in-circuit path
   documented there if you can't pull the chip.)

### SSH Key Setup

```sh
ssh root@192.168.1.135 'cat > /mnt/config/dropbear/authorized_keys' < ~/.ssh/id_rsa.pub
```

(scp doesn't work — Dropbear has no sftp-server; pipe over SSH instead)

### Cross Compilation

```sh
export PATH=$PWD/custom_rom/toolchain/arm-linux-musleabi-cross/bin:$PATH
export CC=arm-linux-musleabi-gcc
export CFLAGS="-march=armv5te -mfloat-abi=soft -Os -static"
```

For binaries calling HiSilicon MPI (camera pipeline), you need the uClibc-based HiSilicon SDK toolchain — the musl toolchain cannot link against uClibc `.so` libs.

***

## 7. Kernel Module Loading (S10hisi / load3518e)

Called with: sensor=sc1045, osmem=32, total=64

### Memory Layout

| Parameter | Value                                           |
| --------- | ----------------------------------------------- |
| Total RAM | 64 MB                                           |
| OS memory | 32 MB (custom ROM; original used 40 MB)         |
| MMZ start | `0x82000000` (custom) / `0x82800000` (original) |
| MMZ size  | 32 MB (custom) / 24 MB (original)               |
| Phys base | `0x80000000`                                    |

### Module Load Order

1. **Pinmux/clocks/sysctl** — shell scripts configure IOCFG registers
2. **MMZ + base** — `mmz.ko`, `hi_media.ko`, `hi3518e_base.ko`, `hi3518e_sys.ko`
3. **Video pipeline** — TDE, region, VGS, ISP, VIU, VPSS, RC, VENC, CHNL, H264E, JPEGE, IVE
4. **Sensor I2C** — `extdrv/sensor_i2c.ko` + pinmux for SC1045
5. **Audio** — `acodec.ko`, `hi3518e_aio.ko`, AI, AO, AENC, ADEC
6. **MIPI** — `hi_mipi.ko`

### Sensor Pinmux (SC1045)

| Register                  | Value     | Function                     |
| ------------------------- | --------- | ---------------------------- |
| `0x200f0040`              | `0x2`     | I2C0\_SCL (sensor control)   |
| `0x200f0044`              | `0x2`     | I2C0\_SDA                    |
| `0x200f007c`–`0x200f0094` | various   | VI parallel data/sync pins   |
| `0x2003002c`              | `0xc4001` | Sensor unreset, 24 MHz clock |

***

## 8. WiFi — RTL8188EUS

| Property      | Value                            |
| ------------- | -------------------------------- |
| Chip          | Realtek RTL8188EUS               |
| Interface     | USB (internal)                   |
| Driver        | `8188fu.ko`                      |
| Power control | `/proc/wifi_power` (0=off, 1=on) |
| STA config    | `/mnt/config/wpa_conf`           |
| MAC stored    | `/mnt/config/wifi_mac`           |

***

## 9. FIFO IPC System

| FIFO                    | Purpose                                             |
| ----------------------- | --------------------------------------------------- |
| `/tmp/my_fifo`          | Main IPC bus (IPServer <-> event\_detect)           |
| `/tmp/event_fifo`       | Event process FIFO                                  |
| `/tmp/watchdog_fifo`    | Hardware watchdog feed channel                      |
| `/tmp/audio_fifo`       | Audio playback commands                             |
| `/tmp/send_audio_fifo`  | Audio send path                                     |
| `/tmp/send_video_fifo2` | Video stream send path                              |
| `/tmp/mcu_cmd`          | Custom ROM: feed portion count to MCU writer daemon |

### send\_fifo Command Format

```sh
/usr/sbin/send_fifo <fifo_path> <command_type> <value>
```

Known command codes (via `/tmp/my_fifo`):

| Code | Value     | Function                   |
| ---- | --------- | -------------------------- |
| 106  | 101       | Factory reset / audio test |
| 106  | 2         | System configuration       |
| 106  | 11        | WiFi configuration         |
| 810  | 0         | Memory cleanup / reboot    |
| 1000 | type,file | Firmware upgrade           |

### FIFO Command Types (from IPServer strings)

`COMMAND_TYPE_FEED_PETS_NOTIFY`, `COMMAND_TYPE_CAMERA_WORKMODE`, `COMMAND_TYPE_ENABLE_SPEAK`, `COMMAND_TYPE_SNAPSHOT_PIC`, `COMMAND_TYPE_GET_LIGHT_NIGHT_MODE`, `COMMAND_TYPE_NETWORK_CHANGED`, `COMMAND_TYPE_UPGRADE_ONLINE_AUTO`, etc.

***

## 10. MQTT Interface (Original Firmware)

### Topics

| Topic                              | Direction    |
| ---------------------------------- | ------------ |
| `voice/manualfeedreq/<DEVICE_ID>`  | App → device |
| `voice/manualfeedresp/<DEVICE_ID>` | Device → app |
| `voice/autofeedreq/<DEVICE_ID>`    | App → device |
| `voice/autofeedresp/<DEVICE_ID>`   | Device → app |

### Command Format

```json
{
    "cmd": "manualfeedreq",
    "devid": "<DEVICE_ID>",
    "rand": "<RANDOM_STRING>",
    "feedweight": "<PORTION_SIZE>",
    "feedtime": "<HH:MM>"
}
```

Response codes: `"result":"0"` = success, `"result":"6"` = error.

***

## 11. ADC / Light Sensor

| Property  | Value                                              |
| --------- | -------------------------------------------------- |
| Device    | `/dev/hi_adc`                                      |
| Used by   | `event_detect` → `getAdcValue()`                   |
| Purpose   | Ambient light level for automatic IR cut switching |
| Threshold | `light_night_var=13000`                            |

***

## 12. Hardware Watchdog

| Property | Value                                       |
| -------- | ------------------------------------------- |
| Device   | `/dev/watchdog` (Hi3518E built-in WDT)      |
| Binary   | `/usr/sbin/feed_watchdog`                   |
| Wrapper  | `/usr/sbin/feed_watchdog.sh` (restart loop) |
| Priority | First service started in init               |

If `feed_watchdog` stops and isn't restarted, the SoC performs a hardware reset.

***

## 13. NVRAM Keys

Accessed via `nvram_get uboot <KEY>` / `nvram_set uboot <KEY> <VALUE>`.

| Key            | Description                                |
| -------------- | ------------------------------------------ |
| `BOARD_TYPE`   | Board/product variant string               |
| `UID`          | Device unique ID (P2P and SSID generation) |
| `ethaddr`      | MAC address                                |
| `ptz_width`    | PTZ range                                  |
| `product_test` | Factory test flag                          |
| `AP_NAME`      | WiFi AP SSID override                      |

***

## 14. Environment Variables (from `/etc/profile` / S40camera)

| Variable                | Value                            | Purpose                    |
| ----------------------- | -------------------------------- | -------------------------- |
| `DEVICE_MODEL`          | `L8-SI`                          | Device model identifier    |
| `VENDOR`                | `IPCAME`                         | Vendor string              |
| `DEVICE_TYPE`           | `BH264`                          | H.264 camera type          |
| `PRODUCT_MODE`          | `A06_3.81.4`                     | Product + firmware version |
| `BOARD_TYPE`            | `DOGNESS_PETS_V200_BREAD_DEVICE` | Board variant              |
| `SUPPORT_FEED_FUNCTION` | `0` (custom) / `1` (original)    | Pet feeder MCU thread      |
| `SUPPORT_PTZ`           | `0`                              | No pan-tilt-zoom           |
| `SUPPORT_FIVE_PARTION`  | `1`                              | 5-partition flash layout   |
| `NOT_SUPPORT_SDCARD`    | `1`                              | SD card not supported      |
| `SUPPORT_ALEXA`         | `1`                              | Amazon Alexa integration   |
| `G_WIRE_EXIST`          | `no`                             | No wired ethernet          |
| `G_P2P_TYPE`            | `tutk`                           | P2P stack: TUTK            |

***

## 15. U-Boot Serial Flashing Quick Reference

Load addresses: `0x80700000` for U-Boot itself (mini-boot link addr,
allows `go 0x80700000` to chain-boot a fresh u-boot from RAM),
`0x82000000` for kernel/rootfs payloads.

Transport: YMODEM (`loady <addr>`) over picocom. Patched U-Boot supports
up to 921600 baud — bump after first flash for \~8× faster transfers.
See [BY25Q256\_UPGRADE.md](BY25Q256_UPGRADE.md) for the
full step-by-step, including the in-circuit "boot new u-boot from RAM"
recovery dance for fresh chips.

### 8MB layout (W25Q64/W25Q128 stock)

```
# U-Boot (offset 0, 320KB)
sf probe 0; sf erase 0 0x50000; sf write 0x82000000 0 ${filesize}; reset

# Kernel (offset 0x50000, 2MB slot)
sf probe 0; sf erase 0x50000 0x200000; sf write 0x82000000 0x50000 ${filesize}

# Rootfs squashfs (offset 0x250000, 5.75MB slot)
sf probe 0; sf erase 0x250000 0x5B0000; sf write 0x82000000 0x250000 ${filesize}

# Entire 8MB image
sf probe 0; sf erase 0 0x800000; sf write 0x82000000 0 0x800000; reset
```

### 32MB layout (BY25Q256, patched U-Boot)

```
# U-Boot (offset 0, 320KB)
sf probe 0; sf erase 0 0x50000; sf write 0x82000000 0 ${filesize}; reset

# Kernel (offset 0x60000, 3MB slot)
sf probe 0; sf erase 0x60000 0x300000; sf write 0x82000000 0x60000 ${filesize}

# Rootfs squashfs (offset 0x360000, ~28.6MB available)
sf probe 0; sf erase 0x360000 0x700000; sf write 0x82000000 0x360000 ${filesize}

# Entire 32MB image
sf probe 0; sf erase 0 0x2000000; sf write 0x82000000 0 0x2000000; reset
```

### Bumping baud for faster loady (patched U-Boot only)

```
setenv baudrate 921600
saveenv
# quit picocom, reconnect at 921600
```

The patched U-Boot re-applies env baud after `env_relocate()`, so subsequent
boots come up at the saved rate automatically — no manual `setenv` needed.
Linux flips back to 115200 via `console=ttyAMA0,115200` on the kernel cmdline,
so switch picocom back at handoff.

***

## 16. Peripheral Summary Diagram

```
                        Hi3518EV200 SoC (ARM926EJ-S, 64MB RAM)
                    ┌──────────────────────────────────────────┐
                    │                                          │
  SC1045 sensor ◄───┤ I2C0 (GPIO3_3/3_4)                      │
  (720p, 24MHz)     │ VI parallel bus (DATA9-13, VS, HS)       │
                    │                                          │
  STC15W408AS ◄─────┤ UART2 /dev/ttyAMA2 — binary protocol    │
  MCU (8051)        │   Pin 51 (0xCC mux=3) TX                 │
  (motor, feed)     │   Pin 52 (0xD0 mux=3) RX                 │
                    │   115200 8N1, interrupt-driven            │
                    │                                          │
  Debug console ◄───┤ UART0 /dev/ttyAMA0 (115200 baud)         │
                    │                                          │
  RTL8188EUS ◄──────┤ USB (internal bus)                       │
  WiFi              │   /proc/wifi_power for power ctrl        │
                    │                                          │
  Status LED ◄──────┤ GPIO 0:2 (output)                        │
  IR LED ◄──────────┤ GPIO 0:0 (output)                        │
  IR Cut filter ◄───┤ GPIO 4:5 + GPIO 8:0/8:1 (solenoid)      │
  RGB LED(s) ◄──────┤ GPIO (board-specific, via wps_led)       │
  PIR sensor ────►──┤ GPIO (input, board-specific)             │
  Button(s) ────►───┤ /dev/event0 (input subsystem)            │
  ADC (light) ──►───┤ /dev/hi_adc                              │
  Watchdog ─────────┤ /dev/watchdog (built-in WDT)             │
  RTC ──────────────┤ /dev/hi_rtc                              │
                    │                                          │
  SPI NOR flash ◄───┤ MTD (5 partitions, 8MB or 32MB)          │
                    │                                          │
  Internal codec ◄──┤ AIO (MCLK: 0x201200E0=0xd)              │
                    └──────────────────────────────────────────┘
```

***

## 17. Other Board Variants (Compiled Into Same Binaries)

* `HANWEI_PETS_V200_BOARD`

* `LIUBINGHUA_PETS_V200_BOARD`

* `MEIKE_PETS_V200_BOARD`

* `MEIKE_SMART_PETS_V200_BOARD`

* `PETFUN_PLAYDOG_V200_BOARD`

* `PETWANT_PETS_V200_BOARD`

* `RUIYI_PET_V200_BOARD`

* `HISI3518E_CORE_BOARD` (generic dev board)

***

## 18. Key File Paths

| Path                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| `/dev/ttyAMA2`                | MCU UART (OpenIPC)                       |
| `/dev/ttyAMA0`                | Console UART                             |
| `/dev/higpio`                 | GPIO driver node                         |
| `/dev/hi_adc`                 | ADC (light sensor)                       |
| `/dev/watchdog`               | Hardware watchdog                        |
| `/tmp/my_fifo`                | Main IPC bus                             |
| `/tmp/mcu_cmd`                | Feed command FIFO (custom ROM)           |
| `/tmp/micro_verson.txt`       | MCU firmware version (original firmware) |
| `/tmp/serial_detect`          | MCU contact flag                         |
| `/mnt/config/camera_mode`     | Camera mode: ipserver/rtsp/off           |
| `/mnt/config/wpa_conf`        | WiFi credentials                         |
| `/mnt/config/dropbear/`       | SSH host keys + authorized\_keys         |
| `/mnt/config/pet_configs.cgi` | Meal schedule (original firmware)        |
| `/usr/sbin/ha_server.sh`      | HA HTTP accept loop                      |
| `/usr/sbin/ha_handler.sh`     | HA HTTP request handler                  |
| `/usr/sbin/mcu_writer.sh`     | Persistent MCU UART writer daemon        |
| `/usr/sbin/gpio_setting`      | GPIO control binary                      |
| `/usr/sbin/feed_watchdog`     | Hardware watchdog feed binary            |
| `/lib/libcommon.so`           | Motor/serial/GPIO functions (original)   |
| `/lib/libjiake_protocol.so`   | MCU serial protocol (original)           |
| `/lib/libjiake_sdk.so`        | SDK (WatchDog, FileOperation)            |

***

## 19. TODO

* [ ] Handle low food hopper after feeding (read MCU food-present sensor response)

* [ ] Build Home Assistant dashboard card

* [ ] Auto night mode / single button in HA

* [ ] Read MCU response in `mcu_writer.sh` and surface via `/tmp/mcu_resp`
