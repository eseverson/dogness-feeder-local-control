#!/bin/sh
# Build the patched U-Boot for hi3518ev200 with BY25Q256 SPI NOR support
# and high-baud (up to 921600) serial console.
#
# Output: u-boot-hi3518ev200-by25q256.bin (~135KB) — flashable to offset 0
# of a 32MB BY25Q256FSSIG (or any chip the patch table covers).
#
# This is just an automation wrapper around the upstream Hi3518 U-Boot
# build sequence with a few quirks ironed out:
#   1. The shipped build.sh expects arm-hisiv510-linux- but most Hi3518
#      toolchains in circulation are arm-hisiv300-linux-uclibcgnueabi-.
#      We force the v300 toolchain prefix and ensure common/Makefile
#      knows about it (handled by patch 0005).
#   2. distclean from this U-Boot tree deletes *.bin including the DDR
#      reg_info_*.bin files. We avoid distclean and use targeted cleans.
#   3. The build needs `lzma` on PATH for image compression. On Fedora 42
#      that's `xz-lzma-compat`; we provide a wrapper at ~/.local/bin/lzma
#      if missing.
#
# Apply patches: see patches/u-boot/*.patch
# To re-apply from a fresh clone:
#   cd u-boot-hi3516cv200
#   for p in ../patches/u-boot/*.patch; do git apply "$p"; done

set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
UBOOT_DIR=${UBOOT_DIR:-$ROOT/u-boot-hi3516cv200}
TOOLCHAIN_DIR=${TOOLCHAIN_DIR:-$HOME/Downloads/hisi-linux/x86-arm/arm-hisiv300-linux}
SOC=${SOC:-hi3518ev200}
OUT=${OUT:-$ROOT/u-boot-hi3518ev200-by25q256.bin}

if [ ! -d "$UBOOT_DIR" ]; then
    echo "error: U-Boot tree not found at $UBOOT_DIR" >&2
    exit 1
fi
if [ ! -x "$TOOLCHAIN_DIR/bin/arm-hisiv300-linux-uclibcgnueabi-gcc" ]; then
    echo "error: hisiv300 toolchain not found at $TOOLCHAIN_DIR" >&2
    echo "  download from your Hi3518 SDK distributor and untar to that path," >&2
    echo "  or override with TOOLCHAIN_DIR=..." >&2
    exit 1
fi

# Ensure lzma command is available (xz --format=lzma works fine if you don't
# have xz-lzma-compat installed). We don't auto-install; we just create a
# small wrapper in ~/.local/bin if neither package nor wrapper exists.
if ! command -v lzma >/dev/null 2>&1; then
    mkdir -p "$HOME/.local/bin"
    cat > "$HOME/.local/bin/lzma" <<'EOF'
#!/bin/sh
exec /usr/bin/xz --format=lzma "$@"
EOF
    chmod +x "$HOME/.local/bin/lzma"
    echo "info: installed lzma wrapper at ~/.local/bin/lzma"
fi

export PATH=$TOOLCHAIN_DIR/bin:$HOME/.local/bin:$PATH
export ARCH=arm
export CROSS_COMPILE=arm-hisiv300-linux-uclibcgnueabi-

cd "$UBOOT_DIR"

# Targeted clean — never use 'make distclean' here; it nukes reg_info_*.bin.
echo "==> cleaning previous artifacts"
rm -f \
    u-boot u-boot.bin u-boot.srec u-boot.map mini-boot.bin \
    drivers/mtd/spi/hifmc100/hifmc_spi_nor_ids.o \
    drivers/mtd/spi/hifmc100/libhifmcv100.a \
    drivers/serial/serial_pl01x.o drivers/serial/libserial.a \
    arch/arm/lib/board.o arch/arm/lib/libarm.a \
    arch/arm/cpu/${SOC}/compressed/image_data.lzma \
    arch/arm/cpu/${SOC}/compressed/image_data.o \
    arch/arm/cpu/${SOC}/compressed/mini-boot.bin \
    arch/arm/cpu/${SOC}/compressed/mini-boot.elf

# If reg_info files were previously deleted, restore from git.
for f in reg_info_${SOC}.bin reg_info_hi3516cv200.bin reg_info_hi3518ev201.bin; do
    if [ ! -f "$f" ] && git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        git checkout -- "$f"
    fi
done

echo "==> configuring for $SOC"
make ${SOC}_config >/dev/null
cp reg_info_${SOC}.bin .reg

# bootss2.a comes pre-built per (CROSS_COMPILE, SOC) combo. The Makefile only
# knows about the bare prefix; patch 0005 adds the uclibcgnueabi variant.
if [ ! -f common/bootss2.a ]; then
    if [ -f "common/cmd_bootss2_v300_${SOC}" ]; then
        cp "common/cmd_bootss2_v300_${SOC}" common/bootss2.a
    fi
fi

echo "==> building u-boot.bin"
make -j"$(nproc)"

echo "==> wrapping into mini-boot.bin"
make mini-boot.bin

cp mini-boot.bin "$OUT"
SIZE=$(stat -c %s "$OUT")
echo
echo "==> wrote $OUT ($SIZE bytes)"
if [ $SIZE -gt $((0x50000)) ]; then
    echo "WARNING: $SIZE > 0x50000 — won't fit in standard 320KB boot partition"
fi
