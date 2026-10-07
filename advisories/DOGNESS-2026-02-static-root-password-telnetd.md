# DOGNESS-2026-02 — telnetd started unconditionally at boot with a static root password in a read-only filesystem

|               |                                                                                                 |
| ------------- | ----------------------------------------------------------------------------------------------- |
| Identifier    | DOGNESS-2026-02                                                                                 |
| CVE           | requested, not yet assigned                                                                     |
| CWE           | CWE-798 (use of hard-coded credentials), CWE-1392 (use of default credentials), CWE-912 (hidden functionality) |
| CVSS v3.1     | **9.8 critical** — `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H`                                |
| Status        | Published 2026-10-06. See [README.md](README.md#disclosure-statement).                          |
| Fix available | **No.** The daemon has no off switch and the password cannot be changed persistently.           |

## Summary

`/etc/profile` starts a BusyBox `telnetd` on port 23 on every boot, unconditionally, with no setting that disables it and nothing in the product's documentation or app that mentions it exists. It authenticates against a `root` password stored as a traditional DES-crypt hash in `/etc/shadow` inside the read-only squashfs rootfs. The password is **`059AnkJ`**.

That password is not Dogness's, and this is not a new discovery about it: the identical credential has already been assigned CVEs on two sibling pet feeders built on the same platform, and the exact `/etc/shadow` line is published. What is reported here is that this product ships it too. See [Prior art](#prior-art) before scoring or citing this entry.

Every unit running this build shares the password, nothing about it derives from the unit, and an owner cannot change it — `/etc/shadow` lives in a read-only filesystem, so any edit reverts at the next power cycle.

The result is a permanent root shell, reachable from anywhere on the network, behind a password that is public.

## Affected

| Brand / model                      | Firmware                                   | Service              | Root hash                  | Algorithm   | Password  |
| ---------------------------------- | ------------------------------------------ | -------------------- | -------------------------- | ----------- | --------- |
| Dogness F01WH / `L8-SI` pet feeder | `PRODUCT_MODE=A06_3.81.4`, system `3.81.4.7` | `telnetd`, TCP 23, always on | `FCb/N1tGGXtP6` (in `/etc/shadow`) | DES crypt, salt `FC` | `059AnkJ` |

The same credential appears in numerous unrelated HiSilicon OEM camera firmwares, which is why it is published here rather than withheld. The seven other pet-feeder board profiles compiled into these binaries ([README](README.md#who-the-vendor-is-and-who-actually-wrote-the-firmware)) share the platform that carries this defect, so it is the finding in this set most likely to apply to them — untested.

## Prior art

This is the weakest claim to novelty in the set, and the honest framing matters more than the finding.

| Reference | Product | What it covers |
| --- | --- | --- |
| [CVE-2021-37555](https://www.cve.org/CVERecord?id=CVE-2021-37555) | Trixie TX9 Automatic Food Dispenser v3.2.57 | Root shell over telnet on port 23 using **the default root password `059AnkJ`** — the same string, named in the CVE description |
| [CVE-2019-16734](https://www.cve.org/CVERecord?id=CVE-2019-16734) | Petwant PF-103 firmware 4.3.2.50, Petalk AI 3.2.2.30 | Default credentials on the telnet server allowing remote root command execution; research by [ISE](https://blog.securityevaluators.com/remotely-exploiting-iot-pet-feeders-21013562aea3) |
| [HiSilicon IP camera root passwords](https://gist.github.com/gabonator/74cdd6ab4f733ff047356198c781f27d) | numerous OEM cameras | The credential circulating publicly, including the byte-identical shadow line `root:FCb/N1tGGXtP6:10957:0:99999:7:::` documented against Fredi and HeimVision cameras |

**`PETWANT_PETS_V200_BOARD` is one of the board profiles compiled into this firmware's own binaries** (see the [set README](README.md#the-platform-vendor)). CVE-2019-16734 is therefore not a coincidental neighbour — it is the same ODM platform, reported six years earlier on a different brand's feeder.

**What is new here:** that the Dogness F01WH / `L8-SI` on firmware `A06_3.81.4` is affected, which no existing record states. Nothing else.

**What is not new:** the credential, the hash, the DES-crypt weakness, the always-on daemon, and the general pattern. Anyone scoring or triaging this should expect it to be treated as another instance of an already-documented platform defect rather than a discovery, and a CNA may reasonably decline a separate identifier on that basis.

## Description

The boot path is three lines of shell. `/etc/profile` runs once per boot, guarded by a `/tmp/test_run` sentinel, and inside that block:

```sh
    #telnetd
    /sbin/telnetd &
```

There is no conditional, no environment flag, no configuration file consulted. The commented-out `#telnetd` above it is a label, not a disabled alternative. By the time the application stack starts, the daemon is listening.

Authentication is ordinary BusyBox login against `/etc/shadow`:

```
root:FCb/N1tGGXtP6:10957:0:99999:7:::
```

Thirteen characters, no `$` prefix: traditional DES crypt, salt `FC`. It reproduces exactly:

```sh
$ perl -e 'print crypt("059AnkJ","FC"), "\n"'
FCb/N1tGGXtP6
```

The algorithm is worth stating separately from the password, because it matters even for builds whose password is not published. DES crypt truncates the password at eight characters and has a 12-bit salt; a hash in this form falls to brute force on one consumer GPU in seconds. Any DES-crypt root hash recovered from a firmware image of this family should be treated as already public, whatever the password turns out to be.

`/etc/passwd`, `/etc/shadow` and `/etc/profile` are all inside `mtd2`, the squashfs rootfs, mounted read-only. `/mnt/config` (`mtd4`, JFFS2) is the only writable partition, and nothing in the boot path overlays or re-reads account files from it. So `passwd` at a root shell changes the running copy and nothing more: the next reboot restores `FCb/N1tGGXtP6`.

The platform does carry a notion of a hardened telnet — `ShellCommon.conf` has a `G_SAFETELNET` flag that, when `yes`, routes file reads through a `cat_jk` wrapper instead of `cat`. On this build it is set to `no`. Either way the flag concerns how scripts read files; it does not gate the daemon.

Serial console access is equivalent and worth noting for completeness: UART0 on the board gives a 115200 8N1 login prompt against the same `/etc/shadow`, so the same credential also works with physical access and no network at all.

## Proof of concept

```sh
telnet <feeder-ip>
# login: root
# password: 059AnkJ
```

The session lands at a root shell on the camera SoC. From there, `/dev/ttyAMA2` is the UART to the STC15 feed MCU, and a 14-byte frame runs the motor — the protocol is documented in [`docs/MCU_PROTOCOL.md`](../docs/MCU_PROTOCOL.md).

Run this only against a device you own.

## How to tell whether you are affected

If `telnet <feeder-ip>` presents a login prompt, the daemon is running; this build always runs it. The firmware version is visible in the vendor app, and `/usr/ipcam/bak/get_status.cgi` reports `sys_ver="3.81.4.7"` on the build analyzed here.

## Impact

Full root on the device, from anywhere the device is reachable, with a password that is public. Concretely that is: the live camera and microphone; the Wi-Fi PSK and every other credential the owner entered, in cleartext ([DOGNESS-2026-04](DOGNESS-2026-04-cleartext-credential-storage.md)); direct control of the feed motor over the MCU UART, bypassing every portion limit and lockout the app enforces; and a persistent foothold on the owner's network, on a device nobody inspects, that cannot be patched.

## Mitigation

**No vendor fix exists**, and no owner action on the device removes the daemon or changes the password durably.

1. **Network isolation is the only control.** The feeder needs to reach your broker or app and nothing else; it should not be reachable from your general LAN, and it should not be reachable from the internet under any circumstances. If anything has forwarded a port to it, remove that first.
2. **Changing the app or camera password does nothing here.** This credential is not the app's.
3. **Replace the firmware.** The OpenIPC build in this repository has no telnet daemon, and you set the root credential and SSH key at build time. See [`docs/INSTALL.md`](../docs/INSTALL.md).

Note, with the irony acknowledged, that the no-soldering installation path in this repository uses this vulnerability to get a shell and flash the replacement. It is the one constructive use available for it.

## Credit

Found by Evan Severson (`@eseverson`) on this product. The `059AnkJ` credential itself is prior work by others — see [Prior art](#prior-art). What is reported here is only that this product and firmware version ship it on an always-on, undocumented, owner-unchangeable remote shell.

## References

- [`docs/DEVICE_REFERENCE.md` §1 — network access](../docs/DEVICE_REFERENCE.md)
- [`docs/INSTALL.md`](../docs/INSTALL.md) — the telnet flashing path
- [DOGNESS-2026-04](DOGNESS-2026-04-cleartext-credential-storage.md) — what a shell hands you
