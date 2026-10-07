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

The configuration partition stores the device's account password as plain `var name=value` text, unhashed, alongside a second copy of the live login pair in `login.cgi`. The Wi-Fi PSK sits in a `wpa_supplicant` config in the same partition, with a backup copy.

**Read the scope limits before using this entry.** An earlier version of this advisory listed a long inventory of cleartext credentials — eight accounts, RTSP, DDNS, PPPoE, SMTP, FTP, Wi-Fi keys. Checked against the device, almost all of those fields are empty or unchanged factory placeholders, and two of them do not exist at all. What survives is narrow, and its impact is weaker than the entry's own CVSS score suggests. See [What this actually amounts to](#what-this-actually-amounts-to).

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

Among its 104 settings:

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

Checked against the live configuration read off this device, that inventory is almost entirely hollow:

| Field | State on the device |
| --- | --- |
| `user1_name` | set, **byte-identical to the factory template** — the shipped default account name, not owner input |
| `user1_pwd` | set, and **differs** from the factory template — genuinely owner- or app-set. The one real credential here |
| `user2_*` – `user8_*` | **all empty.** Only one account exists |
| `rtsp_user`, `rtsp_pwd` | **empty.** Never configured; nothing serves RTSP on this build |
| `ddns_user`, `ddns_pwd` | **empty.** No DDNS client is started anywhere in the boot path |
| `pppoe_user`, `pppoe_pwd` | set, **byte-identical to the factory template** — placeholders, not owner data |
| `wifi_key1`–`4` | **empty.** The WEP key fields are unused; the real PSK lives in `wpa_conf` |
| SMTP / FTP credentials | **do not exist in this file.** Only `ftp_upload_interval`, a number, is present |

So the cleartext inventory is one account password plus the `login.cgi` copy of it. There is no hashing of the account passwords even though they are only ever compared, never replayed. The two authentication routines in the firmware are `checkLoginUserAndPas`, exported by `libcommon.so`, and `jiake::UserManagerment::checkUser`, exported by `libjiake_sdk.so`; neither was decompiled, so how they perform the comparison is not claimed here. What is established is that the stored side of it is the literal secret.

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

## What this actually amounts to

Three things keep this from being the finding the rest of the document implies.

**The headline impact was circular.** The previous Impact section said an attacker who reached the feeder could recover the Wi-Fi PSK and "pivot to the rest of the household network." Recovering the PSK requires being on that network already, or having the device in your hands. Gaining access to a network you are already on is not an impact.

**Storing a PSK in a `wpa_supplicant` config is normal.** That is how every Linux device on Wi-Fi works. It is not a defect of this product and should not be scored as one.

**The unused fields were never the owner's to leak.** RTSP, DDNS and the WEP key slots are empty; PPPoE holds factory placeholders; SMTP and FTP credentials are not in the file at all. They are inherited Foscam-template fields on a build with no interface to set them.

What is left is genuinely true and genuinely small: one device account password, and the login pair that duplicates it, stored unhashed in a writable flash partition, preserved across firmware updates by `conf_backup()`. The one non-circular consequence is physical: a feeder that is resold, returned or thrown away carries the previous owner's account password and Wi-Fi PSK in plaintext on a flash chip anyone can clip a SOIC-8 onto. That is worth telling an owner. It is not clearly worth a CVE, and it is not specific to this product.

**Recommendation: this entry should be withdrawn from the set** and its reserved identifier released, or demoted to a hardening note in the project README. It is retained here only until that decision is made.

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
