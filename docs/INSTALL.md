# Installing on your own feeder

> ⚠️ **At your own risk — YMMV.** You're reflashing the firmware of an appliance
> you own. Nobody here is responsible if you brick it, jam the motor, or void a
> warranty. Hardware, board revisions, and flash chips vary — go slow and make
> sure you understand each step before you run it.
>
> **Back up the flash _first_.** Before writing anything, clip the SOIC-8 onto the
> chip and dump the current contents so you can always restore the exact factory
> image:
>
> ```sh
> flashrom -p ch341a_spi -r factory-backup.bin
> flashrom -p ch341a_spi -r verify.bin && cmp factory-backup.bin verify.bin   # confirm a clean, repeatable read
> ```
>
> Keep `factory-backup.bin` somewhere safe — re-flashing it is your guaranteed way
> back to stock. In-circuit clipping can be unreliable (it was flaky on this
> hardware), so the most dependable reads/writes are with the chip **off the
> board**; failing that, dump the MTD partitions from the running device
> (`cat /dev/mtdblockN`) over telnet/SSH.

> **You can't really brick this.** With a SOIC-8 clip and a CH341A you can always
> rewrite the flash externally, so a failed flash is a 5-minute re-do, not a dead
> device. See [Recovery](#recovery). Wire up the UART console and keep a known-good
> full image around before your first flash and you're covered.

This is a HiSilicon SPI-NOR camera, so "installing" means writing a new image to
the flash. There are three ways in (external programmer, network flash from the
stock firmware, SSH once OpenIPC is running) and two independent recovery paths.

## 0. Decide which build

| Build | Flash chip | Hardware mod | Notes |
|---|---|---|---|
| **32 MB "ultimate"** | Boya BY25Q256 | desolder W25Q64 → solder BY25Q256 | The proven, full-feature target. Needs the chip swap — see [`BY25Q256_UPGRADE.md`](BY25Q256_UPGRADE.md). |
| **8 MB "lite"** | stock W25Q64 | none | No soldering, flashable over the network, but tight on space and the camera bring-up on lite was never finished here. Treat as experimental. |

If you want it to just work, do the 32 MB swap. If you want to avoid soldering and
don't mind the rough edges, the 8 MB lite path lets you flash over telnet.

## 1. Build the artifacts

```sh
./scripts/build.py all        # u-boot + main + recovery, assembles the 32 MB image
# or the granular steps the upgrade doc walks through:
./scripts/build-uboot.sh
FLASH_SIZE=32mb ./scripts/build-full-image.sh
```

Artifacts land in the current directory (`u-boot-hi3518ev200-by25q256.bin`,
`uImage.hi3518ev200`, `rootfs.squashfs.hi3518ev200`, `full-…-32mb.bin`).

> **Set your own credentials first.** The published overlay ships with the root
> password, WiFi PSK, and SSH key removed (see the main README → *Before you
> build*). Set them in the firmware overlay or you'll boot an image with no login.

## 2. Flash it

### Path A — external CH341A + SOIC-8 clip

```sh
# power the board OFF, clip the SOIC-8 onto the flash chip
flashrom -p ch341a_spi -w full-hi3518ev200-ultimate-32mb.bin
```

Power up. On a 32 MB board's first boot, set the U-Boot env (mtdparts / bootargs /
bootcmd) per [`BY25Q256_UPGRADE.md`](BY25Q256_UPGRADE.md), then `saveenv`.

> **Program the BY25Q256 _off the board_.** A replacement chip ships blank — no
> U-Boot — so nothing in-circuit can bootstrap it (there's no U-Boot for the mask
> ROM to load, so the `loady` path can't help a blank chip). Program the chip
> before soldering it in (or with it lifted), then mount it. On this hardware the
> in-circuit clip was unreliable anyway — off-device programming is what worked.

> **flashrom and the Boya BY25Q256.** flashrom knows the stock W25Q64 / W25Q128
> out of the box (so the factory backup above just works), but it has **no chip
> entry for the 32 MB Boya BY25Q256** — its Boya support tops out at the 128 Mbit
> B.25Q128AS, including the v1.7.0 build used in this project — so a plain
> `flashrom -w` reports an unknown chip. Two ways around it: force a compatible
> 256-Mbit definition with `-c` (the BY25Q256 uses the same EN4B / 4-byte-opcode
> protocol as the Winbond part, so `-c W25Q256FV` is the natural pick), or skip
> flashrom for the 32 MB chip and program it in-circuit with U-Boot `loady` — the
> path [`BY25Q256_UPGRADE.md`](BY25Q256_UPGRADE.md) walks through, and what this
> project used at bringup.

### Path B — network flash from the stock firmware (no soldering, 8 MB lite only)

The stock Dogness firmware runs **telnet on port 23** with `root` / `059AnkJ`
(a known HiSilicon-OEM default). That's enough to push a *lite* image onto the
running device without opening it:

1. Serve the image over HTTP from your machine (`python3 -m http.server`).
2. Telnet in, `wget` the image to `/tmp`, and verify its md5.
3. `flashcp` it onto the kernel + rootfs MTD partitions.
4. `reboot`.

`scripts/flash_rootfs_telnet.sh` automates exactly this dance (HTTP transfer →
md5 check → `flashcp`). It was written for the original 8 MB custom-ROM layout, so
adjust the target MTD partitions for the OpenIPC image. **The 32 MB ultimate build
will not fit the stock 8 MB chip** — for that you need Path A.

### Path C — updating once OpenIPC is running (SSH)

`scripts/flash.py` flashes partitions over SSH and md5-verifies every transfer:

```sh
./scripts/flash.py main      --device <ip>   # kernel + rootfs, detached + auto-reboot
./scripts/flash.py rootfs    --device <ip>   # rootfs only
./scripts/flash.py kernel    --device <ip>   # kernel only
./scripts/flash.py recovery  --device <ip>   # writes the recovery image to mtd4 (no reboot)
./scripts/flash.py uboot     --device <ip>   # mtd0 — the risky one (asks to confirm)
```

`main`/`rootfs`/`kernel` run **detached and auto-reboot** — the running rootfs
disappears mid-flash, so SSH drops on purpose; wait ~60 s and reconnect. `uboot`
is the only write that can leave the device needing UART recovery, so it prompts
before erasing `mtd0`.

## Recovery

You have two independent nets before the device is ever truly stuck, in order of
effort:

1. **Recovery partition (on-device).** The build ships a fallback initramfs
   (`flash.py recovery` → `mtd4`) that boots WiFi + sshd on its own. If a `main`
   flash goes bad, boot recovery and re-flash `main` over SSH — no cables.
2. **U-Boot YMODEM (`loady`) over UART.** As long as the chip already holds a
   working U-Boot, the hi3518 mask ROM loads it from flash offset 0 in 3-byte mode
   *regardless of JEDEC ID* — so U-Boot comes up even on a chip it can't fully
   probe, enough to `loady` a fresh kernel / rootfs / U-Boot over the serial
   console. This recovers anything short of a corrupt **or absent** U-Boot — a
   blank chip has nothing to load, so use net 3 for that. Full sequence in
   [`BY25Q256_UPGRADE.md`](BY25Q256_UPGRADE.md).
3. **SOIC-8 clip + CH341A (the ultimate net).** If U-Boot is gone or the chip is
   blank, rewrite the whole image externally — the same write as a clean install
   (Path A). In-circuit clipping was unreliable on this board, so program the chip
   **off the board** if it won't take in place. No software state survives this,
   which is why you can't permanently brick the device as long as you can reach the
   chip with a programmer.

**Soft-brick reality:** the only writes that can stop the device booting are the
U-Boot region (`flash.py uboot`, or a botched Path-A write) and a corrupt full
image. A bad kernel or rootfs is recovered from U-Boot in minutes (net 2); a bad
U-Boot is recovered with the clip (net 3). Keep a known-good `full-…bin` and the
clip on hand and the worst case is a re-flash.
