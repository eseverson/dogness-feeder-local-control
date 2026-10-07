# DOGNESS-2026-01 — the cloud plane is unauthenticated cleartext HTTP keyed on the device UID, with fleet-wide credentials compiled into the firmware

|               |                                                                                                 |
| ------------- | ----------------------------------------------------------------------------------------------- |
| Identifier    | DOGNESS-2026-01                                                                                 |
| CVE           | requested, not yet assigned                                                                     |
| CWE           | CWE-319 (cleartext transmission of sensitive information), CWE-798 (use of hard-coded credentials), CWE-287 (improper authentication) |
| CVSS v3.1     | **7.4 high** — `CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:N`                                   |
| Status        | Published 2026-10-06. See [README.md](README.md#disclosure-statement).                          |
| Fix available | **No.** The endpoints are in the firmware's shared libraries and the server address is provisioned at setup. |

## Summary

Everything this feeder tells its cloud, and everything the cloud tells it, goes over **plain HTTP with no authentication beyond the device's own UID in the query string**. There is no TLS anywhere in the cloud plane, no token, no signature, no per-device secret. The UID is the whole of the device's identity, and it travels in the clear on every request.

Observed live: the device issuing

```
GET /service/api/fc/server.php?cmd=feedpet&devid=<UID>&feedtype=2&feedweight=10&feedtime=<epoch> HTTP/1.1
Host: 54.184.52.74
```

to an AWS-hosted endpoint on TCP port 10000, answered `{"header":{"status":1000,"message":"success"}}`. Alarm events, online heartbeats, server registration and pairing all use the same `server.php?cmd=…&devid=<UID>` form. Snapshot images are uploaded by `curl` over the same cleartext HTTP, gated by a **hardcoded upload key, `Let*Me_Upload`, identical in every unit**.

Separately, the Alexa voice path (`mqtt_alex`) carries a second fleet-wide credential — an MQTT username and password compiled into the binary — and connects over cleartext MQTT on TCP 1883 with no TLS library linked at all. That channel is reported here as the same defect, with an important caveat: **in the capture available, it never established a session.** See [The Alexa MQTT channel](#the-alexa-mqtt-channel) for exactly what is and is not claimed about it.

## Affected

| Brand / model                      | Firmware                                     | Component                    | Channel                                              | Evidence |
| ---------------------------------- | -------------------------------------------- | ---------------------------- | ---------------------------------------------------- | -------- |
| Dogness F01WH / `L8-SI` pet feeder | `PRODUCT_MODE=A06_3.81.4`, system `3.81.4.7` | `libp2p_server.so`           | `GET /<prefix>/server.php?cmd=…&devid=<UID>` over HTTP | **Live capture** + static |
| same                               | same                                         | `libcommon.so`               | `curl -F cmd=uploadpic … uploadkey=Let*Me_Upload` over HTTP | Static |
| same                               | same                                         | `libhaisi_3518_video.so`     | `GET /<prefix>/server.php?cmd=sync&devid=…&qrcode=…` over HTTP | Static |
| same                               | same                                         | `mqtt_alex` (MD5 `27366ac444261b4bc2f06436a6825a98`) | cleartext MQTT/1883, fleet credential | Static; **no session observed live** |

Other brands whose board profiles are compiled into the same binaries are listed in the [set README](README.md#who-the-vendor-is-and-who-actually-wrote-the-firmware). The HTTP endpoint family lives in platform libraries shared across them, so it is likely to carry; the Dogness-specific parts are the hostnames and the path prefix. Untested.

## Description

### The live channel: `server.php` over HTTP, identified by UID

`libp2p_server.so` holds the request templates. Every one of them is a cleartext `GET`, and in every one the device's only claim to be itself is `devid`/`uid`:

```
GET /%s/server.php?cmd=reg_server&uid=%s
GET /%s/server.php?cmd=online&devid=%s&eventtype=%d&eventtime=%lu
GET /%s/server.php?cmd=feedpet&devid=%s&feedtype=%d&feedweight=%d&feedtime=%lu
GET /%s/server.php?cmd=raisealarm&devid=%s&eventtype=%d&eventtime=%lu&eventpicn=%s&sn=%s
GET /%s/server.php?cmd=raisealarm&devid=%s&eventtype=%d&feedweight=%d&eventtime=%lu
GET /tpns?cmd=device&uid=%s
GET /tpns?cmd=event&uid=%s&event_type=%d&event_time=%lu
```

`libhaisi_3518_video.so` adds the pairing call, which carries the setup QR code in the clear:

```
GET /%s/server.php?cmd=sync&devid=%s&qrcode=%s&product=%s
```

The host, port and path prefix are not compiled in — they are provisioned into the writable configuration partition at setup. On the unit examined, `/mnt/config/server_info.cgi` contains the address `54.184.52.74` and the prefix `service/api/fc`, which is exactly what the capture shows. That address belongs to **Amazon Technologies Inc.**; port 10000.

There is no `Authorization` header, no signature parameter, no nonce, and no TLS on any of these. The `User-Agent` is a spoofed desktop Chrome string, which is worth mentioning only because it shows the channel was built to look like a browser rather than to be secured like an API.

### The hardcoded upload key

Snapshot upload is shelled out to `curl` from `libcommon.so`:

```
curl -F "cmd=uploadpic" -F "devid=%s" -F "uploadkey=Let*Me_Upload" -F "userfile=@/%s/%s" --connect-timeout 10 -m 15 "http://%s:%d/%s/server.php"
```

`Let*Me_Upload` is a string literal. It is the same in every unit, it cannot be changed by an owner, and it is the only thing besides the UID gating image upload into the vendor's media store. A second variant posts to `/DOOR_Server/server.php` with the same key. The same library also carries a hardcoded **Baidu Maps API key** used for IP geolocation, and a log/image upload endpoint at `BJ_UploadTest/uploadLogFileForCamera.do` — both cleartext HTTP, both fleet-wide.

### The Alexa MQTT channel

`mqtt_alex` is kept alive in a one-second restart loop by `run_alex.sh` for the life of the device; `SUPPORT_ALEXA=1`. It calls its own `mqtt_init_auth()` with two plaintext literals from `.rodata`: username `dogness`, and a ten-character password whose SHA-256 is `41c2ff15d634a524fc693c0a8ef20c07ee7c304c215c73960ea97c5ab4e23d6f`. The MQTT client identifier is the fixed literal `emqtt`. Its dependency list — `libjiake_sdk.so`, `libcommon.so`, `libcrypt.so.0`, `libpthread.so.0`, `libstdc++.so.6`, `libm.so.0`, `libgcc_s.so.1`, `libc.so.0` — contains no TLS library; the only `ssl` match in the binary is a path inside the compiled-in `RPATH`. The port is the immediate `0x75b`, 1883. It tries `alxs0`, `alxs1`, `alxs2.dognessnetwork.com` in rotation, then the hardcoded address `119.28.64.224`. On connection it subscribes to `voice/{shoot,manualfeed,autofeed,move,show}req/<devid>` and acts on anything published there; a feed command is `{"cmd":"manualfeedreq","devid":"…","rand":"…","feedweight":"…","feedtime":"HH:MM"}`, where `rand` is chosen by the sender and echoed back unvalidated.

**What was observed, and what that implies.** In the 2025-06-08 capture the only MQTT activity is a single unanswered `SYN` to `119.28.64.224:1883` — the hardcoded fallback, which the code reaches only after all three hostnames fail to resolve. No DNS query for any `alxs*` name appears in the capture, and nothing answered. The working cloud paths in that same window were the `server.php` HTTP API above and TUTK P2P (UDP 10001 to Tencent-hosted masters; the `alxs*` names resolve to one of those same addresses today). So:

- The hardcoded fleet credential and the absence of TLS are **facts about shipped firmware**, verifiable from any copy of it, and are reported as such.
- Whether a broker is still serving on 1883, and whether it would accept that credential, is **not established**. The `alxs*` names resolving today proves only that the names resolve; the one observation available suggests the Alexa MQTT backend was unreachable from this device at the time of the capture.

## Severity, stated honestly

No vendor infrastructure was tested — see [Scope and method](README.md#scope-and-method) — so nothing here claims to have read or forged another owner's data.

What the firmware establishes on its own is that the device's entire cloud identity is a UID sent in cleartext, that its feed and alarm history and its uploaded snapshots cross the internet unencrypted, and that the only secret in the upload path is a string every unit shares. The consequences that follow without any assumption about the server:

- **An on-path observer** — anyone on the owner's Wi-Fi, a compromised router, an upstream network — learns the UID, reads the full feed and alarm history as it happens, and sees the snapshot uploads. Household routine, in other words, plus images from inside the home.
- **An on-path attacker can rewrite the device's reports and responses.** Plain HTTP on a known port with no integrity protection is trivially injectable, in either direction.
- **Anyone who learns a UID holds the device's whole credential** for the HTTP plane. Server-side authorization is the only thing left, and the firmware neither verifies it nor degrades safely without it.

`AC:H` reflects that the strongest consequences need a network position the attacker does not get for free. The weaker, credential-free variant — issuing `server.php?cmd=…&devid=<UID>` from anywhere once a UID is known — needs no position at all, and its impact depends entirely on untested server-side checks; if those turn out to be absent, this entry should be rescored upward.

## Proof of concept

None is published. For the HTTP plane a demonstration would mean sending requests to the vendor's live API on behalf of a device identifier, which is the harm being reported. For the MQTT channel it would mean connecting to third-party production infrastructure with an extracted credential.

The finding is verifiable by reading the firmware. From an extracted rootfs:

```sh
strings lib/libp2p_server.so | grep 'server\.php\|/tpns?'
strings lib/libcommon.so     | grep 'uploadkey\|uploadpic'
strings lib/libhaisi_3518_video.so | grep 'cmd=sync'
cat mnt/config/server_info.cgi          # the provisioned host + path prefix
strings usr/sbin/mqtt_alex | grep -A3 dognessnetwork
readelf -d usr/sbin/mqtt_alex | grep NEEDED   # no TLS library
```

To observe it on your own feeder on your own network, capture its traffic and read the HTTP on port 10000 directly — it is plaintext, which is the point.

## Impact

Disclosure of the device UID, the feed and alarm history, pairing material and uploaded snapshot images to anyone on the network path, continuously and without any credential. Forgery of those same reports by an on-path attacker. A fleet-wide upload key that cannot be rotated. And, latent in the firmware, a command channel that will accept feed instructions from whoever can publish to a topic named after a UID, should that backend be reachable.

For a device whose output is food, forged or suppressed feed reports are not only a privacy matter: an owner reading "fed at 17:00" has no way to tell the difference between a feed that happened and a report that was injected.

## Mitigation

**No vendor fix exists.** The endpoints are in shared libraries inside a read-only filesystem; the upload key is a string literal; the cloud address is provisioned, not configurable by the owner in any security-relevant way.

1. **Block the feeder's route to the internet.** This closes the whole advisory: no cloud plane, nothing in cleartext leaving the house. The app, Alexa and remote viewing stop working. Scheduled feeding is executed by the STC15 MCU rather than the application SoC, so it is expected to continue — confirm it on your own unit before relying on it.
2. **Put it on an isolated VLAN or guest network.** Every consequence above that needs no server-side assumption needs only network adjacency, so isolating the feeder from your other devices matters even with the internet blocked.
3. **Treat the UID as a secret the device does not keep.** Do not post it, and do not share screenshots of the app's device page.
4. **Replace the firmware.** The OpenIPC + `catd` build in this repository removes `mqtt_alex`, the `server.php` client and the P2P stack, and talks only to a broker you run. See [`docs/INSTALL.md`](../docs/INSTALL.md).

## Scope — why several channels, one entry

The `server.php` HTTP API, the `curl` upload path, the pairing call and the MQTT client are reported as one finding because they are one defect with one remediation: the cloud plane is unencrypted and authenticated by non-secrets, and nothing short of removing it fixes any of them. If MITRE prefers to split this into separate identifiers — plausibly cleartext transport, the hardcoded upload key, and the MQTT credential — that is a reasonable outcome and the advisory is written so the pieces separate cleanly.

## Credit

Found by Evan Severson (`@eseverson`) while reverse-engineering the feeder for local control.

## References

- [`docs/DEVICE_REFERENCE.md` §10 — MQTT interface (original firmware)](../docs/DEVICE_REFERENCE.md)
- [`docs/MCU_PROTOCOL.md` §6 — how a cloud command reaches the motor](../docs/MCU_PROTOCOL.md)
- [DOGNESS-2026-03](DOGNESS-2026-03-unsigned-update-over-cleartext-http.md) — the other cleartext HTTP channel, the one that writes flash
