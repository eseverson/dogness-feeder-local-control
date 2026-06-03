#!/usr/bin/env python3
"""Flash OpenIPC firmware partitions over SSH.

Subcommands
-----------

  flash.py uboot      Flash u-boot to mtd0. Highest-risk write (failure
                      bricks the device until UART recovery), so requires
                      explicit y confirmation.
  flash.py main       Flash kernel + rootfs together. Detached + auto-
                      reboot — the running rootfs disappears mid-flash so
                      SSH dies anyway.
  flash.py rootfs     Flash rootfs only. (Detached + auto-reboot.)
  flash.py kernel     Flash kernel only. (Detached + auto-reboot.)
  flash.py recovery   Flash recovery to mtd4. Requires the 32MB layout
                      (mtd4 named "recovery"). Doesn't disturb the running
                      system, no reboot.

All paths default to artifacts in $PWD (matching `build.py all` output).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _common import (
    SSHTarget,
    confirm,
    die,
    fetch_mtd_map,
    info,
    parse_proc_mtd,
    require_mtd,
    warn,
)


DEFAULT_DEVICE = "192.168.1.135"
DEFAULT_USER = "root"


# Image filename defaults — match build.py output.
DEF_UBOOT    = "u-boot-hi3518ev200-by25q256.bin"
DEF_KERNEL   = "uImage.hi3518ev200"
DEF_ROOTFS   = "rootfs.squashfs.hi3518ev200"
DEF_RECOVERY = "uImage.hi3518ev200.recovery"


# ── Common helpers ───────────────────────────────────────────────────────


def make_target(args: argparse.Namespace) -> SSHTarget:
    return SSHTarget(host=args.device, user=args.user)


def resolve_path(arg: Path | None, default_name: str) -> Path:
    p = arg or (Path.cwd() / default_name)
    if not p.is_file():
        die(f"image not found: {p}")
    return p


def stage_flash_tools(target: SSHTarget) -> None:
    """Copy flashcp/flash_eraseall into /tmp so they survive a rootfs erase."""
    target.ssh(
        "cp /usr/sbin/flashcp /tmp/flashcp && "
        "cp /usr/sbin/flash_eraseall /tmp/flash_eraseall"
    )


def check_tmpfs_room(target: SSHTarget, total_bytes: int) -> None:
    out = target.ssh_capture("df /tmp")
    # Skip header row; values are in 1K blocks.
    last_line = out.strip().splitlines()[-1].split()
    free_kb = int(last_line[3])
    need_kb = (total_bytes + 1023) // 1024
    if need_kb > free_kb:
        die(f"images ({need_kb} KB) exceed /tmp free space ({free_kb} KB)")


# ── uboot ────────────────────────────────────────────────────────────────


def cmd_uboot(args: argparse.Namespace) -> int:
    target = make_target(args)
    img = resolve_path(args.image, DEF_UBOOT)

    info("verifying MTD layout on device")
    parts = fetch_mtd_map(target)
    boot = require_mtd(parts, 0, "boot")

    img_kb = img.stat().st_size // 1024
    if img_kb < 50 or img_kb > 300:
        die(
            f"u-boot size {img_kb} KB is outside expected 50-300 KB range — "
            f"refusing to flash. Verify {img} is actually a u-boot binary."
        )
    if img_kb > boot.size_kb:
        die(f"u-boot ({img_kb} KB) exceeds boot partition ({boot.size_kb} KB)")

    print(f"=== u-boot flash via SSH ===")
    print(f"target:  {args.device}")
    print(f"binary:  {img} ({img_kb} KB) → mtd0/boot ({boot.size_kb} KB)")
    print()
    if not confirm("Flash u-boot? Failure here bricks the device until UART recovery."):
        info("aborted")
        return 1

    stage_flash_tools(target)
    target.transfer_with_md5(img, "/tmp/u-boot.bin", "uboot")

    info("flashing /dev/mtd0 (DO NOT POWER OFF)")
    target.ssh("/tmp/flash_eraseall /dev/mtd0 && /tmp/flashcp -v /tmp/u-boot.bin /dev/mtd0")

    print()
    info("u-boot flashed. Running system unaffected — old u-boot stays in")
    info("memory until reboot. To activate the new u-boot:")
    info(f"  ssh {args.user}@{args.device} reboot")
    info("then connect UART at the new u-boot's compile-time baudrate (921600).")
    return 0


# ── main / rootfs / kernel (detached + reboot) ──────────────────────────


def _flash_main_partitions(
    *,
    target: SSHTarget,
    rootfs: Path | None,
    kernel: Path | None,
) -> int:
    info("verifying MTD layout on device")
    parts = fetch_mtd_map(target)

    flashes = []  # list of (label, src_path, mtd_index, tmp_remote_path)
    total_bytes = 0
    print()
    print(f"=== flash via SSH ===")
    print(f"target: {target.host}")

    if kernel:
        kp = require_mtd(parts, 2, "kernel")
        sz_kb = kernel.stat().st_size // 1024
        if sz_kb > kp.size_kb:
            die(f"kernel ({sz_kb} KB) exceeds partition ({kp.size_kb} KB)")
        print(f"  kernel:   {kernel} ({sz_kb} KB) → mtd2 ({kp.size_kb} KB)")
        flashes.append(("kernel", kernel, 2, "/tmp/kernel.img"))
        total_bytes += kernel.stat().st_size

    if rootfs:
        rp = require_mtd(parts, 3, "rootfs")
        sz_kb = rootfs.stat().st_size // 1024
        if sz_kb > rp.size_kb:
            die(f"rootfs ({sz_kb} KB) exceeds partition ({rp.size_kb} KB)")
        print(f"  rootfs:   {rootfs} ({sz_kb} KB) → mtd3 ({rp.size_kb} KB)")
        flashes.append(("rootfs", rootfs, 3, "/tmp/rootfs.img"))
        total_bytes += rootfs.stat().st_size
    print()

    check_tmpfs_room(target, total_bytes)
    stage_flash_tools(target)

    # Transfer + verify everything BEFORE we erase any partition.
    for label, src, _, remote in flashes:
        target.transfer_with_md5(src, remote, label)

    # Build flash sequence. Order: kernel first, rootfs last.
    # Once we erase mtd3 (rootfs), dropbear can no longer page in libs from
    # squashfs and SSH dies. So we run the whole sequence detached under
    # nohup; it runs to reboot regardless of the SSH client.
    flashes_ordered = sorted(flashes, key=lambda f: 0 if f[0] == "kernel" else 1)
    cmds = []
    for label, _, idx, remote in flashes_ordered:
        cmds.append(f"/tmp/flash_eraseall /dev/mtd{idx}")
        cmds.append(f"/tmp/flashcp -v {remote} /dev/mtd{idx}")
    cmds.append("reboot")

    sequence = " && ".join(cmds[:-1]) + "; " + cmds[-1]
    info("flashing (DO NOT POWER OFF) — detached, will reboot when done")
    target.ssh(
        f"nohup sh -c {sequence!r} >/tmp/flash.log 2>&1 </dev/null &",
    )
    info(f"flash dispatched. Wait ~60s then: ssh {target.user}@{target.host}")
    return 0


def cmd_main(args: argparse.Namespace) -> int:
    target = make_target(args)
    return _flash_main_partitions(
        target=target,
        rootfs=resolve_path(args.rootfs, DEF_ROOTFS),
        kernel=resolve_path(args.kernel, DEF_KERNEL),
    )


def cmd_rootfs(args: argparse.Namespace) -> int:
    target = make_target(args)
    return _flash_main_partitions(
        target=target,
        rootfs=resolve_path(args.image, DEF_ROOTFS),
        kernel=None,
    )


def cmd_kernel(args: argparse.Namespace) -> int:
    target = make_target(args)
    return _flash_main_partitions(
        target=target,
        rootfs=None,
        kernel=resolve_path(args.image, DEF_KERNEL),
    )


# ── recovery (foreground, no reboot, layout-aware) ──────────────────────


def cmd_recovery(args: argparse.Namespace) -> int:
    target = make_target(args)
    img = resolve_path(args.image, DEF_RECOVERY)

    info("verifying MTD layout on device")
    parts = fetch_mtd_map(target)
    # Requires the 32MB layout (mtd4 named "recovery"). Trying to write
    # recovery onto a "rootfs_data" partition (old layout) was tested once
    # and broke the boot — don't try it again.
    mtd4 = require_mtd(parts, 4, "recovery")

    img_kb = img.stat().st_size // 1024
    if img_kb > mtd4.size_kb:
        die(f"recovery ({img_kb} KB) exceeds mtd4 partition ({mtd4.size_kb} KB)")

    print()
    print(f"=== recovery flash via SSH ===")
    print(f"target:   {target.host}")
    print(f"image:    {img} ({img_kb} KB) → mtd4/recovery ({mtd4.size_kb} KB)")
    print()

    stage_flash_tools(target)
    target.transfer_with_md5(img, "/tmp/recovery.img", "recovery")

    info("flashing /dev/mtd4 (DO NOT POWER OFF)")
    target.ssh("/tmp/flash_eraseall /dev/mtd4 && /tmp/flashcp -v /tmp/recovery.img /dev/mtd4")

    print()
    info("recovery flashed. Running system unaffected — no reboot needed.")
    print(
        "  To test: from U-Boot, `run bootcmdrec` (with the patched u-boot's\n"
        f"  defaults), or `fw_setenv bootcmd 'run bootcmdrec'; reboot` from main."
    )
    return 0


# ── argparse ─────────────────────────────────────────────────────────────


def _add_device_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--device", default=DEFAULT_DEVICE,
        help=f"target IP or hostname (default: {DEFAULT_DEVICE})",
    )
    p.add_argument(
        "--user", default=DEFAULT_USER,
        help=f"ssh user (default: {DEFAULT_USER})",
    )


def main() -> int:
    p = argparse.ArgumentParser(
        prog="flash.py",
        description="Flash OpenIPC partitions over SSH.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="SUBCOMMAND")

    # uboot
    pu = sub.add_parser("uboot", help="Flash patched u-boot to mtd0 (high-risk).")
    pu.add_argument("image", type=Path, nargs="?", default=None,
                    help=f"u-boot binary (default: $PWD/{DEF_UBOOT})")
    _add_device_args(pu)
    pu.set_defaults(func=cmd_uboot)

    # main (rootfs + kernel together)
    pm = sub.add_parser("main", help="Flash rootfs + kernel together (auto-reboot).")
    pm.add_argument("--rootfs", type=Path, default=None,
                    help=f"rootfs image (default: $PWD/{DEF_ROOTFS})")
    pm.add_argument("--kernel", type=Path, default=None,
                    help=f"kernel uImage (default: $PWD/{DEF_KERNEL})")
    _add_device_args(pm)
    pm.set_defaults(func=cmd_main)

    # rootfs only
    pr = sub.add_parser("rootfs", help="Flash rootfs only (auto-reboot).")
    pr.add_argument("image", type=Path, nargs="?", default=None,
                    help=f"rootfs image (default: $PWD/{DEF_ROOTFS})")
    _add_device_args(pr)
    pr.set_defaults(func=cmd_rootfs)

    # kernel only
    pk = sub.add_parser("kernel", help="Flash kernel only (auto-reboot).")
    pk.add_argument("image", type=Path, nargs="?", default=None,
                    help=f"kernel uImage (default: $PWD/{DEF_KERNEL})")
    _add_device_args(pk)
    pk.set_defaults(func=cmd_kernel)

    # recovery
    prc = sub.add_parser(
        "recovery",
        help="Flash recovery to mtd4 (no reboot; detects old layout).",
    )
    prc.add_argument("image", type=Path, nargs="?", default=None,
                     help=f"recovery uImage (default: $PWD/{DEF_RECOVERY})")
    _add_device_args(prc)
    prc.set_defaults(func=cmd_recovery)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
