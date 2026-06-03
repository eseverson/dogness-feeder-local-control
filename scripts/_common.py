"""Shared utilities for the OpenIPC build/flash CLIs.

Keep this module dependency-free (stdlib only) so the CLIs run on any
Python 3.8+ without setup.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ── Paths ────────────────────────────────────────────────────────────────

# scripts/openipc/_common.py → ../../.. is the openipc/ root
SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
FIRMWARE_DIR = REPO_ROOT / "firmware"
UBOOT_TREE = REPO_ROOT / "u-boot-hi3516cv200"
PATCHES_DIR = OPENIPC_DIR / "patches"


# ── Shell helpers ────────────────────────────────────────────────────────


def info(msg: str) -> None:
    print(f"==> {msg}")


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def die(msg: str, code: int = 1) -> "None":
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def run(
    cmd,
    *,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """Run a command; print it first so the user can see what's happening.

    cmd may be a list or a string; if a string, it's run through the shell.

    When `cwd` is given, we also set PWD in the child's environment to match.
    POSIX doesn't update PWD on chdir — it's a shell convention — but GNU
    Make initializes its built-in $(PWD) variable from the env var. OpenIPC's
    Makefile uses $(PWD)/general/openipc.fragment unquoted, so when the
    invocation directory contains a space, the cat command splits into
    broken arguments. Setting PWD to the actual cwd sidesteps that.
    """
    shell = isinstance(cmd, str)
    pretty = cmd if shell else " ".join(shlex.quote(str(c)) for c in cmd)
    print(f"$ {pretty}", file=sys.stderr)
    if cwd is not None:
        env = dict(env) if env is not None else os.environ.copy()
        env["PWD"] = str(cwd)
    return subprocess.run(
        cmd,
        shell=shell,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=capture,
        text=capture,
    )


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ── SSH / SCP ────────────────────────────────────────────────────────────


@dataclass
class SSHTarget:
    """A reachable OpenIPC device. Bundles the args we always pass to ssh/scp."""

    host: str
    user: str = "root"
    timeout: int = 10

    @property
    def base_args(self):
        return [
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={self.timeout}",
        ]

    def ssh(self, remote_cmd: str, *, capture: bool = False, check: bool = True):
        return run(
            ["ssh", *self.base_args, f"{self.user}@{self.host}", remote_cmd],
            capture=capture,
            check=check,
        )

    def ssh_capture(self, remote_cmd: str) -> str:
        cp = self.ssh(remote_cmd, capture=True, check=False)
        if cp.returncode != 0:
            die(
                f"ssh '{remote_cmd}' failed (rc={cp.returncode}): "
                f"{cp.stderr.strip()}"
            )
        return cp.stdout

    def scp_to(self, local: Path, remote: str) -> None:
        # -O = legacy scp protocol; required for older dropbear servers.
        run(
            ["scp", "-O", *self.base_args, str(local), f"{self.user}@{self.host}:{remote}"],
        )

    def transfer_with_md5(self, local: Path, remote: str, label: str) -> None:
        """Copy local→remote and verify md5 matches end-to-end."""
        local_md5 = md5_file(local)
        info(f"[{label}] transferring {local.name} → {remote}")
        self.ssh(f"rm -f {shlex.quote(remote)}")
        self.scp_to(local, remote)
        out = self.ssh_capture(f"md5sum {shlex.quote(remote)}")
        remote_md5 = out.split()[0]
        if remote_md5 != local_md5:
            die(
                f"[{label}] MD5 mismatch — aborting\n"
                f"  local:  {local_md5}\n"
                f"  remote: {remote_md5}"
            )
        info(f"[{label}] md5 verified ({local_md5})")


# ── MTD inspection ───────────────────────────────────────────────────────


@dataclass
class MtdPartition:
    index: int           # mtd0 → 0
    size_bytes: int
    erase_bytes: int
    name: str

    @property
    def size_kb(self) -> int:
        return self.size_bytes // 1024


def parse_proc_mtd(text: str) -> list:
    """Parse /proc/mtd text into a list[MtdPartition], indexed by mtd number."""
    parts = []
    pat = re.compile(r"^mtd(\d+):\s+([0-9a-f]+)\s+([0-9a-f]+)\s+\"([^\"]+)\"")
    for line in text.splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        idx, sz, er, name = m.group(1), m.group(2), m.group(3), m.group(4)
        parts.append(
            MtdPartition(
                index=int(idx),
                size_bytes=int(sz, 16),
                erase_bytes=int(er, 16),
                name=name,
            )
        )
    return parts


def fetch_mtd_map(target: SSHTarget) -> list:
    text = target.ssh_capture("cat /proc/mtd")
    parts = parse_proc_mtd(text)
    if not parts:
        die("could not parse /proc/mtd from device")
    return parts


def require_mtd(parts, index: int, expected_name: str) -> MtdPartition:
    """Look up mtd[index] and assert its name matches; die otherwise."""
    for p in parts:
        if p.index == index:
            if p.name != expected_name:
                die(
                    f"mtd{index} is '{p.name}', expected '{expected_name}' — "
                    f"refusing to flash. Check `cat /proc/mtd` on the device."
                )
            return p
    die(f"mtd{index} not present in /proc/mtd")


# ── Misc ─────────────────────────────────────────────────────────────────


def confirm(prompt: str, *, default_no: bool = True) -> bool:
    suffix = "[y/N]" if default_no else "[Y/n]"
    ans = input(f"{prompt} {suffix} ").strip().lower()
    if not ans:
        return not default_no
    return ans in ("y", "yes")


@contextlib.contextmanager
def timed(label: str):
    start = time.time()
    yield
    secs = int(time.time() - start)
    info(f"{label} done in {secs // 60}m{secs % 60}s")


def check_size(path: Path, max_bytes: int, label: str) -> int:
    size = path.stat().st_size
    if size > max_bytes:
        die(f"{label} too big: {size} > {max_bytes} bytes")
    return size


def ensure_executable(path: Path, name: str) -> None:
    if not path.is_file() or not os.access(path, os.X_OK):
        die(f"{name} not found or not executable at {path}")
