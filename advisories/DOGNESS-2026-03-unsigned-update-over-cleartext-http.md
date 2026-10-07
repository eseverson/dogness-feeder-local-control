# DOGNESS-2026-03 — firmware and a root-executed helper script fetched over cleartext HTTP with no signature, automatically at every boot

|               |                                                                                                 |
| ------------- | ----------------------------------------------------------------------------------------------- |
| Identifier    | DOGNESS-2026-03                                                                                 |
| CVE           | requested, not yet assigned                                                                     |
| CWE           | CWE-494 (download of code without integrity check), CWE-319 (cleartext transmission), CWE-345 (insufficient verification of data authenticity) |
| CVSS v3.1     | **8.1 high** — `CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H`                                   |
| Status        | Published 2026-10-06. See [README.md](README.md#disclosure-statement).                          |
| Fix available | **No.** The update path is itself the defect; there is no mechanism by which a corrected one could arrive safely. |

## Summary

The device updates itself over plain HTTP, verified by an MD5 checksum downloaded from the same unauthenticated URL as the image it is supposed to vouch for. Nothing is signed. No key is pinned. No certificate is involved, because there is no TLS.

The same code path also fetches a shell script named `sdcard.sh` over that HTTP connection, marks it executable and runs it as root, with **no integrity check of any kind** — not even the MD5 the firmware image gets.

Both run unattended. `ipcam.sh` invokes `upgrade_online_force` against a hardcoded IP address at every boot, and `IPServer` carries an `auto_upgrade_online_thread` plus a `COMMAND_TYPE_UPGRADE_ONLINE_AUTO` handler. No owner action is required, and none is possible to withhold.

Anyone who can answer for the update host — on-path on the owner's network, upstream, or by DNS — owns the device persistently at its next boot.

## Affected

| Brand / model                      | Firmware                                     | Components                                                                   | Evidence |
| ---------------------------------- | -------------------------------------------- | ---------------------------------------------------------------------------- | -------- |
| Dogness F01WH / `L8-SI` pet feeder | `PRODUCT_MODE=A06_3.81.4`, system `3.81.4.7` | `/usr/sbin/upgrade_online.sh`, `/usr/sbin/upgrade.sh`, `/usr/sbin/upgrade_online_force`, `/usr/sbin/ipcam.sh`, `IPServer` | Static analysis of the unit's flash image |

The update machinery is platform code rather than product code, so of the four findings this is, with [DOGNESS-2026-02](DOGNESS-2026-02-static-root-password-telnetd.md), the most likely to carry to the other board profiles in the same binaries — untested.

## Description

### Where the image comes from

`upgrade_online.sh` builds its base URL in `get_server_addr()`:

```sh
server_addrs="http://h5cn.dognessnetwork.com:8090/IMG_Server/images/"
...
wget -t 3 -T 30 -P /tmp $server_addrs/server_list.txt
server_temp=`$CAT_PRO $server_list_file | grep $company | awk -F'=' '{print $2}'`
server_addrs="http://${server_temp}/IMG_Server/images/"
```

So the *server list itself* is fetched over cleartext HTTP and then used to choose where firmware comes from: an attacker who can answer one HTTP request redirects every subsequent one. A hardcoded fallback `http://112.124.112.116/IMG_Server/images/` exists, and `/mnt/config/server_addr.cgi`, on the writable partition, overrides the base URL entirely if present.

`h5cn.dognessnetwork.com` still resolves as of 2026-10-06. Whether it still serves images was not tested; the hardcoded fallback address is tried regardless of whether it does.

### What verification happens

```sh
download_sys_files()
{
	wget -P $download_dir ${server_addrs}/${platform}/${PRODUCT_MODE}/${sys_system_file}
	wget -P $download_dir ${server_addrs}/${platform}/${PRODUCT_MODE}/${sys_md5file}
}

check_sys_md5()
{
    local device_sys_md5=`md5sum $download_dir/${sys_system_file} | awk -F ' ' '{print $1}'`
    local server_sys_md5=`$CAT_PRO $download_dir/${sys_md5file}`
    if [ "$device_sys_md5" = "${server_sys_md5}"  ] ; then
     return 0;
    fi
     return 1;
}
```

`system.tar` and `md5sum_sys.txt` come down the same cleartext channel, from the same host, back to back. Whoever controls one controls the other, so the comparison proves only that the transfer was not corrupted in flight. It is a transport integrity check presented where an authenticity check belongs. There is no signature, no public key anywhere in the image, and MD5's collision weakness is beside the point — the attacker simply supplies the matching digest.

On success the script hands the tarball to the application over a FIFO, which runs `upgrade.sh`:

```sh
send_fifo /tmp/my_fifo 1000 $upgrade_type $download_dir/${sys_system_file}
```

`upgrade.sh` untars it and writes the members straight to flash with `flashcp`, by partition number: `uImage` to `/dev/mtd1` (kernel), `sys.img` to `/dev/mtd2` (rootfs) and, if the archive contains it, `uboot-v200.bin` to `/dev/mtd0` — **the bootloader**. An unsigned archive from a cleartext HTTP fetch can therefore replace every stage of the boot chain, not just the kernel and root filesystem. A `check_tar_flag()` helper compares version strings from the archive against the running build; it is a downgrade/ordering check, not an authenticity one. Failure of the MD5 comparison leads to `sleep 120; reboot`, so a hostile server that gets the digest wrong merely puts the feeder into a reboot loop.

### The unchecked script

In the same file:

```sh
get_server_sdcard_exec()
{
	local server_sdcard=sdcard.sh
	wget -P $download_dir ${server_addrs}/${platform}/${PRODUCT_MODE}/$server_sdcard
	if [ -e /tmp/sdcard.sh ] ; then
		chmod +x /tmp/sdcard.sh
		/tmp/sdcard.sh
	fi
	rm /tmp/sdcard.sh -rf
}
```

Downloaded over HTTP, made executable, executed as root. No MD5, no version check, no signature. This is the shortest path in the whole firmware from "answer an HTTP request" to "arbitrary code as root", and it is reached when `upgrade_type` is neither `sys` nor `ui`. A near-identical block in `ipcaminit.sh` runs `/mnt/config/record/sdcard.sh` from the SD card at boot on the same terms.

### When it runs

`ipcam.sh`, started on the normal boot path, line 24:

```sh
$run_dir/upgrade_online_force 112.124.112.116
```

An update check against a hardcoded IP, forced, every boot. `IPServer` additionally exports `auto_upgrade_online_thread` and logs `recive COMMAND_TYPE_UPGRADE_ONLINE_AUTO command!`, so the cloud can trigger the same path at will — and [DOGNESS-2026-01](DOGNESS-2026-01-cleartext-cloud-plane.md) is about how little it takes to speak to that cloud plane.

For fairness: the platform does contain an authenticated upgrade path — `/usr/sbin/cgi-bin/upgrade_firmware.cgi` calls `checkLoginUserAndPas` before `setUpgradeFirmware`. It is dead code in this build, since no HTTP server exists to execute it, and either way it does not constrain the unattended route above, which reaches the same `flashcp` with no gate at all.

## Proof of concept

Not published. A working demonstration is a hostile update server plus a redirection primitive, which together are an implant builder for a device whose owners cannot patch it.

The finding is verifiable by reading the firmware. From an extracted rootfs:

```sh
grep -n 'server_addrs=\|wget\|md5sum\|chmod +x\|flashcp' usr/sbin/upgrade_online.sh usr/sbin/upgrade.sh
sed -n '24p' usr/sbin/ipcam.sh
strings usr/sbin/IPServer | grep -i upgrade_online
```

To see whether your own feeder is doing this, watch its traffic at boot for outbound HTTP to port 8090 or to `112.124.112.116`.

## Impact

Persistent arbitrary code execution as root, surviving reboots, written into flash. An attacker in a position to answer for the update host — the owner's own LAN, a compromised router, an upstream network, or DNS for `dognessnetwork.com` — can replace kernel and rootfs with their own, or more cheaply have `sdcard.sh` run anything they like as root. Because the check is forced at every boot, the attacker does not need to wait for anything or persuade anyone to click.

`AC:H` in the vector reflects that the attacker must hold a network position they do not get for free. Everything after that position is unconditional.

## Mitigation

1. **Block the feeder from reaching the internet.** No update host reachable, no update path. This is the same control that closes DOGNESS-2026-01, and it is the only one that works.
2. **If you cannot isolate it, make sure nothing on the path is hostile**, which is not a control you can verify. Treat it as unmitigated.
3. **Replace the firmware.** The OpenIPC build in this repository has no auto-update client; updates are something you push over SSH with [`scripts/flash.py`](../scripts/flash.py).

## Credit

Found by Evan Severson (`@eseverson`).

## References

- [`docs/DEVICE_REFERENCE.md` §9 — FIFO command codes, including `1000` (firmware upgrade)](../docs/DEVICE_REFERENCE.md)
- [DOGNESS-2026-01](DOGNESS-2026-01-cleartext-cloud-plane.md) — who can trigger the auto-update path remotely
