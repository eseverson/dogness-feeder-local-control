#!/bin/sh
# Assemble a full flashrom image for hi3518ev200-nor.
#
# Two layouts supported. Both place env so it overlaps the boot region
# tail (since CONFIG_ENV_OFFSET=0x40000 in the U-Boot we ship), so the
# 64KB env slot is purely informational — saveenv lands inside the boot
# region but doesn't collide with the actual u-boot.bin (~135KB).
#
# 8MB lite layout (default):
#   0x000000  u-boot                (320KB)
#   0x050000  uImage                (2MB)
#   0x250000  rootfs (squashfs)     (5.75MB)
#   Total: 0x800000 (8MB)
#
# 32MB ultimate layout (FLASH_SIZE=32mb):
#   0x000000  u-boot                (320KB, includes env at 0x40000-0x50000)
#   0x050000  env                   (64KB)
#   0x060000  uImage                (3MB)
#   0x360000  rootfs (squashfs)     (8MB)
#   0xB60000  rootfs_data (JFFS2)   (~20.6MB, formatted on first boot)
#   Total: 0x2000000 (32MB)
#
# mtdparts: hi_sfc:320k(boot),64k(env),3072k(kernel),8192k(rootfs),-(rootfs_data)
# Set in U-Boot once with: setenv mtdparts <above>; saveenv
#
# Inputs (defaults assume the directory layout this repo uses):
#   UBOOT   — patched U-Boot binary with BY25Q256 support, see build-uboot.sh
#   KERNEL  — kernel uImage
#   ROOTFS  — squashfs rootfs (NOT UBI; UBI ultimate images won't attach on NOR)
#
# Usage:
#   ./build-full-image.sh                      # 8MB lite
#   FLASH_SIZE=32mb ./build-full-image.sh      # 32MB ultimate
#   UBOOT=... KERNEL=... ROOTFS=... ./build-full-image.sh
#
# After building, flash via CH341A externally, or via U-Boot loady. See
# BY25Q256_UPGRADE.md for the BY25Q256 chip swap procedure.

set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
IMAGES=$ROOT
FLASH_SIZE=${FLASH_SIZE:-8mb}

case "$FLASH_SIZE" in
    8mb)
        TOTAL_SIZE=$((0x800000))
        KERNEL_OFFSET=$((0x050000))
        ROOTFS_OFFSET=$((0x250000))
        UBOOT_MAX=$((0x050000))
        KERNEL_MAX=$((0x200000))
        ROOTFS_MAX=$((0x500000))
        : "${KERNEL:=$IMAGES/openipc.hi3518ev200-nor-lite/uImage.hi3518ev200}"
        : "${ROOTFS:=$IMAGES/openipc.hi3518ev200-nor-lite/rootfs.squashfs.hi3518ev200}"
        OUT=$PWD/full-hi3518ev200-lite-8mb.bin
        ;;
    32mb)
        TOTAL_SIZE=$((0x2000000))
        KERNEL_OFFSET=$((0x060000))
        ROOTFS_OFFSET=$((0x360000))
        UBOOT_MAX=$((0x050000))
        KERNEL_MAX=$((0x300000))
        ROOTFS_MAX=$((0x800000))
        : "${KERNEL:=$IMAGES/openipc.hi3518ev200-nor-ultimate/uImage.hi3518ev200}"
        : "${ROOTFS:=$IMAGES/openipc.hi3518ev200-nor-ultimate/rootfs.squashfs.hi3518ev200}"
        OUT=$PWD/full-hi3518ev200-ultimate-32mb.bin
        ;;
    *)
        echo "error: unsupported FLASH_SIZE '$FLASH_SIZE' (supported: 8mb, 32mb)"
        exit 1
        ;;
esac

# Default to the BY25Q256-aware u-boot. For the original W25Q64/W25Q128
# stock u-boot, override with UBOOT=...
: "${UBOOT:=$IMAGES/u-boot-hi3518ev200-by25q256.bin}"

if [ ! -f "$UBOOT" ]; then
    echo "error: u-boot binary not found at $UBOOT"
    echo "  build it: ./build-uboot.sh"
    echo "  or override: UBOOT=/path/to/u-boot.bin $0"
    exit 1
fi
[ -f "$KERNEL" ] || { echo "error: $KERNEL missing"; exit 1; }
[ -f "$ROOTFS" ] || { echo "error: $ROOTFS missing"; exit 1; }

# Sanity-check rootfs format: anything other than squashfs ('hsqs') will
# panic the kernel during root mount. UBI images need NOR-friendly geometry
# (data_offset=2112, not the default 4096) and have to be rebuilt with
# correct ubinize parameters — easier to just use squashfs.
ROOTFS_MAGIC=$(head -c 4 "$ROOTFS" | od -An -tx1 | tr -d ' \n')
if [ "$ROOTFS_MAGIC" != "68737173" ]; then
    echo "warning: rootfs $ROOTFS does not have squashfs magic ('hsqs')"
    echo "         got: $ROOTFS_MAGIC"
    echo "         (UBI rootfs will fail to attach on NOR — use squashfs)"
fi

UBOOT_SIZE=$(stat -c %s "$UBOOT")
KERNEL_SIZE=$(stat -c %s "$KERNEL")
ROOTFS_SIZE=$(stat -c %s "$ROOTFS")

[ "$UBOOT_SIZE"  -le "$UBOOT_MAX"  ] || { echo "u-boot too big: $UBOOT_SIZE > $UBOOT_MAX";   exit 1; }
[ "$KERNEL_SIZE" -le "$KERNEL_MAX" ] || { echo "kernel too big: $KERNEL_SIZE > $KERNEL_MAX"; exit 1; }
[ "$ROOTFS_SIZE" -le "$ROOTFS_MAX" ] || { echo "rootfs too big: $ROOTFS_SIZE > $ROOTFS_MAX"; exit 1; }

# Fill with 0xFF (erased flash), then dd each piece in place.
dd if=/dev/zero bs=1M count=$((TOTAL_SIZE / 1048576)) status=none | tr '\000' '\377' > "$OUT"
dd if="$UBOOT"  of="$OUT" bs=1 seek=0                conv=notrunc status=none
dd if="$KERNEL" of="$OUT" bs=1 seek="$KERNEL_OFFSET" conv=notrunc status=none
dd if="$ROOTFS" of="$OUT" bs=1 seek="$ROOTFS_OFFSET" conv=notrunc status=none

echo "wrote $OUT ($(stat -c %s "$OUT") bytes, $FLASH_SIZE layout)"
echo "  u-boot: $UBOOT_SIZE / $UBOOT_MAX bytes  ($UBOOT)"
echo "  kernel: $KERNEL_SIZE / $KERNEL_MAX bytes (offset 0x$(printf '%x' "$KERNEL_OFFSET"))"
echo "  rootfs: $ROOTFS_SIZE / $ROOTFS_MAX bytes (offset 0x$(printf '%x' "$ROOTFS_OFFSET"))"
