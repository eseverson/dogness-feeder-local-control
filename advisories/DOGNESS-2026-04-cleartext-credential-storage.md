# DOGNESS-2026-04 — every credential the owner enters is stored in cleartext on the device, and survives firmware upgrades

|               |                                                                                                 |
| ------------- | ----------------------------------------------------------------------------------------------- |
| Identifier    | DOGNESS-2026-04                                                                                 |
| CVE           | requested, not yet assigned                                                                     |
| CWE           | CWE-256 (plaintext storage of a password), CWE-522 (insufficiently protected credentials), CWE-798 (use of hard-coded credentials, for the factory DDNS account) |
| CVSS v3.1     | **6.5 medium** — `CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N`                                 |
| Status        | Published 2026-10-06. See [README.md](README.md#disclosure-statement).                          |
| Fix available | **No.**                                                                                         |

## Summary

The configuration partition stores every secret the owner ever typed into the product as plain `var name=value` text: all eight stored device account passwords, the RTSP password, the DDNS password, the PPPoE password, the Wi-Fi keys, and the live login pair in a separate file. The owner's Wi-Fi PSK is additionally in a `wpa_supplicant` config in the same partition, as is a backup copy of it. Nothing is hashed and nothing is encrypted.

On its own this is a storage defect that needs a shell first. It does not stay on its own, because [DOGNESS-2026-02](DOGNESS-2026-02-static-root-password-telnetd.md) hands any network-adjacent party that shell behind a published password. The combination turns a pet feeder into a cleartext credential store for the household network, reachable over telnet.

The upgrade script deliberately preserves these files across firmware updates, so the exposure is designed to persist.

## Affected

| Brand / model                      | Firmware                                     | Location                                       | Contents |
| ---------------------------------- | -------------------------------------------- | ---------------------------------------------- | -------- |
| Dogness F01WH / `L8-SI` pet feeder | `PRODUCT_MODE=A06_3.81.4`, system `3.81.4.7` | `/mnt/config` (`mtd4`, JFFS2, writable)         | `get_params.cgi`, `login.cgi`, `wpa_conf`, `wpa_conf_bak` |
| same                               | same                                         | `/usr/ipcam/bak` (`mtd2`, squashfs, read-only)  | `get_status.cgi` — factory DDNS account, identical on every unit |

Evidence is the content of those files as read from the unit's own flash image. No values from the researcher's unit are reproduced here.

## Description

### The configuration file

`/mnt/config/get_params.cgi` is a flat list of JavaScript assignments. The `.cgi` extension is misleading and worth clearing up first: on this build nothing serves it over HTTP — there is no web server binary in the rootfs at all — and the file is simply the platform's configuration format, read and written in-process by `IPServer`. The name and the field layout are inherited from the Foscam IP-camera CGI API, where `get_params.cgi` genuinely was an HTTP endpoint; see [Who actually wrote the firmware](README.md#two-components-that-are-somebody-elses-again). What is reported here is the storage, not a web endpoint.

Among roughly two hundred settings:

```
var user1_name=…   var user1_pwd=…   var user1_pri=…
…
var user8_name=…   var user8_pwd=…   var user8_pri=…
var rtsp_auth_enable=…  var rtsp_user=…   var rtsp_pwd=…
var pppoe_user=…        var pppoe_pwd=…
var ddns_user=…         var ddns_pwd=…
var wifi_key1=…  var wifi_key2=…  var wifi_key3=…  var wifi_key4=…
var alarm_http_url=…
```

with SMTP and FTP upload credentials further down the same file. Every one of them is the literal secret. There is no hashing of the account passwords even though they are only ever compared, never replayed — `libcommon.so`'s `checkLoginUserAndPas` and `jiake::UserManagerment::checkUser` compare against these cleartext values directly.

`/mnt/config/login.cgi` holds the current session's pair on its own:

```
var loginuser=…
var loginpass=…
var pri=…
```

### The Wi-Fi PSK

`/mnt/config/wpa_conf` is an ordinary `wpa_supplicant` configuration, so the `psk` line is the owner's network key. `wpa_conf_bak` is a second copy. `wifi_key1`–`4` in `get_params.cgi` are a third place the same class of secret appears. Removing one does not remove the others.

### The factory DDNS account

`/usr/ipcam/bak/get_status.cgi`, inside the read-only rootfs, is the factory template the device starts from. It ships with a populated DDNS account for `user.jiake.info` — username and password both present as literals, dated 2012 in the template's own timestamp field. Because it is in the read-only image, it is identical in every unit of this build, which makes it a hard-coded vendor credential rather than an owner's secret. The account is not published here; it is third-party infrastructure. `jiake.info` no longer resolves, so the account most likely leads nowhere now — which lowers the practical weight of this sub-finding without changing what the firmware does, since a shipped cleartext credential for a dead service is still a shipped cleartext credential.

### Why upgrades do not clear it

`upgrade.sh` explicitly carries the configuration across a firmware update:

```sh
conf_backup()
{
	mkdir -p $UPGRADE_TMP_DIR
	filepath=${CONF_DIR}/*.cgi
	cp -rf $filepath $UPGRADE_TMP_DIR
	…
}
```

`conf_restore()` moves them back afterwards. `conf_delete()` removes a specific short list — `login.cgi`, `get_status.cgi`, `get_log.cgi`, `.htpasswd` and a few flags — on a factory reset path, but `get_params.cgi` with all eight account passwords and the Wi-Fi keys is in the preserved set, not the deleted one.

## Proof of concept

Not applicable as an exploit; this is a read of the device's own filesystem. With a shell on the device, from [DOGNESS-2026-02](DOGNESS-2026-02-static-root-password-telnetd.md) or any other route:

```sh
cat /mnt/config/get_params.cgi | grep -i 'pwd\|key\|user'
cat /mnt/config/login.cgi
cat /mnt/config/wpa_conf
```

Equivalently, from a flash image read off the chip with a CH341A and unpacked, the same files are in the JFFS2 partition. That second route is worth noting on its own: a feeder sold secondhand, returned, or thrown away still carries the previous owner's Wi-Fi key in plaintext on a chip anyone can clip onto.

## Impact

Disclosure of the owner's Wi-Fi PSK, giving an attacker who reached only the feeder a way onto the rest of the household network; disclosure of up to eight stored device account credentials, which owners commonly reuse; disclosure of RTSP, DDNS, SMTP and FTP credentials, the last two often belonging to a real mailbox or server elsewhere.

`PR:L` in the vector reflects that a shell or login is needed first. That prerequisite costs nothing on this device, which is why this entry matters more than its score suggests: score it on its own merits, read it alongside DOGNESS-2026-02.

## Mitigation

1. **Do not reuse credentials on this device.** Give the app and the camera accounts passwords used nowhere else, and assume the Wi-Fi PSK it holds is compromised.
2. **Put the feeder on a segregated SSID with its own PSK**, so the key it stores in cleartext is not the key to your main network.
3. **Erase the configuration partition before the device leaves your hands.** From a root shell, `flash_eraseall -j /dev/mtd4` clears `/mnt/config`. Verify afterwards, and note it will re-provision from scratch.
4. **Replace the firmware.** The OpenIPC build in this repository keeps Wi-Fi configuration in the image you build, and `catd` has no account store, no DDNS client and no SMTP client to store credentials for. The Wi-Fi PSK is still a PSK in a config file — that is `wpa_supplicant` everywhere — so item 2 remains good advice either way.

## Credit

Found by Evan Severson (`@eseverson`).

## References

- [`docs/DEVICE_REFERENCE.md` §18 — key file paths](../docs/DEVICE_REFERENCE.md)
- [DOGNESS-2026-02](DOGNESS-2026-02-static-root-password-telnetd.md) — how an attacker gets the shell this finding needs
