# Dogness `L8-SI` / F01WH pet-feeder camera — advisory set

Four defects in the **original (vendor) firmware** of the Dogness pet-feeder camera this project replaces. The device is a camera with a food-dispensing motor attached, so the consequences are not only the usual ones: a defect that lets a stranger actuate the feeder is a defect that lets a stranger empty a pet's hopper, or keep dispensing into a bowl nobody is watching.

**Published 2026-10-06.** CVE assignment is being requested from MITRE as CNA of last resort. Identifiers appear in the table below as they are issued.

These findings concern the **stock firmware only** (`PRODUCT_MODE=A06_3.81.4`, system `3.81.4.7`, UI `3.1.1.6`, rootfs built 2020-07-13). They do **not** apply to the OpenIPC + `catd` build this repository produces, which removes the entire vendor application stack — no telnet daemon with a shipped password, no cloud broker, no unauthenticated update fetch.

## Who the vendor is, and who actually wrote the firmware

**Dogness supplies the brand and the cloud. It did not write this firmware.** That distinction runs through the whole set, so it is worth establishing before the findings.

### The brand

The box, the app and the cloud are Dogness: `h5cn`, `manager`, `manager2` and `alxs0`–`alxs2.dognessnetwork.com`. Dogness-specific content amounts to the cloud hostnames, the API path prefix provisioned at setup, the MQTT credential, and the `DOGNESS_01_` access-point name. Everything else is platform code.

### The platform vendor

The application stack is the work of a Guangzhou camera ODM that signs its code "jiake" at every level: the C++ namespace is `jiake::` (`jiake::UserManagerment::checkUser`, `jiake::AudioBuffer`, `jiake::device_info`), the shared libraries are `libjiake_sdk.so`, `libjiake_audio.so`, `libjiake_protocol.so`, `libjiake_sound.so` and `libjiake_video.so`, every build path is rooted at `/opt/jiake/arm_3518_v200` (with a build tree at `/media/linux_bak/ipc_040/ipcamera_project`), `/etc/profile` sets `company=guangzhou_jiake`, helper tooling is named `cat_jk`, Wi-Fi state variables are prefixed `JK_HZ_`, and the factory DDNS account in the read-only rootfs points at `user.jiake.info`.

**The firmware update server belongs to that ODM, not to Dogness.** `ipcam.sh` forces an update check against the hardcoded address `112.124.112.116` at every boot, and `upgrade_online.sh` and `libp2p_server.so` carry `http://112.124.112.116/IMG_Server/images/` as the fallback image path. That address is what **`aaipc.cn`** resolves to. So the one host every one of these devices contacts unauthenticated at boot ([DOGNESS-2026-03](DOGNESS-2026-03-unsigned-update-over-cleartext-http.md)) is the platform vendor's, sitting underneath whatever brand is on the box.

**No corporate identity is asserted here.** `aaipc.cn` is registered to an individual rather than a company, and no business registration, trading name or security contact was found for "Guangzhou Jiake" in any form. The evidence establishes that one ODM wrote this stack and distributes its firmware; it does not establish a legal entity to name, and this advisory set does not guess at one or publish the registrant's personal details.

The platform is built to be rebranded and re-targeted. `ShellCommon.conf` selects between `arm-haisi`, `mipsel-ralink`, `arm-anyka` and `arm-grain` — four unrelated SoC families from one source tree — and the same binaries carry board profiles for seven other pet feeders: `HANWEI_PETS_V200_BOARD`, `LIUBINGHUA_PETS_V200_BOARD` (the one this unit selects), `MEIKE_PETS_V200_BOARD`, `MEIKE_SMART_PETS_V200_BOARD`, `PETFUN_PLAYDOG_V200_BOARD`, `PETWANT_PETS_V200_BOARD` and `RUIYI_PET_V200_BOARD`. Those are **leads, not confirmations**: only the Dogness unit was tested. The telnet and update findings are platform defects and are the ones most likely to carry across; the cloud findings are partly Dogness-specific.

### Two components that are somebody else's again

* **The CGI dialect is the Foscam IP-camera CGI API**, inherited rather than invented. `get_params.cgi` with `user1_name` through `user8_pwd`, `loginuse`/`loginpas`, `camera_control.cgi`, `decoder_control.cgi`, `snapshot.cgi`, `set_media.cgi` — this is the interface a large family of Foscam clones has shared for over a decade, and it has its own long CVE history (for example CVE-2013-2574, CVE-2014-1911, CVE-2016-8731 against Foscam itself). Where a finding here touches that surface, the advisory says so and does not claim novelty.

* **P2P is ThroughTek Kalay**: `libIOTCAPIs.so`, `libAVAPIs.so`, `libP2PTunnelAPIs.so` and `libRDTAPIs.so`, with masters at `us-c/d-master-tutk.iotcplatform.com`, the `eu-` equivalents, and `cn-c/d-master-tutk.kalay.net.cn`. In the capture this is the live video path.

## The set

| Advisory                                                                  | Subject                                                                                                                                                                                | CVSS v3.1 | CVE       |
| ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | --------- |
| [DOGNESS-2026-01](DOGNESS-2026-01-cleartext-cloud-plane.md)               | Cloud plane is plain HTTP authenticated by the device UID alone; snapshot upload gated by a fleet-wide hardcoded key; Alexa MQTT channel carries a second fleet credential with no TLS | **7.4**   | requested |
| [DOGNESS-2026-02](DOGNESS-2026-02-static-root-password-telnetd.md)        | `telnetd` started unconditionally at boot; static root password in a read-only filesystem                                                                                              | **9.8**   | requested |
| [DOGNESS-2026-03](DOGNESS-2026-03-unsigned-update-over-cleartext-http.md) | Firmware and a root-executed helper script fetched over cleartext HTTP with no signature; runs automatically at every boot                                                             | **8.1**   | requested |
| [DOGNESS-2026-04](DOGNESS-2026-04-cleartext-credential-storage.md)        | Every credential the owner enters — web, RTSP, DDNS, SMTP, FTP, Wi-Fi PSK — stored in cleartext on the device                                                                          | **6.5**   | requested |

## If you own one of these feeders

A feeder is not a camera you can unplug. Guidance that ends in "disconnect the device" ends in an unfed animal, so take these in order.

1. **Put it on a segmented network with no route to the internet.** That closes DOGNESS-2026-01 and DOGNESS-2026-03 outright, because both depend on the device reaching vendor infrastructure. You lose the phone app and Alexa. You should **not** lose scheduled feeding: the schedule is held and executed by the STC15 MCU, not by the SoC or the cloud (see [`docs/MCU_PROTOCOL.md`](../docs/MCU_PROTOCOL.md)). Verify that on your own unit — set a slot, pull its internet access, and watch the next feed — before you rely on it.
2. **Assume anything on the same LAN owns the device.** DOGNESS-2026-02 is a published root password on an always-on telnet daemon. Segmentation has to be from your own network too, not just from the internet.
3. **Changing the camera or app password does not help.** The root password is in a read-only filesystem, and the cloud credential is not yours to change.
4. **There is no firmware update that fixes this.** The update mechanism is itself DOGNESS-2026-03, and we have no evidence of a build that addresses any of the four.
5. **Replacing the firmware is the only real fix.** That is what the rest of this repository is: OpenIPC plus `catd`, feeding over MQTT on your own broker, with Home Assistant discovery. Start at [`docs/INSTALL.md`](../docs/INSTALL.md). Note the irony that the no-soldering installation path uses DOGNESS-2026-02 to get in.

## Disclosure statement

All four findings rest on static analysis of a flash image read off a unit the researcher owns, plus one passive network capture of that unit on the researcher's own network.

## What is withheld, and why

**The MQTT credential in DOGNESS-2026-01 is redacted.** Whether a broker still answers on that port is not established, but if one does, the password opens production infrastructure that other people's feeders connect to, and the advisory's own argument is that the broker may not isolate clients from each other. The advisory gives the username, the hostnames, the port, the topic grammar, the binary and its MD5, and a SHA-256 of the password, so anyone holding the same firmware can recover it in one command and confirm the finding exactly.

**The `uploadkey` in DOGNESS-2026-01 is published**, because it is not a password to anything: it gates an upload endpoint that already accepts any UID over plain HTTP, the string is the same in every unit, and withholding it would make the finding unverifiable while protecting nothing.

**The Baidu Maps API key and the factory DDNS account are not published.** They are credentials to third parties who have no part in this, and neither is needed to understand or verify the findings.

**The root password in DOGNESS-2026-02 is published in full.** It is generic across a large family of HiSilicon OEM camera firmware, is already in public writeups and gists, is on-device only, and this repository's own installation instructions need it.

**No device UID or TUTK identifier appears anywhere in this set.** The device ID is the addressing key for the MQTT command topics; publishing a real one would name a specific target.

**There is no proof-of-concept code in this set.** For DOGNESS-2026-02 none is needed — it is a telnet login. For DOGNESS-2026-01, working code would be a tool for commanding other people's feeders over live third-party infrastructure, and there is no version of that which is responsible to ship.

## Scope and method

All work was done against a **single feeder owned by the researcher**, on the researcher's own network. No device belonging to anyone else was touched.

**No vendor infrastructure was tested.** No connection was made to the cloud API, to the MQTT brokers, or to the update server. Hostnames were resolved by DNS only, which establishes that names still resolve and **nothing more** — not that anything is listening, and not that a credential would be accepted. Where a finding's real-world impact depends on server-side behavior, the advisory says so in its own severity section instead of assuming the worst.

Evidence is of three kinds, and each advisory says which it is using:

* **Static analysis** of the 8 MiB flash image dumped from the unit with a CH341A (`d2.bin`, MD5 `503c695f1555245fa8562106c95fb257`): the squashfs rootfs, the squashfs UI partition, and the JFFS2 config partition, plus the vendor binaries in them.

* **One live network capture** of the unit on the researcher's LAN, 2025-06-08. It is the only direct evidence of what the device actually talks to: the working cloud channels in that window were plain HTTP to an AWS-hosted endpoint on TCP 10000 and ThroughTek P2P over UDP, while the MQTT connection attempt went unanswered. No device UID from that capture appears anywhere in this set.

* **Live execution**, for the telnet login and the MCU protocol work, performed before the unit was reflashed.

The feeder now runs OpenIPC, so nothing here can be re-tested live. Every claim is either recorded in the project's working notes or re-derivable from the retained flash image.

## Not claimed here

Three surfaces were found and are **not** being reported as vulnerabilities, because the work to establish them was not done. They are listed so that whoever has one of these running knows where to look.

* **`udpServerSys` and `device_discover`.** Two UDP services the stock firmware starts at boot (`ipcam.sh`, `wifi_stat_ctrl.sh`). `device_discover` imports `recvfrom`, `system`, `popen`, `set_ipaddr`, `set_netmask`, `setWifiConfFile`, `getuuid` **and** `userAuthCheck` — a network-reachable path that can rewrite the device's IP and Wi-Fi configuration and shell out, with some authentication check present. What that check covers was not determined, and the listening ports were never captured. This is the most likely place for a fifth finding.

* **The TUTK / ThroughTek P2P stack** (`G_P2P_TYPE=tutk`, `libp2p_server.so`). In the capture the device exchanges UDP/10001 traffic with three Tencent-hosted masters and then streams video to the phone over UDP/14301, so this is the live media and remote-viewing path. The ThroughTek SDK has its own well-known CVE history; the SDK version in this build was not identified and the protocol was not analyzed, so nothing is claimed. Note that the TCP/10000 session to an AWS address in the same capture is **not** TUTK — it is the plaintext `server.php` API covered by [DOGNESS-2026-01](DOGNESS-2026-01-cleartext-cloud-plane.md).

* **The web / CGI surface, which is present but may never be reachable.** There is **no HTTP server binary anywhere in the rootfs** — no `httpd`, `thttpd`, `boa`, `lighttpd` or `goahead` — which settles it for a standalone server. A process listing captured from a running unit shows no web server either, though that listing was taken with the device booted outside its normal init sequence, so it corroborates rather than proves. The `.htm` pages in the `ui` partition and the two ELF programs in `/usr/sbin/cgi-bin` are vestigial remains of an arrangement this build no longer uses; `ipcaminit.sh` goes as far as mounting an empty tmpfs over `/mnt/ui/cgi-bin/`, which would mask anything placed there. What does exist is an HTTP handler **inside `IPServer` itself**: it calls `bind`, `listen` and `accept`, emits `HTTP/1.0 200 OK`, `HTTP/1.0 400 Missing session cookie` and `HTTP/1.0 400 Unknown session cookie`, and carries a `/*/cgi-bin/*` route pattern over roughly twenty endpoints (`set_wifi.cgi`, `set_ddns.cgi`, `set_mail.cgi`, `set_upgrade_online.cgi`, `camera_control.cgi`, `decoder_control.cgi` and so on). Whether that handler binds a port reachable on the LAN, or only serves requests arriving through the ThroughTek P2P tunnel, **was not determined** — no port scan of the unit was captured before it was reflashed, and the one network capture available contains no inbound connections to it. Account checking for it lives in `jiake::UserManagerment::checkUser`, so a session mechanism exists; how completely it covers those routes is likewise untested. This is the largest unexamined surface on the device, and the second-most likely place for a further finding after the UDP services above.

* **`/mnt/config/exec_extern.sh`**, copied out of the rootfs and then `chmod +x`'d and executed at every boot from the writable JFFS2 partition. A persistence foothold for anyone who already has a shell, not an entry point on its own.

## License

This advisory set is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Credit `@eseverson`.
