# BY25Q256 (32MB SPI NOR) Upgrade — hi3518ev200

> _Curated from the project's working notes. The OpenIPC build helpers referenced below (`build-uboot.sh`, `build-full-image.sh`, `flash_rootfs_ssh.sh`) live in [`scripts/`](../scripts/) and run from the repo root; `firmware/` and `u-boot-hi3516cv200/` are git submodules pinned to their upstream base commit, with our changes applied from [`patches/`](../patches/)._

This document captures the work needed to swap the stock 8MB W25Q64 SPI
NOR for a 32MB **Boya BY25Q256FSSIG**. Neither U-Boot nor the kernel
shipped with OpenIPC for hi3518ev200 supports this part out of the box —
both fail at the JEDEC ID lookup before the chip is ever read.

This isn't BY25Q256-specific in spirit. The same fixes apply to any
W25Q256-class part with an unfamiliar manufacturer code or a JEDEC
device-type byte the stock tables don't recognize. Adapt the JEDEC IDs
in the patches if you're using a different chip.

## Why it didn't "just work"

Three layered problems, each invisible until the previous one is fixed:

1. **U-Boot doesn't recognize the JEDEC ID `0x68 0x49 0x19`.** The
   hi3518ev200's mask ROM reads u-boot from offset 0 in 3-byte address
   mode (no chip ID lookup), so u-boot itself loads. But once running,
   `sf probe` fails because the SPI NOR table only has Winbond/Macronix/
   Spansion entries. Result: `Failed to initialize SPI flash at 0:0`.

2. **The kernel's SPI NOR ID table is independently broken.** Even after
   u-boot is fixed, the kernel's `hisi-sfc` driver calls `spi_nor_scan()`
   from the common spi-nor framework, which has its own JEDEC table —
   also missing Boya. Result: `unrecognized JEDEC id bytes: 68, 49, 19`,
   followed by no MTD partitions appearing, followed by VFS panic.

3. **The stock 32MB "ultimate" UBI rootfs image was built for NAND.**
   Its erase-counter header has `data_offset=4096` (assumes
   min_io_size=2048, typical for NAND). On NOR, min_io_size=1, so UBI
   computes `data_offset=2112`. Result: `bad data offset 4096, expected
   2112` and another VFS panic. Solution: use the squashfs rootfs
   instead of the UBI rootfs — also in the OpenIPC build, smaller, and
   correct for NOR.

The patches in [patches/u-boot/](patches/u-boot/) and
[patches/kernel/](patches/kernel/) (kernel patch lives at
[firmware/general/package/all-patches/linux/0022-add-by25q256fs-spi-nor-id.patch](firmware/general/package/all-patches/linux/0022-add-by25q256fs-spi-nor-id.patch)
so buildroot picks it up automatically) address all three.

## Quick Reference

| Property | Value |
|---|---|
| Chip | Boya BY25Q256FSSIG (Digi-Key) |
| Footprint | SOIC-8 (drop-in for W25Q64/W25Q128) |
| Capacity | 256 Mbit / 32 MB |
| JEDEC ID | `0x68 0x49 0x19` |
| Voltage | 2.7–3.6V (3.3V works) |
| Addressing | 4-byte mode required for accesses above 16MB |
| Standard 4-byte commands | EN4B `0xB7`, EX4B `0xE9`, native opcodes 0x13/0x12/0xDC/0x21 |

## What got patched

### U-Boot (5 patches in [patches/u-boot/](patches/u-boot/))

1. **`0001-add-by25q256-jedec-id.patch`** —
   [drivers/mtd/spi/hifmc100/hifmc_spi_nor_ids.c](u-boot-hi3516cv200/drivers/mtd/spi/hifmc100/hifmc_spi_nor_ids.c).
   Adds a Boya entry with `addrcycle=4` next to the existing W25Q256FV
   entry. Reuses `spi_driver_w25q256fv` since BY25Q256 follows the same
   EN4B/reset protocol.

2. **`0002-extend-baudrate-table.patch`** —
   [include/configs/hi3518ev200.h](u-boot-hi3516cv200/include/configs/hi3518ev200.h).
   Adds 230400/460800/921600 to `CONFIG_SYS_BAUDRATE_TABLE`. Without
   this, `setenv baudrate 921600` reports "Baudrate not supported".

3. **`0003-implement-pl011-setbrg.patch`** —
   [drivers/serial/serial_pl01x.c](u-boot-hi3516cv200/drivers/serial/serial_pl01x.c).
   `serial_setbrg()` was an empty stub. With this fix it actually
   reprograms IBRD/FBRD on the PL011, so runtime baud changes work.

4. **`0004-apply-env-baudrate-after-relocate.patch`** —
   [arch/arm/lib/board.c](u-boot-hi3516cv200/arch/arm/lib/board.c).
   `serial_init()` programs the UART using the compile-time
   `CONFIG_BAUDRATE` (115200), ignoring whatever's in env. After
   `env_relocate()` we now re-apply the env baud, so the UART comes up
   at the saved rate automatically. Without this you'd have to type
   `setenv baudrate 921600` after every reset.

5. **`0005-makefile-uclibc-toolchain-prefix.patch`** —
   [common/Makefile](u-boot-hi3516cv200/common/Makefile). The shipped
   Makefile only knows `arm-hisiv300-linux-` (glibc); most Hi3518
   toolchains in the wild are `arm-hisiv300-linux-uclibcgnueabi-`. Adds
   an `ifeq` branch so the bootss2.a archive selection works with the
   uclibc toolchain too.

### Kernel (1 patch, applied automatically by buildroot)

[firmware/general/package/all-patches/linux/0022-add-by25q256fs-spi-nor-id.patch](firmware/general/package/all-patches/linux/0022-add-by25q256fs-spi-nor-id.patch).
Adds an entry for `by25q256fs` (JEDEC `0x684919`, 32MB) to the common
`spi_nor_ids[]` table in `drivers/mtd/spi-nor/spi-nor.c` with
`SPI_NOR_4B_OPCODES` set, so the kernel uses native 4-byte opcodes
(0x13/0x12/0x21/0xDC) and skips the manufacturer-specific 4-byte
mode-switch in `set_4byte()`.

## Reproducible build

### Prereqs

- Hisilicon SDK toolchain `arm-hisiv300-linux-uclibcgnueabi-` at
  `~/Downloads/hisi-linux/x86-arm/arm-hisiv300-linux/`. Override with
  `TOOLCHAIN_DIR=...` if it's elsewhere.
- `lzma` command on `PATH`. On Fedora 42 install `xz-lzma-compat`, or
  `build-uboot.sh` will drop a `xz --format=lzma` wrapper at
  `~/.local/bin/lzma`.
- Buildroot already configured (one-shot via OpenIPC's `make BOARD=...`).

### Build U-Boot

```sh
./scripts/build-uboot.sh
# → u-boot-hi3518ev200-by25q256.bin (repo root) (~135KB)
```

If you're starting from a clean clone of the U-Boot tree, apply the
patches first:

```sh
cd u-boot-hi3516cv200
for p in ../patches/u-boot/*.patch; do git apply "$p"; done
cd ..
./scripts/build-uboot.sh
```

### Build kernel + rootfs

The kernel patch lives in `firmware/general/package/all-patches/linux/`
so buildroot applies it automatically on next build:

```sh
cd firmware
make BOARD=hi3518ev200-nor-ultimate
# → output/images/uImage and rootfs.squashfs.hi3518ev200
```

If `linux-custom` was already built, force a partial rebuild after the
patch lands:

```sh
make linux-custom-rebuild
```

> **Heads up — initramfs bloat.** The hi3518ev200 buildroot config has
> `CONFIG_INITRAMFS_SOURCE=${BR_BINARIES_DIR}/rootfs.cpio`. That
> embeds the entire 15MB rootfs into the kernel, ballooning it from
> ~1.8MB to ~8.4MB. Since we have a real squashfs rootfs at flash
> offset `0x360000`, an embedded initramfs is unnecessary. If you build
> the kernel manually (not through buildroot), edit
> `output/build/linux-custom/.config` and set
> `CONFIG_INITRAMFS_SOURCE=""`.

### Build flashable image

```sh
FLASH_SIZE=32mb ./scripts/build-full-image.sh
# → openipc/full-hi3518ev200-ultimate-32mb.bin (32MB)
```

`scripts/build-full-image.sh` defaults are now:
- `UBOOT` → the patched binary above
- `KERNEL` → `openipc.hi3518ev200-nor-ultimate/uImage.hi3518ev200`
- `ROOTFS` → `openipc.hi3518ev200-nor-ultimate/rootfs.squashfs.hi3518ev200`

The script warns if the ROOTFS magic isn't `hsqs` — UBI rootfs files
will not attach on NOR with stock geometry.

## Flash layout (32MB)

| Offset | Size | Region | mtd | Notes |
|---|---|---|---|---|
| 0x000000 | 320KB | u-boot | mtd0 | mini-boot (~135KB) + 0xFF padding to 0x50000 |
| 0x040000 | 64KB | (env)  | — | `CONFIG_ENV_OFFSET=0x40000` lives in u-boot's tail padding; saveenv writes here, NOT at 0x50000 |
| 0x050000 | 64KB | env-pad | mtd1 | informational mtdparts entry; actual env is at 0x40000 above |
| 0x060000 | 3MB  | kernel | mtd2 | uImage (~1.8MB) |
| 0x360000 | ~28.6MB | rootfs | mtd3 | squashfs (~6.6MB) + 0xFF (writable filesystem can mount remaining as JFFS2 if desired) |

U-Boot env after first boot:

```
mtdparts hi_sfc:320k(boot),64k(env),3072k(kernel),-(rootfs)
bootargs mem=32M console=ttyAMA0,115200 panic=20 root=/dev/mtdblock3 rootfstype=squashfs init=/init mtdparts=${mtdparts} ${extras}
bootcmd  setenv setargs setenv bootargs ${bootargs}; run setargs; sf probe 0; sf read ${baseaddr} 0x60000 0x300000; bootm ${baseaddr}; reset
osmem    32M
baudrate 921600
```

> **Env offset mismatch — known wart.** `build-full-image.sh` reserves
> 0x50000 for env padding, but the U-Boot we ship has
> `CONFIG_ENV_OFFSET=0x40000` (overridden by hi-common.h). `saveenv`
> writes to `0x40000` which falls inside the boot region's tail
> padding. Harmless in practice — u-boot.bin is only ~135KB so 0x40000
> is in the 0xFF padding area — but worth knowing if you ever need to
> recover env from a chip dump. Fix by either changing `UBOOT_MAX` in
> the build script to `0x40000`, or editing `CONFIG_ENV_OFFSET` in
> [u-boot-hi3516cv200/include/configs/hi-common.h:34](u-boot-hi3516cv200/include/configs/hi-common.h)
> to `0x50000`.

## Flashing procedures

### Path A: external CH341A (cleanest)

This is how the chip was actually brought up here: a replacement BY25Q256 ships
**blank** (no U-Boot), so it can't be programmed in-circuit — there's nothing for
the mask ROM to boot. Program it externally, then mount it.

1. Build `full-hi3518ev200-ultimate-32mb.bin` per above.
2. Clip onto the BY25Q256 with a SOIC-8 clip, **off the board**. In-circuit
   clipping was unreliable on this hardware; programming the loose chip worked.
3. `flashrom -p ch341a_spi -w full-hi3518ev200-ultimate-32mb.bin` — but note
   **flashrom has no BY25Q256 chip entry** (its Boya support stops at the 128 Mbit
   B.25Q128AS, v1.7.0 included), so it reports an unknown chip. Force a compatible
   256 Mbit definition with `-c W25Q256FV` (same EN4B / 4-byte-opcode protocol), or
   use a CH341A tool with its own chip database.
4. Solder the programmed chip in and power up. First boot uses compiled-in env
   defaults; set them per the table above and `saveenv`.

### Path B: in-circuit via U-Boot loady (no chip removal)

Use this to *update* U-Boot or recover a board that **already has a working
U-Boot** — not to bring up a blank chip (a blank BY25Q256 has nothing for the mask
ROM to load; program it externally first, Path A). It works as long as some U-Boot
is in the boot region, even the stock one that can't probe the new chip — its
mask-ROM-loaded read still runs. All transfers via picocom YMODEM at 115200 first,
then bumped to 921600 after the first U-Boot replacement.

```sh
picocom -b 115200 --send-cmd "sx -vv" /dev/ttyACM1
```

In U-Boot:

```
loady 0x80700000
# picocom: Ctrl+A Ctrl+S, send u-boot-hi3518ev200-by25q256.bin
go 0x80700000
# Now running new U-Boot from RAM. Check 'sf probe 0' shows BY25Q256 32MB.
sf probe 0
sf erase 0 0x50000
sf write 0x80700000 0 ${filesize}
reset
```

After reset the new U-Boot is running from flash. Bump baud:

```
setenv baudrate 921600
```

> Quit picocom, reconnect at 921600, press Enter:
> ```sh
> picocom -b 921600 --send-cmd "sx -vv" /dev/ttyACM1
> ```

```
saveenv
```

Now loady the kernel and rootfs at the higher rate (~30s + ~75s):

```
loady 0x82000000
# send openipc/openipc.hi3518ev200-nor-ultimate/uImage.hi3518ev200
sf erase 0x60000 0x300000
sf write 0x82000000 0x60000 ${filesize}

loady 0x82000000
# send openipc/openipc.hi3518ev200-nor-ultimate/rootfs.squashfs.hi3518ev200
sf erase 0x360000 0x700000
sf write 0x82000000 0x360000 ${filesize}
```

Set env and boot:

```
setenv mtdparts 'hi_sfc:320k(boot),64k(env),3072k(kernel),-(rootfs)'
setenv bootargs 'mem=${osmem} console=ttyAMA0,115200 panic=20 root=/dev/mtdblock3 rootfstype=squashfs init=/init mtdparts=${mtdparts} ${extras}'
setenv bootcmd 'setenv setargs setenv bootargs ${bootargs}; run setargs; sf probe 0; sf read ${baseaddr} 0x60000 0x300000; bootm ${baseaddr}; reset'
setenv osmem '32M'
saveenv
run bootcmd
```

The kernel `console=ttyAMA0,115200` setting will switch the UART back
to 115200 once the kernel takes over. Switch picocom back to 115200 to
read the boot log.

## Diagnostic / one-off tricks worth remembering

### Read JEDEC ID directly via FMC registers (when `sf probe` fails)

The hifmc100 read-ID sequence — useful when the U-Boot SPI table doesn't
recognize the chip but you need to know what it is:

```
mw.l 0x10010024 0x9F     ; FMC_CMD = RDID
mw.l 0x10010030 0x0      ; CS = 0
mw.l 0x10010038 0x8      ; read 8 bytes back
mw.l 0x1001003c 0x85     ; CMD1_EN | READ_DATA_EN | OP_START
md.b 0x58000000 8        ; first 3 bytes are JEDEC manufacturer/type/capacity
```

Reference: [u-boot-hi3516cv200/drivers/mtd/spi/hifmc100/hifmc100.c:312](u-boot-hi3516cv200/drivers/mtd/spi/hifmc100/hifmc100.c).

### Confirm UART baud from silicon

Bypass any env confusion and read the divisor directly:

```
md.l 0x20080024 2     ; IBRD then FBRD on UART0 (PL011)
```

Decode against `24,000,000 / (16 × (IBRD + FBRD/64))`. Sanity values:

| IBRD | FBRD | Baud   |
|------|------|--------|
| 13   | 1    | 115200 |
| 6    | 33   | 230400 |
| 3    | 16   | 460800 |
| 1    | 40   | 921600 |
