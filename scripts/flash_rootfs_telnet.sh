#!/bin/bash
# flash_rootfs_telnet.sh - Flash rootfs via telnet on the ORIGINAL firmware
#
# Use this ONLY when the device is still running the stock Dogness firmware,
# which has telnetd on port 23 (root / 059AnkJ).
#
# Once the custom ROM is running, use SSH + flash_rootfs_ssh.sh instead,
# or reflash via U-Boot YMODEM (scripts/flash_via_uboot.sh).
#
# WARNING: If flashing fails mid-way, the device may not boot.
# Ensure you have a recovery plan (serial console, YMODEM via picocom).
#
# Usage: ./flash_rootfs_telnet.sh [rootfs.img] [device_ip]

set -e

ROMDIR="$(cd "$(dirname "$0")/.." && pwd)"
IMG="${1:-$ROMDIR/flash/rootfs.img}"
DEVICE="${2:-192.168.1.137}"
DEVICE_PORT=23
DEVICE_USER=root
DEVICE_PASS="059AnkJ"
HOST_IP="${HOST_IP:-192.168.1.2}"   # your machine's IP

MTD_DEVICE=/dev/mtd2                  # rootfs partition (8MB layout)
TMPFS_PATH=/tmp/rootfs.img
if [ ! -f "$IMG" ]; then
    echo "ERROR: Image not found: $IMG"
    echo "Run: flash/pack_images.sh first"
    exit 1
fi

IMG_KB=$(( $(stat -c%s "$IMG") / 1024 ))
LOCAL_MD5=$(md5sum "$IMG" | cut -d' ' -f1)
echo "=== Rootfs flash via telnet ==="
echo "Image:  $IMG ($IMG_KB KB)"
echo "MD5:    $LOCAL_MD5"
echo "Target: $DEVICE:$MTD_DEVICE"
echo ""

TMPFS_DIR=/tmp

echo "Cleaning up old image and checking free space..."
TMPFS_FREE_KB=$(
    (
        sleep 1
        printf "%s\r\n" "$DEVICE_USER"
        sleep 1
        printf "%s\r\n" "$DEVICE_PASS"
        sleep 1
        printf "killall nc 2>/dev/null; true\r\n"
        sleep 1
        printf "rm -f %s\r\n" "$TMPFS_PATH"
        sleep 1
        printf "df %s\r\n" "$TMPFS_DIR"
        sleep 2
        printf "exit\r\n"
    ) | nc "$DEVICE" "$DEVICE_PORT" 2>/dev/null \
      | tr -d '\r' \
      | awk '/\/tmp$/{print $4}' \
    || true
)
if [ -z "$TMPFS_FREE_KB" ]; then
    echo "ERROR: Could not query free space on device at $TMPFS_DIR"
    exit 1
fi
echo "Device tmpfs free: $TMPFS_FREE_KB KB"

if [ "$IMG_KB" -gt "$TMPFS_FREE_KB" ]; then
    echo "ERROR: Image ($IMG_KB KB) exceeds available tmpfs space ($TMPFS_FREE_KB KB)"
    exit 1
fi

# ── Step 1: Transfer image via HTTP ──────────────────────────────────────────
echo "[1/3] Transferring image to device tmpfs..."

HTTP_PORT=9997
IMG_BASENAME="$(basename "$IMG")"

# Serve the flash directory via Python HTTP server
python3 -m http.server "$HTTP_PORT" --directory "$(dirname "$IMG")" &>/dev/null &
HTTP_PID=$!
sleep 1  # let server start

echo "  wget http://$HOST_IP:$HTTP_PORT/$IMG_BASENAME -> $TMPFS_PATH"
echo "  Waiting for transfer to complete..."
(
    sleep 1
    printf "%s\r\n" "$DEVICE_USER"
    sleep 1
    printf "%s\r\n" "$DEVICE_PASS"
    sleep 1
    printf "wget http://%s:%s/%s -O %s\r\n" "$HOST_IP" "$HTTP_PORT" "$IMG_BASENAME" "$TMPFS_PATH"
    # wget runs in foreground; 4.5MB at LAN speeds < 5s; allow generous margin
    sleep 60
    printf "exit\r\n"
    sleep 1
) | nc "$DEVICE" "$DEVICE_PORT" 2>/dev/null || true

kill $HTTP_PID 2>/dev/null || true

echo ""
echo "[2/3] Verifying transfer..."
REMOTE_MD5=$(
    (
        sleep 1
        printf "%s\r\n" "$DEVICE_USER"
        sleep 1
        printf "%s\r\n" "$DEVICE_PASS"
        sleep 1
        printf "md5sum %s\r\n" "$TMPFS_PATH"
        sleep 5
        printf "exit\r\n"
    ) | nc "$DEVICE" "$DEVICE_PORT" 2>/dev/null | grep -o '[0-9a-f]\{32\}' | tail -1 || true
)
echo "Local  MD5: $LOCAL_MD5"
echo "Remote MD5: $REMOTE_MD5"
if [ "$REMOTE_MD5" != "$LOCAL_MD5" ]; then
    echo "ERROR: MD5 mismatch — transfer corrupted or incomplete. Aborting flash."
    exit 1
fi
echo "MD5 verified OK."

# ── Step 2: Flash via flashcp ────────────────────────────────────────────────
echo ""
echo "[3/3] Flashing rootfs (DO NOT POWER OFF)..."
(
    sleep 1
    printf "%s\r\n" "$DEVICE_USER"
    sleep 1
    printf "%s\r\n" "$DEVICE_PASS"
    sleep 1
    # Free memory by stopping the camera server; leave feed_watchdog alone
    # so the hardware WDT keeps being satisfied during the flash operation.
    printf "killall IPServer 2>/dev/null; true\r\n"
    sleep 2
    printf "echo 'Flashing rootfs...'\r\n"
    printf "flash_eraseall %s && flashcp -v %s %s\r\n" "$MTD_DEVICE" "$TMPFS_PATH" "$MTD_DEVICE"
    sleep 60
    printf "echo 'Flash complete. Rebooting...'\r\n"
    sleep 1
    printf "reboot\r\n"
    sleep 5
) | nc "$DEVICE" "$DEVICE_PORT" 2>&1 | tee /tmp/flash_log.txt

echo ""
echo "Flash log saved to /tmp/flash_log.txt"
echo ""
echo "Device should be rebooting with custom ROM."
echo "Wait 30 seconds then:"
echo "  ssh root@$DEVICE       (new dropbear SSH)"
echo "  telnet $DEVICE         (original telnet still available)"
