# DOGNESS-2026-01 — one MQTT credential compiled into every unit; cleartext broker; feed commands addressed by device ID with no per-device secret

|               |                                                                                                 |
| ------------- | ----------------------------------------------------------------------------------------------- |
| Identifier    | DOGNESS-2026-01                                                                                 |
| CVE           | requested, not yet assigned                                                                     |
| CWE           | CWE-798 (use of hard-coded credentials), CWE-319 (cleartext transmission of sensitive information), CWE-306 (missing authentication for a critical function) |
| CVSS v3.1     | **8.6 high** — `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:H/A:L`                                   |
| Status        | Published 2026-10-06. See [README.md](README.md#disclosure-statement).                          |
| Fix available | **No.** The credential is in a read-only filesystem and the infrastructure it reaches is still live. |

## Summary

`mqtt_alex`, the binary that handles cloud and Alexa voice control, authenticates to Dogness's MQTT brokers with a username and password compiled into the executable. The credential is identical in every unit running this build. The connection is plaintext MQTT on TCP 1883 — the binary links no TLS library at all. Once connected, the device subscribes to command topics named after its own device ID and acts on anything published to them, including `voice/manualfeedreq/<devid>`, which runs the feed motor.

Nothing in that exchange is per-device. There is no device certificate, no per-unit secret, no signature on a command, no nonce the device issues and checks. A client holding the fleet credential is indistinguishable from any legitimate device or app, and the only thing standing between it and someone else's feeder is broker-side topic authorization that the device neither sees nor verifies.

**The credential is redacted here.** It opens a live production broker that other owners' feeders are attached to; see [What is withheld, and why](README.md#what-is-withheld-and-why). Everything needed to recover it from the same firmware is below.

## Affected

| Brand / model                      | Firmware                                           | Binary      | MD5 of binary                      | Evidence |
| ---------------------------------- | -------------------------------------------------- | ----------- | ---------------------------------- | -------- |
| Dogness F01WH / `L8-SI` pet feeder | `PRODUCT_MODE=A06_3.81.4`, system `3.81.4.7`, rootfs built 2020-07-13 | `/usr/sbin/mqtt_alex` | `27366ac444261b4bc2f06436a6825a98` | Static analysis of the unit's own flash image, plus one live capture showing the outbound connection |

Other brands whose board profiles are compiled into the same application binaries are listed in the [set README](README.md#who-the-vendor-is). They are leads only, and this particular finding is tied to Dogness cloud infrastructure, so it is the least likely of the four to carry across.

## Description

`/etc/profile` sets `SUPPORT_ALEXA=1`, and `run_alex.sh` keeps `mqtt_alex` alive in a one-second restart loop for the life of the device. On a live unit it was running as PID 802.

**The credential.** `mqtt_alex` calls its own `mqtt_init_auth(broker, username, password)` with two string literals from `.rodata`. The username is `dogness`. The password is a ten-character ASCII literal sitting three strings later in the same region; its SHA-256 is `41c2ff15d634a524fc693c0a8ef20c07ee7c304c215c73960ea97c5ab4e23d6f`. Both are plain, unobfuscated strings — `strings /usr/sbin/mqtt_alex` prints them. The MQTT client identifier is the fixed literal `emqtt`, also shared by every unit.

**The transport.** The broker port is the immediate `0x75b` — 1883 — passed to `init_socket()` for all three primary servers and for the fallback. `mqtt_alex`'s dynamic dependencies are `libjiake_sdk.so`, `libcommon.so`, `libcrypt.so.0`, `libpthread.so.0`, `libstdc++.so.6`, `libm.so.0`, `libgcc_s.so.1`, `libc.so.0`. There is no `libssl`, no `libmbedtls`, no TLS of any kind; the only match for "ssl" in the binary is an `openssl/lib` path inside the compiled-in `RPATH`. The session, credential included, crosses the internet in the clear.

**The servers.** Three hostnames are tried in rotation, then one hardcoded IP as a fallback:

```
alxs0.dognessnetwork.com
alxs1.dognessnetwork.com
alxs2.dognessnetwork.com
119.28.64.224          <- hardcoded fallback, used when none of the hostnames resolve
```

All three hostnames and the update host still resolve as of 2026-10-06, so this is live infrastructure, not an abandoned service.

**The command plane.** After `CONNACK`, the device formats its own topic names from `getuuid()` — the same device UID used for P2P and for the setup access point's SSID — and subscribes:

```
voice/shootreq/<devid>          snapshot
voice/manualfeedreq/<devid>     dispense now
voice/autofeedreq/<devid>       write a scheduled feed
voice/movereq/<devid>           PTZ (no-op on this product)
voice/showreq/<devid>           Alexa display/status
```

replying on the matching `…resp/<devid>` topics. A manual feed request is:

```json
{"cmd":"manualfeedreq","devid":"<devid>","rand":"<caller-chosen string>","feedweight":"<portions>","feedtime":"HH:MM"}
```

and the device answers `{"cmd":"manualfeedresp","devid":"<devid>","result":"0", "rand":"<echoed>" }` — `result` `0` for success, `6` for failure. `rand` is chosen by whoever sends the command and echoed back untouched: it correlates a reply to a request, and is not a secret, a nonce the device issues, or anything the device validates. So the complete content of an authenticated-looking feed command is a device ID, an arbitrary string, a portion count and a time.

**What this means for authorization.** The device's entire claim to be itself is: it knew the fleet password, and it subscribed to a topic with its UID in the name. It performs no check on who published a command. Authorization therefore lives entirely in broker ACLs for the shared `dogness` account — an external, invisible control that the firmware does not verify, cannot observe, and does not degrade safely if it is absent or misconfigured.

## Severity, stated honestly

This advisory does **not** claim to have dispensed food into another person's feeder. Establishing that would mean connecting to Dogness's production broker, which is someone else's infrastructure, and it was not done — see [Scope and method](README.md#scope-and-method). Whether the broker restricts the shared account to per-device topics is **unknown**.

What is established, entirely from the firmware, is the design defect: a fleet-wide credential on a cleartext channel, with no per-device secret anywhere in the protocol and no check on command origin. The CVSS vector reflects that: `C:L` for the command and response stream and the device identifiers it exposes, `I:H` for actuation of the feed motor and rewriting of the feed schedule, `A:L` for the hopper being emptied into an unattended bowl. If the broker turns out to have no per-device ACL, the realistic impact is higher than 8.6 and the entry should be rescored.

Two consequences need no assumption about the broker at all:

- **Anyone on the network path sees everything.** No TLS means the credential, the device ID, every feed command and every reply are readable by anyone between the feeder and the broker — starting with anyone else on the owner's Wi-Fi.
- **An on-path attacker can inject commands.** A plaintext MQTT session can be injected into or spoofed from the LAN without the credential and without reaching the real broker. The device will accept the result.

## Proof of concept

None is published. Working code here would be a tool for commanding strangers' feeders across live third-party infrastructure.

To confirm the finding on firmware you hold:

```sh
strings usr/sbin/mqtt_alex | grep -A3 dognessnetwork      # servers, then the credential pair
printf '%s' '<the password string>' | sha256sum           # compare with the SHA-256 above
readelf -d usr/sbin/mqtt_alex | grep NEEDED               # no TLS library
```

To check your own feeder on your own network, capture its traffic and look for an outbound TCP connection to port 1883. In a capture of this unit from 2025-06-08, a `SYN` to `119.28.64.224:1883` appears — the hardcoded fallback — alongside a TUTK P2P session to `54.184.52.74:10000`. Nothing answered the 1883 `SYN` in that capture, which is the fallback IP, not the hostnames.

## Impact

Dispensing food on demand into an unattended bowl, emptying the hopper so a later scheduled feed has nothing to deliver, overwriting the feed schedule, and triggering snapshots. Overfeeding is not a cosmetic outcome for an animal, and a hopper emptied on Friday afternoon is an animal unfed until someone comes home.

Passively, the cleartext channel exposes device identifiers, feed activity and household routine to anyone on the path.

## Mitigation

**No vendor fix exists.** The credential is a string in a read-only squashfs; there is no configuration that changes it, and the owner has no credential of their own to rotate.

1. **Block the feeder's route to the internet.** This closes the finding completely: no broker reachable, no command plane. The phone app and Alexa stop working. Scheduled feeding is executed by the STC15 MCU rather than by the SoC or the cloud, so it is expected to continue — confirm that on your own unit before relying on it.
2. **Put it on its own VLAN or guest network.** The on-path variants above need only LAN adjacency, so isolating it from your other devices matters even with the internet blocked.
3. **Replace the firmware.** The OpenIPC + `catd` build in this repository removes `mqtt_alex` and the entire vendor cloud stack, and talks to a broker you run. See [`docs/INSTALL.md`](../docs/INSTALL.md).

## Credit

Found by Evan Severson (`@eseverson`) while reverse-engineering the feeder for local control.

## References

- [`docs/DEVICE_REFERENCE.md` §10 — MQTT interface (original firmware)](../docs/DEVICE_REFERENCE.md)
- [`docs/MCU_PROTOCOL.md` — what a feed command ultimately drives](../docs/MCU_PROTOCOL.md)
- [DOGNESS-2026-02](DOGNESS-2026-02-static-root-password-telnetd.md) — the local path to the same feed motor
