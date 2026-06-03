#!/usr/bin/env python3
"""Build the OpenIPC firmware artifacts for the hi3518ev200 Dogness target.

Subcommands
-----------

  build.py uboot      Build the patched U-Boot binary (with BY25Q256 +
                      921600 baud + 32MB layout defaults).
  build.py main       Build main firmware (uImage + squashfs rootfs).
  build.py recovery   Build recovery firmware (kernel with embedded
                      initramfs that brings up wifi + sshd).
  build.py full       Assemble a flashable full image (8MB or 32MB layout).
  build.py all        Run uboot + main + recovery (in parallel if asked)
                      and assemble the 32MB full image. This is the
                      one-shot you want for a clean rebuild.

All artifacts land in the cwd unless --out-dir is given. Build-tree caches
(buildroot downloads, ccache) live under ~/.cache/openipc/ and are reused
across subcommand invocations and parallel builds.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from _common import (
    FIRMWARE_DIR,
    UBOOT_TREE,
    check_size,
    die,
    info,
    run,
    warn,
)


# ── Paths and defaults ───────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "openipc"
DL_CACHE = CACHE_DIR / "dl"
CCACHE = CACHE_DIR / "ccache"

DEFAULT_TOOLCHAIN = (
    Path.home() / "Downloads" / "hisi-linux" / "x86-arm" / "arm-hisiv300-linux"
)
SOC = "hi3518ev200"

DEFCONFIG_MAIN = (
    FIRMWARE_DIR / "br-ext-chip-hisilicon" / "configs" / "hi3518ev200_ultimate_defconfig"
)
DEFCONFIG_RECOVERY = (
    FIRMWARE_DIR / "br-ext-chip-hisilicon" / "configs" / "hi3518ev200_recovery_defconfig"
)


# ── U-Boot build ─────────────────────────────────────────────────────────


def ensure_lzma_wrapper() -> None:
    """U-Boot needs `lzma` on PATH. On Fedora it's xz-lzma-compat; if the
    binary isn't present, drop a wrapper at ~/.local/bin/lzma that calls
    xz --format=lzma."""
    if shutil.which("lzma") is not None:
        return
    wrapper = Path.home() / ".local" / "bin" / "lzma"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("#!/bin/sh\nexec /usr/bin/xz --format=lzma \"$@\"\n")
    wrapper.chmod(0o755)
    info(f"installed lzma wrapper at {wrapper}")


def build_uboot(out: Path, toolchain: Path) -> Path:
    """Build the patched U-Boot, write the final binary to `out`. Returns out."""
    if not UBOOT_TREE.is_dir():
        die(f"U-Boot tree not found at {UBOOT_TREE}")
    gcc = toolchain / "bin" / f"arm-hisiv300-linux-uclibcgnueabi-gcc"
    if not gcc.is_file():
        die(
            f"hisiv300 toolchain not found at {toolchain}\n"
            "  download from your Hi3518 SDK distributor and untar to that path,\n"
            "  or pass --toolchain /path/to/arm-hisiv300-linux"
        )

    ensure_lzma_wrapper()

    env = os.environ.copy()
    env["PATH"] = f"{toolchain / 'bin'}:{Path.home() / '.local/bin'}:{env['PATH']}"
    env["ARCH"] = "arm"
    env["CROSS_COMPILE"] = "arm-hisiv300-linux-uclibcgnueabi-"

    # Targeted clean — never `make distclean` here; it nukes reg_info_*.bin.
    info("cleaning previous U-Boot artifacts")
    cleanup = [
        "u-boot", "u-boot.bin", "u-boot.srec", "u-boot.map", "mini-boot.bin",
        f"drivers/mtd/spi/hifmc100/hifmc_spi_nor_ids.o",
        f"drivers/mtd/spi/hifmc100/libhifmcv100.a",
        "drivers/serial/serial_pl01x.o", "drivers/serial/libserial.a",
        "arch/arm/lib/board.o", "arch/arm/lib/libarm.a",
        f"arch/arm/cpu/{SOC}/compressed/image_data.lzma",
        f"arch/arm/cpu/{SOC}/compressed/image_data.o",
        f"arch/arm/cpu/{SOC}/compressed/mini-boot.bin",
        f"arch/arm/cpu/{SOC}/compressed/mini-boot.elf",
    ]
    for f in cleanup:
        (UBOOT_TREE / f).unlink(missing_ok=True)

    # Restore reg_info_*.bin from git if a prior distclean removed them.
    for name in (f"reg_info_{SOC}.bin", "reg_info_hi3516cv200.bin", "reg_info_hi3518ev201.bin"):
        if not (UBOOT_TREE / name).is_file():
            cp = subprocess.run(
                ["git", "ls-files", "--error-unmatch", name],
                cwd=UBOOT_TREE, capture_output=True,
            )
            if cp.returncode == 0:
                run(["git", "checkout", "--", name], cwd=UBOOT_TREE, env=env)

    info(f"configuring U-Boot for {SOC}")
    run(["make", f"{SOC}_config"], cwd=UBOOT_TREE, env=env, capture=True)
    shutil.copy(UBOOT_TREE / f"reg_info_{SOC}.bin", UBOOT_TREE / ".reg")

    # bootss2.a comes prebuilt per (CROSS_COMPILE, SOC). Patch 0005 wires up
    # the uclibcgnueabi variant — we just need to copy if the canonical name
    # doesn't exist yet.
    bootss2 = UBOOT_TREE / "common" / "bootss2.a"
    fallback = UBOOT_TREE / "common" / f"cmd_bootss2_v300_{SOC}"
    if not bootss2.is_file() and fallback.is_file():
        shutil.copy(fallback, bootss2)

    info("building u-boot.bin")
    run(["make", f"-j{os.cpu_count() or 1}"], cwd=UBOOT_TREE, env=env)

    info("wrapping into mini-boot.bin")
    run(["make", "mini-boot.bin"], cwd=UBOOT_TREE, env=env)

    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(UBOOT_TREE / "mini-boot.bin", out)
    size = out.stat().st_size
    info(f"wrote {out} ({size} bytes)")
    if size > 0x50000:
        warn(f"{size} > 0x50000 — won't fit in standard 320KB boot partition")
    return out


def cmd_uboot(args: argparse.Namespace) -> int:
    out = args.out or (Path.cwd() / f"u-boot-{SOC}-by25q256.bin")
    build_uboot(out, args.toolchain)
    return 0


# ── Buildroot firmware (main / recovery) ────────────────────────────────


def build_firmware(*, board: str, target_subdir: str, jobs: int) -> Path:
    """Run the OpenIPC Makefile for a single board. Returns its output dir."""
    if not FIRMWARE_DIR.is_dir():
        die(f"firmware tree not found at {FIRMWARE_DIR}")

    # No -j on the OUTER make: OpenIPC's `all: build repack timer` lists no
    # ordering deps, so parallel-targets race. Pass JOBS through so the
    # inner Buildroot make `-j$(or $(JOBS),$(shell nproc))` honors our cap.
    target = FIRMWARE_DIR / f"output-{target_subdir}"

    env = os.environ.copy()
    env["BR2_DL_DIR"] = str(DL_CACHE)
    env["BR2_CCACHE_DIR"] = str(CCACHE)
    DL_CACHE.mkdir(parents=True, exist_ok=True)
    CCACHE.mkdir(parents=True, exist_ok=True)

    run(
        ["make", f"BOARD={board}", f"TARGET={target}", f"JOBS={jobs}"],
        cwd=FIRMWARE_DIR,
        env=env,
    )
    return target


def cmd_main(args: argparse.Namespace) -> int:
    if not DEFCONFIG_MAIN.is_file():
        die(f"missing main defconfig at {DEFCONFIG_MAIN}")
    out_dir = build_firmware(
        board="hi3518ev200_ultimate", target_subdir="main", jobs=args.jobs,
    )
    images = out_dir / "images"
    kernel = images / "uImage.hi3518ev200"
    rootfs = images / "rootfs.squashfs.hi3518ev200"
    for p in (kernel, rootfs):
        if not p.is_file():
            die(f"expected artifact missing: {p}")
    target_dir = args.out_dir or Path.cwd()
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(kernel, target_dir / kernel.name)
    shutil.copy(rootfs, target_dir / rootfs.name)
    info(f"main: {kernel.name} + {rootfs.name} → {target_dir}")
    return 0


def cmd_recovery(args: argparse.Namespace) -> int:
    if not DEFCONFIG_RECOVERY.is_file():
        die(f"missing recovery defconfig at {DEFCONFIG_RECOVERY}")
    out_dir = build_firmware(
        board="hi3518ev200_recovery", target_subdir="recovery", jobs=args.jobs,
    )
    src = out_dir / "images" / "uImage.hi3518ev200"
    if not src.is_file():
        die(f"expected artifact missing: {src}")
    target_dir = args.out_dir or Path.cwd()
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / "uImage.hi3518ev200.recovery"
    shutil.copy(src, dst)
    info(f"recovery: {dst}")
    return 0


# ── Full image assembly ──────────────────────────────────────────────────


# Layouts: see build-full-image.sh for the original spec.
LAYOUTS = {
    "8mb": {
        "total":     0x800000,
        "uboot":     {"offset": 0x000000, "max": 0x050000},
        "kernel":    {"offset": 0x050000, "max": 0x200000},
        "rootfs":    {"offset": 0x250000, "max": 0x500000},
        "out_name":  "full-hi3518ev200-lite-8mb.bin",
        "needs_recovery": False,
    },
    "32mb": {
        "total":     0x2000000,
        "uboot":     {"offset": 0x000000,  "max": 0x050000},
        "kernel":    {"offset": 0x060000,  "max": 0x300000},
        "rootfs":    {"offset": 0x360000,  "max": 0x800000},
        "recovery":  {"offset": 0xB60000,  "max": 0x800000},
        "out_name":  "full-hi3518ev200-ultimate-32mb.bin",
        "needs_recovery": True,
    },
}


def assemble_full_image(
    *,
    layout_name: str,
    uboot: Path,
    kernel: Path,
    rootfs: Path,
    recovery: Path | None,
    out_dir: Path,
) -> Path:
    layout = LAYOUTS[layout_name]
    total = layout["total"]

    if layout["needs_recovery"] and recovery is None:
        die(f"layout {layout_name} requires --recovery image")

    # Sanity-check rootfs format.
    with open(rootfs, "rb") as f:
        magic = f.read(4)
    if magic != b"hsqs":
        warn(
            f"{rootfs} doesn't have squashfs magic ('hsqs') — got {magic.hex()}. "
            "UBI rootfs won't attach on NOR; rebuild as squashfs."
        )

    check_size(uboot,  layout["uboot"]["max"],  "uboot")
    check_size(kernel, layout["kernel"]["max"], "kernel")
    check_size(rootfs, layout["rootfs"]["max"], "rootfs")
    if recovery:
        check_size(recovery, layout["recovery"]["max"], "recovery")

    out = out_dir / layout["out_name"]
    out.parent.mkdir(parents=True, exist_ok=True)

    # Fill with 0xFF (erased flash), then write each piece in place.
    info(f"assembling {layout_name} image at {out}")
    with open(out, "wb") as f:
        f.write(b"\xFF" * total)

    def splice(src: Path, offset: int) -> None:
        data = src.read_bytes()
        with open(out, "r+b") as f:
            f.seek(offset)
            f.write(data)

    splice(uboot,  layout["uboot"]["offset"])
    splice(kernel, layout["kernel"]["offset"])
    splice(rootfs, layout["rootfs"]["offset"])
    if recovery:
        splice(recovery, layout["recovery"]["offset"])

    info(f"wrote {out} ({out.stat().st_size} bytes, {layout_name})")
    info(f"  uboot:    {uboot.stat().st_size:>9} / {layout['uboot']['max']:>9} bytes ({uboot})")
    info(f"  kernel:   {kernel.stat().st_size:>9} / {layout['kernel']['max']:>9} bytes")
    info(f"  rootfs:   {rootfs.stat().st_size:>9} / {layout['rootfs']['max']:>9} bytes")
    if recovery:
        info(f"  recovery: {recovery.stat().st_size:>9} / {layout['recovery']['max']:>9} bytes")
    return out


def cmd_full(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    uboot    = args.uboot    or (cwd / f"u-boot-{SOC}-by25q256.bin")
    kernel   = args.kernel   or (cwd / "uImage.hi3518ev200")
    rootfs   = args.rootfs   or (cwd / "rootfs.squashfs.hi3518ev200")
    recovery = args.recovery or (cwd / "uImage.hi3518ev200.recovery")
    if args.size == "8mb":
        recovery = None
    for label, p in [("uboot", uboot), ("kernel", kernel), ("rootfs", rootfs)]:
        if not p.is_file():
            die(f"{label} missing at {p}")
    if recovery and not recovery.is_file():
        die(f"recovery missing at {recovery}")
    assemble_full_image(
        layout_name=args.size,
        uboot=uboot, kernel=kernel, rootfs=rootfs, recovery=recovery,
        out_dir=args.out_dir or cwd,
    )
    return 0


# ── Orchestrator: build everything ───────────────────────────────────────


def _tail_log(label: str, path: Path, n: int = 20) -> None:
    """Print the last n lines of a log to stderr, prefixed with the label."""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception as e:
        print(f"[{label}] (couldn't read log {path}: {e})", file=sys.stderr)
        return
    print(f"[{label}] tail of {path}:", file=sys.stderr)
    for ln in lines[-n:]:
        print(f"  {ln}", file=sys.stderr)


def _spawn_subcommand(label: str, subcmd_args: list, log_path: Path) -> subprocess.Popen:
    """Re-invoke build.py for one subcommand, with stdout+stderr → log_path."""
    log_path.write_bytes(b"")
    cmd = [sys.executable, __file__, *subcmd_args]
    log_fh = open(log_path, "ab")
    return subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT)


def cmd_all(args: argparse.Namespace) -> int:
    out_dir = args.out_dir or Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = out_dir / "build-logs"
    log_dir.mkdir(exist_ok=True)

    DL_CACHE.mkdir(parents=True, exist_ok=True)
    CCACHE.mkdir(parents=True, exist_ok=True)

    uboot_out = out_dir / f"u-boot-{SOC}-by25q256.bin"

    info(f"out: {out_dir}")
    info(f"logs: {log_dir}")
    info(f"parallel: {args.parallel}  (make -j{args.jobs} per build)")
    info(f"dl cache: {DL_CACHE}  ccache: {CCACHE}")

    # Each task is (label, list-of-subcommand-args). We re-invoke build.py
    # with these args; the orchestrator just supervises and pipes the
    # child's stdout/stderr to a log file. Builds DO NOT inherit the
    # parent's terminal — output is silent on the console, in the log.
    tasks = [
        ("uboot",    ["uboot", "--out", str(uboot_out), "--toolchain", str(args.toolchain)]),
        ("main",     ["main", "--out-dir", str(out_dir), "--jobs", str(args.jobs)]),
        ("recovery", ["recovery", "--out-dir", str(out_dir), "--jobs", str(args.jobs)]),
    ]

    start = time.time()
    failed = []

    if args.parallel:
        # Kick off all three at once. Wait for each in start order; for any
        # that failed, tail its log to stderr.
        running = []
        for label, subcmd_args in tasks:
            log_path = log_dir / f"{label}.log"
            info(f"[{label}] starting (log: {log_path})")
            p = _spawn_subcommand(label, subcmd_args, log_path)
            running.append((label, p, log_path))
        for label, p, log_path in running:
            rc = p.wait()
            if rc == 0:
                info(f"[{label}] OK")
            else:
                print(f"[{label}] FAILED rc={rc}", file=sys.stderr)
                _tail_log(label, log_path)
                failed.append(label)
    else:
        # Serial: just run them in order. Stop on first failure (no point
        # building recovery if main is broken — same buildroot tree).
        for label, subcmd_args in tasks:
            log_path = log_dir / f"{label}.log"
            info(f"[{label}] starting (log: {log_path})")
            p = _spawn_subcommand(label, subcmd_args, log_path)
            rc = p.wait()
            if rc == 0:
                info(f"[{label}] OK")
            else:
                print(f"[{label}] FAILED rc={rc}", file=sys.stderr)
                _tail_log(label, log_path)
                failed.append(label)
                break

    if failed:
        die("phase 1 FAILED: " + ", ".join(failed))

    info(f"phase 1 done ({int(time.time() - start)}s)")

    # Phase 2: assemble full image. Runs in the parent process and prints
    # to the console — it's fast and informational.
    kernel_out   = out_dir / "uImage.hi3518ev200"
    rootfs_out   = out_dir / "rootfs.squashfs.hi3518ev200"
    recovery_out = out_dir / "uImage.hi3518ev200.recovery"
    assemble_full_image(
        layout_name="32mb",
        uboot=uboot_out,
        kernel=kernel_out,
        rootfs=rootfs_out,
        recovery=recovery_out,
        out_dir=out_dir,
    )

    total = int(time.time() - start)
    info(f"all done in {total // 60}m{total % 60}s")
    return 0


# ── Argparse ─────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(
        prog="build.py",
        description="Build OpenIPC firmware artifacts for the Dogness hi3518ev200 device.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="SUBCOMMAND")

    # uboot
    pu = sub.add_parser("uboot", help="Build patched U-Boot binary.")
    pu.add_argument(
        "--out", type=Path, default=None,
        help=f"output path (default: $PWD/u-boot-{SOC}-by25q256.bin)",
    )
    pu.add_argument(
        "--toolchain", type=Path, default=DEFAULT_TOOLCHAIN,
        help=f"hisiv300 toolchain root (default: {DEFAULT_TOOLCHAIN})",
    )
    pu.set_defaults(func=cmd_uboot)

    # main
    pm = sub.add_parser("main", help="Build main firmware (kernel + squashfs).")
    pm.add_argument("--out-dir", type=Path, default=None,
                    help="copy artifacts here (default: $PWD)")
    pm.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                    help="inner make -j (default: nproc)")
    pm.set_defaults(func=cmd_main)

    # recovery
    pr = sub.add_parser("recovery", help="Build recovery firmware (kernel + initramfs).")
    pr.add_argument("--out-dir", type=Path, default=None,
                    help="copy artifact here (default: $PWD)")
    pr.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                    help="inner make -j (default: nproc)")
    pr.set_defaults(func=cmd_recovery)

    # full
    pf = sub.add_parser("full", help="Assemble a flashable full-flash image.")
    pf.add_argument("--size", choices=("8mb", "32mb"), default="32mb",
                    help="layout (default: 32mb)")
    pf.add_argument("--uboot", type=Path, default=None,
                    help=f"path to u-boot bin (default: $PWD/u-boot-{SOC}-by25q256.bin)")
    pf.add_argument("--kernel", type=Path, default=None,
                    help="path to kernel uImage (default: $PWD/uImage.hi3518ev200)")
    pf.add_argument("--rootfs", type=Path, default=None,
                    help="path to rootfs squashfs (default: $PWD/rootfs.squashfs.hi3518ev200)")
    pf.add_argument("--recovery", type=Path, default=None,
                    help="path to recovery uImage (32mb layout only) "
                         "(default: $PWD/uImage.hi3518ev200.recovery)")
    pf.add_argument("--out-dir", type=Path, default=None,
                    help="write the full image here (default: $PWD)")
    pf.set_defaults(func=cmd_full)

    # all
    pa = sub.add_parser("all", help="Build u-boot + main + recovery + full image (32MB layout).")
    pa.add_argument("--out-dir", type=Path, default=None,
                    help="output directory (default: $PWD)")
    pa.add_argument("--parallel", action="store_true",
                    help="run u-boot/main/recovery builds in parallel")
    pa.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                    help="inner make -j per build (default: nproc)")
    pa.add_argument("--toolchain", type=Path, default=DEFAULT_TOOLCHAIN,
                    help=f"hisiv300 toolchain root (default: {DEFAULT_TOOLCHAIN})")
    pa.set_defaults(func=cmd_all)

    args = p.parse_args()
    try:
        return args.func(args)
    except subprocess.CalledProcessError as e:
        # Don't dump a Python traceback into the build log — the make/gcc
        # output above already has the real error. Just print a short
        # summary line and exit non-zero.
        cmd = e.cmd if isinstance(e.cmd, str) else " ".join(map(str, e.cmd))
        print(f"error: command failed (exit {e.returncode}): {cmd}", file=sys.stderr)
        return e.returncode or 1


if __name__ == "__main__":
    sys.exit(main())
