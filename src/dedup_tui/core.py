"""Core duplicate-detection engine — cross-platform, no UI here.

Two backends:
  - rmlint (fast) if available on PATH
  - built-in pure-Python (size -> partial hash -> full hash) otherwise

"Most original" copy = earliest creation time; ties -> earliest mtime -> shortest path.
Creation time is platform-aware (see creation_time()).
"""
from __future__ import annotations
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

QUARANTINE = Path.home() / "dedup-quarantine"

DEFAULT_EXCLUDES = [
    "node_modules", ".cache", ".venv", "venv", ".git", "__pycache__",
    ".tox", ".gradle", ".npm", "site-packages", "vendor", ".dist-info",
    ".Trash", "$RECYCLE.BIN",
]

_IS_WIN = platform.system() == "Windows"
_IS_MAC = platform.system() == "Darwin"


def creation_time(p: os.stat_result | str | os.PathLike) -> float:
    """Best-effort creation time, platform-aware.

    macOS:   st_birthtime (true birth time)
    Windows: st_ctime (creation time on Windows)
    Linux:   st_birthtime if the kernel/fs exposes it (rare), else st_mtime.
    """
    st = p if isinstance(p, os.stat_result) else os.stat(p)
    bt = getattr(st, "st_birthtime", None)
    if bt is not None:
        return bt
    if _IS_WIN:
        return st.st_ctime  # Windows ctime == creation
    return st.st_mtime      # Linux without birthtime: fall back to mtime


def originality_key(path: str):
    """Lower = more original."""
    try:
        st = os.stat(path)
        return (creation_time(st), st.st_mtime, len(path), path)
    except OSError:
        return (float("inf"), float("inf"), float("inf"), path)


def excluded(path: str, excludes) -> bool:
    parts = Path(path).parts
    return any(e in parts for e in excludes)


def human(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def fmt_date(path: str) -> str:
    try:
        return datetime.fromtimestamp(creation_time(path)).strftime("%Y-%m-%d")
    except OSError:
        return "?"


# --------------------------------------------------------------------------- #
# Group model
# --------------------------------------------------------------------------- #
@dataclass
class Group:
    kind: str               # "file" or "dir"
    members: list[str]      # absolute paths, sorted by originality (index 0 = default keep)
    size: int               # bytes per member

    @property
    def waste(self) -> int:
        return self.size * (len(self.members) - 1)


# --------------------------------------------------------------------------- #
# Backend: rmlint
# --------------------------------------------------------------------------- #
def have_rmlint() -> bool:
    return shutil.which("rmlint") is not None


# Stats parsed from an rmlint JSON footer; .aborted flags an interrupted/partial scan.
@dataclass
class ScanStats:
    total_files: int = 0
    duplicates: int = 0
    duplicate_sets: int = 0
    lint_size: int = 0
    aborted: bool = False

    def summary(self) -> str:
        s = (f"{self.total_files} files · {self.duplicates} dups · "
             f"{self.duplicate_sets} groups · {human(self.lint_size)}")
        return ("⚠ PARTIAL (interrupted) — " + s) if self.aborted else s


# module-level: last scan's stats, set by groups_from_rmlint_json()
LAST_STATS = ScanStats()


def scan_with_rmlint(target: str) -> list[Group]:
    jf = tempfile.NamedTemporaryFile(prefix="dedup-", suffix=".json", delete=False).name
    subprocess.run(
        ["rmlint", target, "-D", "--types=duplicates", f"-o", f"json:{jf}"],
        capture_output=True, text=True,
    )
    if not os.path.exists(jf) or os.path.getsize(jf) == 0:
        return []
    return groups_from_rmlint_json(jf)


def groups_from_rmlint_json(jpath: str) -> list[Group]:
    global LAST_STATS
    data = json.load(open(jpath))
    # footer dict (no "type") carries scan stats incl. the 'aborted' flag
    footer = next((d for d in reversed(data) if "total_files" in d), None)
    if footer:
        LAST_STATS = ScanStats(
            total_files=footer.get("total_files", 0),
            duplicates=footer.get("duplicates", 0),
            duplicate_sets=footer.get("duplicate_sets", 0),
            lint_size=footer.get("total_lint_size", 0),
            aborted=bool(footer.get("aborted", False)),
        )
    else:
        LAST_STATS = ScanStats()
    file_groups: dict[str, list[str]] = defaultdict(list)
    dir_groups: dict[str, list[str]] = defaultdict(list)
    for d in data:
        t = d.get("type")
        if t == "duplicate_dir":
            dir_groups[d["checksum"]].append(d["path"])
        elif t == "duplicate_file" and not d.get("part_of_directory"):
            file_groups[d["checksum"]].append(d["path"])
    groups: list[Group] = []
    for paths in dir_groups.values():
        dirs = [p for p in dict.fromkeys(paths) if os.path.isdir(p)]
        if len(dirs) > 1:
            groups.append(Group("dir", sorted(dirs, key=originality_key), _dir_size(dirs[0])))
    for paths in file_groups.values():
        files = [p for p in dict.fromkeys(paths) if os.path.isfile(p)]
        if len(files) > 1:
            try:
                sz = os.path.getsize(files[0])
            except OSError:
                sz = 0
            groups.append(Group("file", sorted(files, key=originality_key), sz))
    return groups


# --------------------------------------------------------------------------- #
# Backend: built-in pure-Python (size -> partial hash -> full hash)
# --------------------------------------------------------------------------- #
def _hash(path: str, limit: int | None = None, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as f:
        while True:
            want = chunk if limit is None else min(chunk, limit - read)
            if want <= 0:
                break
            b = f.read(want)
            if not b:
                break
            h.update(b)
            read += len(b)
    return h.hexdigest()


def _dir_size(d: str) -> int:
    total = 0
    for root, _, files in os.walk(d):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def scan_builtin(target: str, excludes, progress=None) -> list[Group]:
    """Pure-Python file dedup. Skips excluded dirs. progress(done, msg) optional."""
    by_size: dict[int, list[str]] = defaultdict(list)
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in excludes]
        for name in files:
            p = os.path.join(root, name)
            try:
                if os.path.islink(p):
                    continue
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz > 0:
                by_size[sz].append(p)
    # candidates: same size, >1 file
    candidates = {sz: ps for sz, ps in by_size.items() if len(ps) > 1}
    if progress:
        progress(0, f"{sum(len(v) for v in candidates.values())} size-collision files")

    groups: list[Group] = []
    done = 0
    for sz, paths in candidates.items():
        # stage 1: partial hash (first 4 KiB) to prune
        by_partial: dict[str, list[str]] = defaultdict(list)
        for p in paths:
            try:
                by_partial[_hash(p, limit=4096)].append(p)
            except OSError:
                pass
            done += 1
            if progress and done % 200 == 0:
                progress(done, "partial-hashing")
        for partial_paths in by_partial.values():
            if len(partial_paths) < 2:
                continue
            # stage 2: full hash
            by_full: dict[str, list[str]] = defaultdict(list)
            for p in partial_paths:
                try:
                    by_full[_hash(p)].append(p)
                except OSError:
                    pass
            for full_paths in by_full.values():
                if len(full_paths) > 1:
                    groups.append(Group("file", sorted(full_paths, key=originality_key), sz))
    return groups


def scan(target: str, excludes, prefer_rmlint=True, progress=None) -> tuple[list[Group], str]:
    """Return (groups, backend_name)."""
    if prefer_rmlint and have_rmlint():
        return scan_with_rmlint(target), "rmlint"
    return scan_builtin(target, excludes, progress=progress), "builtin"


# --------------------------------------------------------------------------- #
# Verify + quarantine (applies decisions)
# --------------------------------------------------------------------------- #
def _same_file(a: str, b: str) -> bool:
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        return _hash(a) == _hash(b)
    except OSError:
        return False


def _same_dir(a: str, b: str) -> bool:
    def snap(d):
        m = {}
        for root, _, files in os.walk(d):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, d)
                try:
                    m[rel] = (os.path.getsize(full), _hash(full))
                except OSError:
                    m[rel] = None
        return m
    return snap(a) == snap(b)


def quarantine(path: str) -> str:
    """Move path into the quarantine tree, preserving its absolute location."""
    # Build dest = QUARANTINE / <path without drive/anchor>
    pp = Path(path)
    rel = Path(*pp.parts[1:]) if pp.is_absolute() else pp
    dest = QUARANTINE / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(path, str(dest))
    return str(dest)


def apply_decisions(decisions, verify=True, log=None):
    """decisions: list of (keeper, victims, kind, new_path|None).

    Returns (removed, skipped).
    """
    removed = skipped = 0
    for keeper, victims, kind, new_path in decisions:
        if not os.path.exists(keeper):
            if log: log(f"!! keeper vanished, skip group: {keeper}")
            skipped += len(victims)
            continue
        for v in victims:
            if not os.path.exists(v):
                continue
            if verify:
                ok = _same_dir(keeper, v) if kind == "dir" else _same_file(keeper, v)
                if not ok:
                    if log: log(f"SKIP (content differs now): {v}")
                    skipped += 1
                    continue
            dest = quarantine(v)
            if log: log(f"MOVED {v} -> {dest}")
            removed += 1
        if new_path and os.path.exists(keeper):
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.move(keeper, new_path)
            if log: log(f"RENAMED keeper {keeper} -> {new_path}")
    return removed, skipped
