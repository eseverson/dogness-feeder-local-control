# Dogness `L8-SI` / F01WH pet-feeder camera — advisory set

Four defects in the **original (vendor) firmware** of the Dogness pet-feeder camera this project replaces. The device is a camera with a food-dispensing motor attached, so the consequences are not only the usual ones: a defect that lets a stranger actuate the feeder is a defect that lets a stranger empty a pet's hopper, or keep dispensing into a bowl nobody is watching.

**Published 2026-10-06.** CVE assignment is being requested from MITRE as CNA of last resort. Identifiers appear in the table below as they are issued.

These findings concern the **stock firmware only** (`PRODUCT_MODE=A06_3.81.4`, system `3.81.4.7`, UI `3.1.1.6`, rootfs built 2020-07-13). They do **not** apply to the OpenIPC + `catd` build this repository produces, which removes the entire vendor application stack — no telnet daemon with a shipped password, no cloud broker, no unauthenticated update fetch.

## Who the vendor is

The box, the app and the cloud infrastructure are **Dogness**. The firmware is not Dogness-authored: every build path compiled into the binaries carries `/opt/jiake/arm_3518_v200` and `/media/linux_bak/ipc_040/ipcamera_project`, the rootfs sets `company=guangzhou_jiake` and `VENDOR=IPCAME`, and the application stack is the Guangzhou Jiake / IPCAME Hi3518 camera platform with a pet-feeder board profile bolted on. The cloud side is Dogness's own: `alxs0`–`alxs2.dognessnetwork.com` for the MQTT control plane, `h5cn.dognessnetwork.com:8090` for firmware images.

The same binaries contain board profiles for seven other pet-feeder products — `HANWEI_PETS_V200_BOARD`, `LIUBINGHUA_PETS_V200_BOARD` (the one this unit selects), `MEIKE_PETS_V200_BOARD`, `MEIKE_SMART_PETS_V200_BOARD`, `PETFUN_PLAYDOG_V200_BOARD`, `PETWANT_PETS_V200_BOARD`, `RUIYI_PET_V200_BOARD`. Those are **leads, not confirmations**: only the Dogness unit was tested, and the cloud-side findings are specific to Dogness infrastructure. The telnet and update findings are platform defects and are the ones most likely to carry across.

## The set

| Advisory | Subject | CVSS v3.1 | CVE |
| --- | --- | --- | --- |
| [DOGNESS-2026-01](DOGNESS-2026-01-fleet-wide-mqtt-credential.md) | One MQTT credential compiled into every unit; cleartext broker; feed commands addressed by device ID with no per-device secret | **8.6** | requested |
| [DOGNESS-2026-02](DOGNESS-2026-02-static-root-password-telnetd.md) | `telnetd` started unconditionally at boot; static root password in a read-only filesystem | **9.8** | requested |
| [DOGNESS-2026-03](DOGNESS-2026-03-unsigned-update-over-cleartext-http.md) | Firmware and a root-executed helper script fetched over cleartext HTTP with no signature; runs automatically at every boot | **8.1** | requested |
| [DOGNESS-2026-04](DOGNESS-2026-04-cleartext-credential-storage.md) | Every credential the owner enters — web, RTSP, DDNS, SMTP, FTP, Wi-Fi PSK — stored in cleartext on the device | **6.5** | requested |

## If you own one of these feeders

A feeder is not a camera you can unplug. Guidance that ends in "disconnect the device" ends in an unfed animal, so take these in order.

1. **Put it on a segmented network with no route to the internet.** That closes DOGNESS-2026-01 and DOGNESS-2026-03 outright, because both depend on the device reaching vendor infrastructure. You lose the phone app and Alexa. You should **not** lose scheduled feeding: the schedule is held and executed by the STC15 MCU, not by the SoC or the cloud (see [`docs/MCU_PROTOCOL.md`](../docs/MCU_PROTOCOL.md)). Verify that on your own unit — set a slot, pull its internet access, and watch the next feed — before you rely on it.
2. **Assume anything on the same LAN owns the device.** DOGNESS-2026-02 is a published root password on an always-on telnet daemon. Segmentation has to be from your own network too, not just from the internet.
3. **Changing the camera or app password does not help.** The root password is in a read-only filesystem, and the cloud credential is not yours to change.
4. **There is no firmware update that fixes this.** The update mechanism is itself DOGNESS-2026-03, and we have no evidence of a build that addresses any of the four.
5. **Replacing the firmware is the only real fix.** That is what the rest of this repository is: OpenIPC plus `catd`, feeding over MQTT on your own broker, with Home Assistant discovery. Start at [`docs/INSTALL.md`](../docs/INSTALL.md). Note the irony that the no-soldering installation path uses DOGNESS-2026-02 to get in.

## Disclosure statement

> **Decision point before publishing — fill this in.** Unlike a no-name AliExpress camera, Dogness is an identifiable company with a corporate web presence and live cloud infrastructure, so "there is nobody to report this to" is not available as a reason here. Either record a vendor-contact attempt and its outcome in this section, or record the decision not to contact and why. Do not publish this set with this box still in it.

The vendor was contacted on `<date>` at `<address>`; outcome: `<outcome>`.

All four findings rest on static analysis of a flash image read off a unit the researcher owns, plus one passive network capture of that unit on the researcher's own network.

## What is withheld, and why

**The MQTT credential in DOGNESS-2026-01 is redacted.** It is a working password to a live production broker that other people's feeders are connected to right now, and the advisory's own argument is that the broker may not isolate clients from each other. Publishing it would hand out access to strangers' devices, which is the harm the advisory is reporting, not a demonstration of it. The advisory gives the username, the hostnames, the port, the topic grammar, the binary and its MD5, and a SHA-256 of the password, so anyone holding the same firmware can recover it in one command and confirm the finding exactly.

**The root password in DOGNESS-2026-02 is published in full.** It is generic across a large family of HiSilicon OEM camera firmware, is already in public writeups and gists, is on-device only, and this repository's own installation instructions need it.

**No device UID or TUTK identifier appears anywhere in this set.** The device ID is the addressing key for the MQTT command topics; publishing a real one would name a specific target.

**There is no proof-of-concept code in this set.** For DOGNESS-2026-02 none is needed — it is a telnet login. For DOGNESS-2026-01, working code would be a tool for commanding other people's feeders over live third-party infrastructure, and there is no version of that which is responsible to ship.

## Scope and method

All work was done against a **single feeder owned by the researcher**, on the researcher's own network. No device belonging to anyone else was touched.

**No vendor infrastructure was tested.** No connection was made to `alxs*.dognessnetwork.com`, to the broker IP, or to the update server. Hostnames were resolved by DNS only, to establish that the infrastructure still exists (it does, as of 2026-10-06). The consequence is stated plainly where it matters: whether the production broker restricts the shared account to per-device topics is **unknown and untested**, and DOGNESS-2026-01 says so in its own severity discussion rather than assuming the worst.

Evidence is of three kinds, and each advisory says which it is using:

- **Static analysis** of the 8 MiB flash image dumped from the unit with a CH341A (`d2.bin`, MD5 `503c695f1555245fa8562106c95fb257`): the squashfs rootfs, the squashfs UI partition, and the JFFS2 config partition, plus the vendor binaries in them.
- **One live network capture** of the unit on the researcher's LAN, 2025-06-08.
- **Live execution**, for the telnet login and the MCU protocol work, performed before the unit was reflashed.

The feeder now runs OpenIPC, so nothing here can be re-tested live. Every claim is either recorded in the project's working notes or re-derivable from the retained flash image.

## Not claimed here

Three surfaces were found and are **not** being reported as vulnerabilities, because the work to establish them was not done. They are listed so that whoever has one of these running knows where to look.

- **`udpServerSys` and `device_discover`.** Two UDP services the stock firmware starts at boot (`ipcam.sh`, `wifi_stat_ctrl.sh`). `device_discover` imports `recvfrom`, `system`, `popen`, `set_ipaddr`, `set_netmask`, `setWifiConfFile`, `getuuid` **and** `userAuthCheck` — a network-reachable path that can rewrite the device's IP and Wi-Fi configuration and shell out, with some authentication check present. What that check covers was not determined, and the listening ports were never captured. This is the most likely place for a fifth finding.
- **The TUTK / ThroughTek P2P stack** (`G_P2P_TYPE=tutk`; the capture shows an outbound session to `54.184.52.74:10000`). The ThroughTek SDK has its own well-known CVE history. The SDK version in this build was not identified, so nothing is claimed.
- **`/mnt/config/exec_extern.sh`**, copied out of the rootfs and then `chmod +x`'d and executed at every boot from the writable JFFS2 partition. A persistence foothold for anyone who already has a shell, not an entry point on its own.

## License

This advisory set is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Credit `@eseverson`.
