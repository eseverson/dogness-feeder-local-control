# Dogness Pet Feeder — MCU UART Protocol Reference

> **Status.** Reconstructed by static analysis of the stock firmware and validated
> in practice by `catd`, which speaks this protocol to the MCU. Confidence tags:
> **HIGH** = observed wire bytes; **MEDIUM** = inferred from firmware log strings /
> structure; **LOW** = informed guess. Frames that aren't fully decoded are flagged
> inline.

STC15W408AS MCU ↔ Hi3518E SoC, binary serial, **115200 8N1**, no flow control, on
UART2 (`/dev/ttyAMA2` on OpenIPC; `/dev/ttyS0` = `ttyAMA1` on the stock kernel).
The MCU owns the feed + shoot motors; the SoC has **no direct GPIO path to
feeding**, so every feed goes over this link. `catd` is the reference
implementation of everything below.

---

## 1. Architecture

```
 Cloud (MQTT voice/<dev>, P2P)
        │
        ▼
   SoC firmware ──(builds FF FF … frames)──►  UART2  ──►  STC15W408AS MCU
        ▲                                                  - drives feed + shoot motors
        └───────────(FF FF … framed replies)──────────────  - reports a per-feed result
```

On the stock firmware the cloud paths (phone app, Alexa-over-MQTT, P2P) land in the
SoC, which serializes feed / schedule / time commands to the MCU and parses its
framed replies. The cloud/Alexa bridge reaches the encoder through shared memory,
not the UART directly (§6). `catd` replaces the entire SoC-side role.

---

## 2. Serial Port Configuration

| Parameter | Value |
|---|---|
| Baud | **115200** |
| Data / parity / stop | 8 / none / 1 |
| Flow control | none (`IGNPAR`, `VMIN=0`, `VTIME=5`) |

No init handshake is sent — the MCU emits its version banner unsolicited shortly
after the port opens.

**Open glitch:** opening the port makes the MCU latch a `0xFF` framing error. Keep
the fd open persistently and flush ~16 null bytes on connect to clear it (what
`catd` does) before sending a real command.

---

## 3. Frame Format

```
┌────────┬──────────┬─────────┬──────────────────────────┐
│  SOF   │ CMD/LEN  │ PAYLOAD │ TERMINATOR (some frames) │
│ FF FF  │  varies  │ N bytes │       0x0A               │
└────────┴──────────┴─────────┴──────────────────────────┘
```

- **SOF** is `FF FF` (both ends use it to resync after noise); some MCU response
  frames use a `FF FC` variant (see §5.1).
- Length / opcode bytes vary per command; there is **no universal length field and
  no checksum**. The `0x0A` (`'\n'`) trailer on some frames is a literal stop byte.
- The receive buffer is capped at **24 bytes**; a length byte > 24 drops the frame.

---

## 4. SoC → MCU (TX)

### 4.1 Manual feed — 14 bytes — **HIGH**

Trigger: "feed now" in the app, or an MQTT `manualfeedreq`.

```
Offset  Hex   Meaning
─────────────────────────────────────────
  0     FF    SOF byte 0
  1     FF    SOF byte 1
  2     01    Command class: 0x01 = manual feed
  3     0A    Fixed (10)
  4     3A    Manual-feed marker (':')
  5     09    Fixed
  6     03    Fixed
  7     0E    Total length = 14
  8     0B    Sub-opcode (11)
  9     WW    Weight (uint8, 0–255)
 10–12  00    Reserved / padding
 13     0A    Terminator '\n'
```

Example (weight = 1): `FF FF 01 0A 3A 09 03 0E 0B 01 00 00 00 0A`

### 4.2 Scheduled / auto feed — 14 bytes — **HIGH (bytes), MEDIUM (field semantics)**

Trigger: schedule sync — one packet per meal slot. The cloud layer only ever sends
**one HH:MM at a time** (no batch schedule frame); multiple meals are sent one at a
time.

```
Offset  Hex/Var   Meaning
──────────────────────────────────────────────
  0     FF        SOF
  1     FF        SOF
  2     01        Command class: 0x01 (same class as manual)
  3     0A        Fixed
  4     A5        Auto-feed marker (vs 0x3A for manual)
  5     A7        Fixed
  6     7F        Fixed
  7     HH        Hour (0–23)
  8     MM        Minute (0–59)
  9     CL        Count low byte (count & 0xFF)
 10     CH        Count high byte (count >> 8)
 11     11        Fixed (17)
 12     DD        Delay (uint8 seconds between cycles)
 13     WW        Weight (uint8)
```

Example — `08:30, weight 5, count 2, delay 60s`: `FF FF 01 0A A5 A7 7F 08 1E 02 00 11 3C 05`

The differentiator from manual feed is bytes 4–6 (`A5 A7 7F` vs `3A 09 03 0E`); the
MCU dispatches on these. **Not fully decoded:** the firmware writes 14 bytes with
no explicit `0x0A` terminator here — unconfirmed whether the wire frame appends one.

### 4.3 Time sync — 10 bytes — **MEDIUM**

```
Offset  Hex/Var   Meaning
─────────────────────────────────
  0     FF        SOF
  1     FF        SOF
  2     06        Command class: 0x06 = time sync
  3     06        Length / subtype
  4     hh        Hour
  5     mm        Minute
  6     ss        Second
  7–9   ?? ?? ??  Extra time fields (date? day-of-week?)
```

The MCU echoes back on success. **Not fully decoded:** bytes 7–9 and the exact byte
order are unverified.

### 4.4 Boot re-feed replay — **HIGH**

On boot (when `/tmp/system_start` exists) the firmware replays the most recent feed
using the same manual-feed frame as §4.1.

### 4.5 ASCII-hex channel — 24 bytes — **HIGH (exists), contents undecoded**

A separate transport: the SoC sends exactly 24 raw bytes built from a 48-character
hex string. Rodata strings nearby (`"send time:"`, `"%s app--> %s"`) suggest an
ASCII-hex time-sync and a generic app command. **Not fully decoded:** the actual
command bytes carried over this channel aren't captured.

### 4.6 Raw passthrough — variable — **LOW**

P2P case `'w'` writes an arbitrary payload straight to the UART. Likely for
GPS-equipped board variants; not exercised on `DOGNESS_PETS_V200_BREAD_DEVICE`.

---

## 5. MCU → SoC (RX)

### 5.1 Feed complete (feed result) — `cmd=0x07` / `0x15` — **HIGH**

`cmd=0x07` (normal) and `cmd=0x15` (IR food-present) are the **same 10-byte frame**;
the stock firmware routes both through one handler (`pthread_main:0xdb6c`) and reports a
*manual* feed's completion as `0x15`, so decode them together. Layout recovered from the
`ldrb` instructions and confirmed byte-for-byte against the captures below:

| Off | Bytes | Field | Meaning |
|---|---|---|---|
| 0–4 | 5 | — | diagnostic / pad (zero on a real feed) |
| **5–6** | **2 (LE)** | **`weight`** | commanded/echoed amount in MCU units = `portions × 10`; live `0a 00` = 10 = 1 portion |
| 7 | 1 | `status` | packed: `>>4` = feed_type, `& 0x0E` = slot/`mem_id`, bit0 = valid marker; live `0x21`. **Not a weight.** |
| 8 | 1 | — | pad |
| 9 | 1 | `audio_index` | echoed sound-clip index (0 = silent) |

`weight = payload[5] | (payload[6] << 8)`. **There is no load cell** — `weight` is the
commanded amount, not a measurement. `portions = weight / 10`.

> An earlier draft mapped this frame as `mem_id, feed_type, valid, weight(LE16),
> audio_index, motor_flags` and read the weight from `payload[7]`. That was wrong:
> `payload[7]` (`0x21`) is a packed status byte, and the strings that draft cited
> (`y:%d %d %d %d %d %d`, `22 recive mem id…`) are actually the clock dump and the
> outbound shm-command dump, not the feed result.

Concrete frames seen on the wire (feed-complete uses a `FF FC` SOF variant):

| Frame | Meaning |
|---|---|
| `FF FF 01 01 00` | Feed ACK (motor started) |
| `FF FC 07 0A 00 00 00 00 00 0A 00 21 00 00` | Feed complete — normal (food present) |
| `FF FC 15 0A 00 00 00 00 00 0A 00 21 00 00` | Feed complete — IR-beam / food-present sensor |
| `FF FC 05 01 04` | Feed blocked (chute jammed mid-feed) |
| `FF FF 11 01 01` | Chute blocked / invalid feed request |
| `FF FF 11 01 00` | Chute unblocked |

### 5.2 Version banner — ASCII — **HIGH (exists)**

On first contact the MCU sends `v <version>\n` (the SoC stores it to
`/tmp/micro_verson.txt` — firmware typo, "verson").

### 5.3 Time-sync ACK — **LOW**

The MCU echoes time after a sync command (firmware logs `"sync ipc time from
micro!!"`). Exact wire format **undecoded**.

### 5.4 Error frame — **LOW**

Seen on a malformed frame (length byte > 24, or framing bytes don't match).

### 5.5 Async feed error (`cmd = 0x05`) — **observed**

Unsolicited frame the MCU sends when a feed cycle fails partway, *in lieu of* a
feed-complete frame. `payload[0]` is an error code; `catd` treats it as terminal
(clears the pending feed, publishes `feed/status=error`). Observed: code `0x04` on
a low / obstructed hopper. **Not fully decoded:** whether the code distinguishes
food-low from motor-stall — one raw capture per condition would build the table.

---

## 6. Cloud → MCU command mapping (shm bridge)

On the stock firmware the cloud/Alexa bridge does **not** touch the UART; it posts
commands into a SysV shared-memory segment (`key 0xea`, six `uint32`):
`[support_flag, command_id, param1, param2, hour, min]`, where `command_id` is
1 = shoot/photo, 2 = manual feed, 3 = auto feed, 4 = PTZ move. The SoC's UART
encoder consumes that and emits the §4 frames.

| MQTT cmd | Topic | shm payload |
|---|---|---|
| `manualfeedreq` | `voice/manualfeedreq/<dev>` | `[1, 2, weight, audio_idx, 0, 0]` |
| `autofeedreq` | `voice/autofeedreq/<dev>` | `[1, 3, weight, audio_idx, HH, MM]` |
| `shootreq` | `voice/<dev>` | `[1, 1, weight, audio_idx, 0, 0]` |
| `movereq` | `voice/<dev>` | `[1, 4, direction, 0, 0, 0]` |

---

## 7. P2P → UART triggers

The stock SoC dispatches P2P commands on a single ASCII letter; only two reach the
UART: `'u'` (feed → manual-feed frame, §4.1) and `'w'` (raw passthrough, §4.6).
Everything else is internal and never touches the MCU.

---

## 8. Quick reference — wire bytes

```
TX MANUAL FEED (14B):  FF FF 01 0A 3A 09 03 0E 0B <weight> 00 00 00 0A
TX AUTO FEED   (14B):  FF FF 01 0A A5 A7 7F <hh> <mm> <cnt_lo> <cnt_hi> 11 <delay> <weight>
TX TIME SYNC   (10B):  FF FF 06 06 <hh> <mm> <ss> <??> <??> <??>      (bytes 7-9 undecoded)
RX FEED COMPLETE:      FF FC 07/15 0A  p0..p4  <wt_lo> <wt_hi>  <status>  p8  <audio_idx>
                       weight = p5 | (p6<<8)  (portions = weight/10); p7 = >>4 type, &0x0E slot
RX VERSION:            v <version>\n
RX FEED ERROR:         FF FF … cmd 0x05, payload[0] = error code
```
