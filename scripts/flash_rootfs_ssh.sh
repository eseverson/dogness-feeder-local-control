#!/bin/bash
# Flash OpenIPC rootfs (and optionally kernel) to device via SSH
#
# Expects the device is already running OpenIPC with SSH (dropbear).
#
# Usage: ./flash_rootfs_ssh.sh [rootfs.img] [device_ip] [--kernel [kernel.img]]
#
# Examples:
#   ./flash_rootfs_ssh.sh                                        # rootfs only, defaults
#   ./flash_rootfs_ssh.sh "" 192.168.1.135                       # rootfs only, custom IP
#   ./flash_rootfs_ssh.sh "" 192.168.1.135 --kernel              # rootfs + kernel, default kernel path
#   ./flash_rootfs_ssh.sh "" 192.168.1.135 --kernel uImage       # rootfs + custom kernel

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGES_DIR="$ROOT/firmware/output/images"

ROOTFS_IMG="${1:-$IMAGES_DIR/rootfs.squashfs.hi3518ev200}"
DEVICE="${2:-192.168.1.135}"

KERNEL_IMG=""
if [ "${3}" = "--kernel" ]; then
    KERNEL_IMG="${4:-$IMAGES_DIR/uImage.hi3518ev200}"
fi

SSH_USER=root
HOST_IP="${HOST_IP:-$(ip route get "$DEVICE" 2>/dev/null | awk '/src/{print $5; exit}')}"
HTTP_PORT=9997

SSH="ssh -v -o StrictHostKeyChecking=no -o ConnectTimeout=10 $SSH_USER@$DEVICE"

# ── Validate inputs ───────────────────────────────────────────────────────────
if [ ! -f "$ROOTFS_IMG" ]; then
    echo "ERROR: Rootfs image not found: $ROOTFS_IMG"
    echo "Build first: make BOARD=hi3518ev200_lite"
    exit 1
fi

if [ -n "$KERNEL_IMG" ] && [ ! -f "$KERNEL_IMG" ]; then
    echo "ERROR: Kernel image not found: $KERNEL_IMG"
    exit 1
fi

if [ -z "$HOST_IP" ]; then
    echo "ERROR: Could not determine host IP. Set HOST_IP env var:"
    echo "  HOST_IP=192.168.1.x $0 $*"
    exit 1
fi

# ── Verify MTD layout ─────────────────────────────────────────────────────────
echo "Verifying MTD layout on device..."
MTD_MAP=$($SSH "cat /proc/mtd" 2>/dev/null)

check_mtd() {
    local num="$1" expected="$2"
    local name
    name=$(echo "$MTD_MAP" | grep "mtd${num}" | awk -F'"' '{print $2}')
    if [ "$name" != "$expected" ]; then
        echo "ERROR: mtd${num} is '$name', expected '$expected'"
        echo "Check: ssh $SSH_USER@$DEVICE cat /proc/mtd"
        exit 1
    fi
}

check_mtd 3 "rootfs"
[ -n "$KERNEL_IMG" ] && check_mtd 2 "kernel"

get_mtd_kb() {
    local num="$1"
    local hex
    hex=$(echo "$MTD_MAP" | awk "/mtd${num}:/{print \"0x\"\$2}")
    echo $(( hex / 1024 ))
}

# ── Print plan ────────────────────────────────────────────────────────────────
echo "=== OpenIPC flash via SSH ==="
echo "Target: $DEVICE"
ROOTFS_KB=$(( $(stat -c%s "$ROOTFS_IMG") / 1024 ))
ROOTFS_MTD_KB=$(get_mtd_kb 3)
echo "Rootfs: $ROOTFS_IMG ($ROOTFS_KB KB) → mtd3 ($ROOTFS_MTD_KB KB)"
if [ -n "$KERNEL_IMG" ]; then
    KERNEL_KB=$(( $(stat -c%s "$KERNEL_IMG") / 1024 ))
    KERNEL_MTD_KB=$(get_mtd_kb 2)
    echo "Kernel: $KERNEL_IMG ($KERNEL_KB KB) → mtd2 ($KERNEL_MTD_KB KB)"
fi
echo ""

# ── Size checks ───────────────────────────────────────────────────────────────
if [ "$ROOTFS_KB" -gt "$ROOTFS_MTD_KB" ]; then
    echo "ERROR: Rootfs ($ROOTFS_KB KB) exceeds partition size ($ROOTFS_MTD_KB KB)"
    exit 1
fi
if [ -n "$KERNEL_IMG" ] && [ "$KERNEL_KB" -gt "$KERNEL_MTD_KB" ]; then
    echo "ERROR: Kernel ($KERNEL_KB KB) exceeds partition size ($KERNEL_MTD_KB KB)"
    exit 1
fi

TMPFS_FREE_KB=$($SSH "df /tmp" 2>/dev/null | awk 'NR==2{print $4}')
if [ -z "$TMPFS_FREE_KB" ]; then
    echo "ERROR: SSH connection failed"
    exit 1
fi

TOTAL_KB=$(( ROOTFS_KB + ${KERNEL_KB:-0} ))
if [ "$TOTAL_KB" -gt "$TMPFS_FREE_KB" ]; then
    echo "ERROR: Total images ($TOTAL_KB KB) exceed /tmp free space ($TMPFS_FREE_KB KB)"
    exit 1
fi

# ── Copy flash tools to tmpfs before we erase anything ───────────────────────
$SSH "cp /usr/sbin/flashcp /tmp/flashcp; cp /usr/sbin/flash_eraseall /tmp/flash_eraseall"

# ── Transfer-only function (no flashing yet) ──────────────────────────────────
transfer_image() {
    local label="$1" img="$2" tmppath="$3"

    local img_basename local_md5
    img_basename="$(basename "$img")"
    local_md5=$(md5sum "$img" | cut -d' ' -f1)

    echo "[$label] Transferring $(basename "$img")..."
    python3 -m http.server "$HTTP_PORT" --directory "$(dirname "$img")" &>/dev/null &
    local http_pid=$!
    trap "kill $http_pid 2>/dev/null; true" EXIT
    sleep 1

    $SSH "rm -f $tmppath; wget -q http://$HOST_IP:$HTTP_PORT/$img_basename -O $tmppath"
    kill $http_pid 2>/dev/null; trap - EXIT

    local remote_md5
    remote_md5=$($SSH "md5sum $tmppath" | cut -d' ' -f1)
    if [ "$remote_md5" != "$local_md5" ]; then
        echo "ERROR: MD5 mismatch on $label — aborting"
        echo "  Local:  $local_md5"
        echo "  Remote: $remote_md5"
        $SSH "rm -f $tmppath"
        exit 1
    fi
    echo "[$label] MD5 verified OK ($local_md5)"
}

# Transfer everything first — SSH stays healthy while flash partitions are intact.
transfer_image "rootfs" "$ROOTFS_IMG" /tmp/rootfs.img
[ -n "$KERNEL_IMG" ] && transfer_image "kernel" "$KERNEL_IMG" /tmp/kernel.img

# Build the flash sequence. Erasing mtd3 (rootfs) kills SSH because dropbear
# can no longer page in libs from squashfs — so run the whole sequence detached
# under nohup. It runs to reboot regardless of what the SSH client does.
FLASH_CMDS=""
if [ -n "$KERNEL_IMG" ]; then
    FLASH_CMDS="$FLASH_CMDS /tmp/flash_eraseall /dev/mtd2 && /tmp/flashcp -v /tmp/kernel.img /dev/mtd2;"
fi
FLASH_CMDS="$FLASH_CMDS /tmp/flash_eraseall /dev/mtd3 && /tmp/flashcp -v /tmp/rootfs.img /dev/mtd3;"

echo "Flashing (DO NOT POWER OFF) — runs detached, will reboot when done..."
$SSH "nohup sh -c '$FLASH_CMDS reboot' >/tmp/flash.log 2>&1 </dev/null &"

echo "Flash dispatched. Wait ~60s then: ssh $SSH_USER@$DEVICE"
echo "On next boot, log lives at /tmp/flash.log only until tmpfs is rebuilt — already gone after reboot."
