#!/bin/sh
# mcu_tool.sh — send commands to the Dogness STC15W408AS MCU and print any responses.
#
# Pure shell + busybox (stty, printf, cat, hexdump or od). Runs on OpenIPC.
#
# Wire: 115200 8N1, no flow control.
#
# Usage:
#   mcu_tool.sh [-p PORT] [-t SECS] <cmd> [args...]
#
# Commands:
#   time-sync                       send time-sync packet built from current time
#   get-time                        query current MCU clock
#   get-version                     query MCU firmware version string
#   motor-test                      run a brief motor self-test on the MCU
#   manual-feed <weight>            send one-shot manual feed (10..255 — min 10)
#   auto-feed <h> <m> <w> [audio] [slot]
#                                   schedule a one-shot feed for HH:MM (MCU clock).
#                                   weight ≥ 10, audio defaults to 0 (silent),
#                                   slot defaults to 1 (must be 1..8, never 0).
#   meal <n> <h> <m> <w> [on|off]   recurring meal slot (n=1..6 named, plus 7-8)
#   read-schedule [slot]            read schedule table. With no arg dumps all 8
#                                   slots; with slot=1..8 reads just that slot.
#   clear-schedule [slot]           clear schedule slots. With no arg clears all
#                                   8 slots; with slot=1..8 clears just that one.
#                                   Sends a disabled meal record (weight=0,
#                                   enable=0x10) to each target slot.
#   raw <hex>                       send arbitrary bytes ('ff ff 06 06 ...')
#   listen                          just print whatever the MCU emits
#
# Examples:
#   ./mcu_tool.sh -p /dev/ttyAMA2 time-sync
#   ./mcu_tool.sh -p /dev/ttyAMA2 get-time
#   ./mcu_tool.sh -p /dev/ttyAMA2 read-schedule          # dump all 8 slots
#   ./mcu_tool.sh -p /dev/ttyAMA2 read-schedule 1        # just slot 1
#   ./mcu_tool.sh -t 30 listen
#   ./mcu_tool.sh manual-feed 10
#   ./mcu_tool.sh -t 120 auto-feed 8 30 25               # slot 1, weight 25
#   ./mcu_tool.sh raw 'ff ff 06 06 0e 20 0f 00 00 00'

set -u

PORT=/dev/ttyS0
LISTEN_SECS=5
RX_FILE=/tmp/mcu_rx.bin

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        -p) PORT="$2"; shift 2;;
        -t) LISTEN_SECS="$2"; shift 2;;
        -h|--help) usage;;
        *) break;;
    esac
done

[ $# -ge 1 ] || usage

ts() { date +%H:%M:%S; }

# Abort with an error if any arg isn't a non-negative integer (decimal or 0xNN).
require_uint() {
    for v in "$@"; do
        case "$v" in
            ''|*[!0-9a-fA-FxX]*) echo "error: '$v' is not a number" >&2; exit 1 ;;
            0x*) ;;
            *[!0-9]*) echo "error: '$v' is not a number" >&2; exit 1 ;;
        esac
    done
}

dump_rx() {
    # Pretty-print collected RX bytes as hex.
    if [ ! -s "$RX_FILE" ]; then
        echo "[$(ts)] (no response)"
        return
    fi
    echo "[$(ts)] RX:"
    if command -v hexdump >/dev/null 2>&1; then
        hexdump -C "$RX_FILE"
    else
        od -An -tx1z "$RX_FILE"
    fi
    frame_dump "$RX_FILE"
}

frame_dump() {
    # Walk the bytes looking for MCU response frames.
    #
    # Per rec_serial_device(): SOF is FF followed by any byte >= FC
    # (so FF FC, FF FD, FF FE, FF FF — the second SOF byte encodes the
    # response class). Then byte 2 = cmd, byte 3 = payload length L,
    # bytes 4..(3+L) = payload.  Total frame size = L + 4.
    od -An -tx1 -v "$1" 2>/dev/null | tr -s ' \n' ' ' | awk '
    {
        for (i = 1; i <= NF; i++) buf[++n] = $i
    }
    END {
        for (k = 0; k <= 9; k++) hx[k] = k
        hx["a"] = 10; hx["b"] = 11; hx["c"] = 12
        hx["d"] = 13; hx["e"] = 14; hx["f"] = 15
        i = 1
        while (i <= n - 3) {
            if (buf[i] == "ff") {
                b1 = buf[i+1]
                # SOF second byte must be FC..FF
                if (b1 == "fc" || b1 == "fd" || b1 == "fe" || b1 == "ff") {
                    lb = buf[i+3]
                    hi = hx[substr(lb,1,1)]; lo = hx[substr(lb,2,1)]
                    len = hi * 16 + lo
                    total = len + 4
                    if (len >= 0 && len <= 24 && i + total - 1 <= n) {
                        s = "FRAME sof=" buf[i] buf[i+1] " cmd=" buf[i+2] " len=" len " payload="
                        for (j = 0; j < len; j++) s = s " " buf[i+4+j]
                        print s
                        i += total
                        continue
                    }
                }
            }
            i++
        }
    }'
}

setup_port() {
    if [ ! -c "$PORT" ]; then
        echo "$PORT not a character device" >&2
        exit 2
    fi
    # Warn if another process already has the port open — it will race with
    # our reader and steal MCU response bytes.
    if command -v fuser >/dev/null 2>&1; then
        holders=$(fuser "$PORT" 2>/dev/null | tr -s ' ')
        if [ -n "$holders" ]; then
            echo "[$(ts)] warn: $PORT already open by PID(s):$holders — responses may be lost" >&2
        fi
    fi
    # min 1 time 0  → read(2) blocks until at least 1 byte arrives, so our
    # background `cat` keeps running instead of hitting an immediate EOF.
    stty -F "$PORT" 115200 cs8 -cstopb -parenb -ixon -ixoff -crtscts raw -echo \
        min 1 time 0 2>/dev/null || {
            # busybox stty subset
            stty -F "$PORT" 115200 cs8 -cstopb -parenb raw -echo
        }
}

start_reader() {
    : > "$RX_FILE"
    cat "$PORT" >> "$RX_FILE" &
    READ_PID=$!
    # tiny settle
    sleep 0.05 2>/dev/null || true
}

stop_reader() {
    [ -n "${READ_PID:-}" ] || return 0
    kill "$READ_PID" 2>/dev/null
    # cat may be blocked in read(); give SIGTERM a moment, then SIGKILL.
    sleep 1
    kill -0 "$READ_PID" 2>/dev/null && kill -9 "$READ_PID" 2>/dev/null
    wait "$READ_PID" 2>/dev/null
}

hex_to_escapes() {
    # 'ff ff 01' -> '\xff\xff\x01'
    echo "$1" | tr ',:' '  ' | tr -s ' ' | sed 's/0x//g; s/[^0-9a-fA-F ]//g' \
        | tr ' ' '\n' | grep -v '^$' \
        | while read -r b; do printf '\\x%s' "$b"; done
}

tx_hex() {
    local hex="$1"
    echo "[$(ts)] TX $hex"
    local esc
    esc=$(hex_to_escapes "$hex")
    # busybox printf supports \xNN
    # shellcheck disable=SC2059
    printf "$esc" > "$PORT"
}

# --- packet builders -----------------------------------------------------

build_time_sync() {
    # FF FF 06 06 <year-60> <month> <day> <hour> <min> <sec>
    # Confirmed from disassembly of Timestamp::sperateHourMinSeond
    # in libjiake_sdk.so: the host emits 6 time bytes in this exact
    # order, where the year byte is (tm_year + 1900) - 1960, i.e.
    # years since 1960.
    local y mon dom h m s
    y=$(date +%Y);   y=$((10#$y - 1960))
    mon=$(date +%m); mon=$((10#$mon))
    dom=$(date +%d); dom=$((10#$dom))
    h=$(date +%H);   h=$((10#$h))
    m=$(date +%M);   m=$((10#$m))
    s=$(date +%S);   s=$((10#$s))
    printf 'ff ff 06 06 %02x %02x %02x %02x %02x %02x' \
        "$y" "$mon" "$dom" "$h" "$m" "$s"
}

build_manual_feed() {
    local w=$(($1 & 0xff))
    printf 'ff ff 01 0a 3a 09 03 0e 0b %02x 00 00 00 0a' "$w"
}

build_auto_feed() {
    # build_auto_feed <hour> <min> <weight> [audio_idx] [slot] [enable]
    #
    # Wire bytes:
    #   byte 9-10 = weight (LE16, minimum 10 to dispense)
    #   byte 11   = enable flag (0x11 = on, 0x10 = off — same convention as meal records)
    #   byte 12   = slot index (1..8 — required! 0 is silently rejected)
    #   byte 13   = audio_idx (0 = no audio)
    #
    # Defaults: audio_idx=0, slot=1, enable=on.
    local h=$(($1 & 0xff)) m=$(($2 & 0xff)) w=$(($3))
    local audio=$((${4:-0} & 0xff))
    local slot=$((${5:-1} & 0xff))
    local en_flag=${6:-on}
    local en=0x11
    case "$en_flag" in off|0|disable) en=0x10 ;; esac
    local wl=$((w & 0xff)) wh=$(((w >> 8) & 0xff))
    printf 'ff ff 01 0a a5 a7 7f %02x %02x %02x %02x %02x %02x %02x' \
        "$h" "$m" "$wl" "$wh" "$en" "$slot" "$audio"
}

build_get_time()      { printf 'ff ff 09 00'; }
build_get_version()   { printf 'ff ff 0d 00'; }
build_motor_test()    { printf 'ff ff 0f 00'; }

# Read schedule table. With no arg, payload byte = 0 (dump all). Otherwise pass slot.
build_read_schedule() {
    local slot=${1:-0}
    printf 'ff ff 02 01 %02x' "$((slot & 0xff))"
}

build_meal_slot() {
    # n h m w [on|off]
    local n=$(($1 & 0xff)) h=$(($2 & 0xff)) m=$(($3 & 0xff)) w=$(($4 & 0xff))
    local en=0x11
    case "${5:-on}" in
        off|0|disable) en=0x10 ;;
    esac
    printf 'ff ff 02 0a 12 01 01 %02x %02x %02x 00 %02x %02x 00 01 00' \
        "$h" "$m" "$w" "$en" "$n"
}

# Echoes "H M" given an offset in minutes from current host clock.
compute_hm_in() {
    local off now_h now_m total
    off=$1
    now_h=$(date +%H); now_h=$((10#$now_h))
    now_m=$(date +%M); now_m=$((10#$now_m))
    total=$((now_h * 60 + now_m + off))
    echo "$((total / 60 % 24)) $((total % 60))"
}

# --- main ----------------------------------------------------------------

CMD="$1"; shift
PKT2=""

case "$CMD" in
    time-sync)
        PKT=$(build_time_sync) ;;
    manual-feed)
        [ $# -ge 1 ] || { echo "manual-feed needs <weight>" >&2; exit 1; }
        require_uint "$1"
        PKT=$(build_manual_feed "$1") ;;
    auto-feed)
        [ $# -ge 3 ] || { echo "auto-feed needs <h> <m> <weight> [audio_idx] [slot=1..6]" >&2; exit 1; }
        require_uint "$1" "$2" "$3" ${4:+"$4"} ${5:+"$5"}
        PKT=$(build_auto_feed "$1" "$2" "$3" "${4:-0}" "${5:-1}") ;;
    feed-in)
        [ $# -ge 2 ] || { echo "feed-in needs <minutes> <weight>" >&2; exit 1; }
        require_uint "$1" "$2"
        PKT=$(build_auto_feed $(compute_hm_in "$1") "$2" 1 0) ;;
    sync-and-feed-in)
        [ $# -ge 2 ] || { echo "sync-and-feed-in needs <minutes> <weight>" >&2; exit 1; }
        require_uint "$1" "$2"
        PKT=$(build_time_sync)
        PKT2=$(build_auto_feed $(compute_hm_in "$1") "$2" 1 0) ;;
    meal)
        [ $# -ge 4 ] || { echo "meal needs <n> <h> <m> <w> [on|off]" >&2; exit 1; }
        require_uint "$1" "$2" "$3" "$4"
        PKT=$(build_meal_slot "$1" "$2" "$3" "$4" "${5:-on}") ;;
    get-time)
        PKT=$(build_get_time) ;;
    get-version)
        PKT=$(build_get_version) ;;
    motor-test)
        PKT=$(build_motor_test) ;;
    read-schedule)
        if [ $# -ge 1 ]; then require_uint "$1"; fi
        PKT=$(build_read_schedule "${1:-0}") ;;
    clear-schedule)
        # Schedules are recurring daily — past-time does not save us.
        # Set the enable flag (byte 11 = 0x10) to disable each slot.
        # Weight=10 satisfies the MCU's minimum-weight check (which
        # validates the field even when disabled, in case enable is
        # only honored at fire time).
        if [ $# -ge 1 ]; then
            require_uint "$1"
            PKT=$(build_auto_feed 0 0 10 0 "$1" off)
        else
            PKT=""
            i=1
            while [ "$i" -le 8 ]; do
                line=$(build_auto_feed 0 0 10 0 "$i" off)
                PKT="${PKT}${line}
"
                i=$((i + 1))
            done
        fi ;;
    raw)
        [ $# -ge 1 ] || { echo "raw needs <hex>" >&2; exit 1; }
        PKT="$1" ;;
    listen)
        PKT="" ;;
    *)
        echo "unknown command: $CMD" >&2; usage ;;
esac

echo "[$(ts)] open $PORT 115200 8N1 (listen ${LISTEN_SECS}s)"
setup_port
start_reader
trap 'stop_reader; exit 130' INT TERM

if [ -n "$PKT" ]; then
    # PKT may be multi-line — send each line as a separate frame, with 1s spacing
    first=1
    echo "$PKT" | while IFS= read -r line; do
        [ -z "$line" ] && continue
        [ "$first" -eq 1 ] || sleep 1
        first=0
        tx_hex "$line"
    done
fi
if [ -n "$PKT2" ]; then
    sleep 1
    tx_hex "$PKT2"
fi

# busybox sleep accepts integer seconds; use a portable wait
i=0
while [ "$i" -lt "$LISTEN_SECS" ]; do
    sleep 1
    i=$((i + 1))
done

stop_reader
dump_rx
