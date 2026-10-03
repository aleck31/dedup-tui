"""dedup entry point: `dedup <target>` headless, `dedup tui <target>` interactive."""
import argparse
import os
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from . import core
from .core import DEFAULT_EXCLUDES, QUARANTINE, human


DESCRIPTION = """\
Find duplicate files/directories by content and move the extra copies to a
recoverable quarantine. The most original copy of each group is kept.

Modes:
  dedup <target>        headless CLI: scan, keep the most original copy of every
                        group, print the plan. Dry-run unless --apply is given.
  dedup tui <target>    interactive full-screen review; pick which copies to keep
                        (multiple keepers allowed, >=1 enforced). Needs a terminal.

<target> is a directory to scan, or an existing `rmlint -D` JSON report (skips scanning).
"""

EPILOG = """\
examples:
  dedup ~/Downloads                      preview what would be removed (nothing moves)
  dedup ~/Downloads --apply              remove duplicates, keeping the most original
  dedup ~/Downloads --exclude build      also protect every path containing a "build" dir
  dedup tui ~/Downloads --apply          review interactively, then apply the choices
  dedup report.json --apply              reuse an rmlint report instead of scanning

safety:
  * Default is dry-run; only --apply changes anything.
  * Removals are MOVED to ~/dedup-quarantine/<original path> (never deleted); restore
    by moving them back. Name clashes get a .1, .2 ... suffix.
  * Each victim is re-hashed against the keeper right before it is moved; a mismatch
    is skipped (disable with --no-verify). Victims nested in / linked to the keeper
    are never moved.
  * Paths under excluded directory names are never removed. Built-in excludes:
    {excludes}
  * After --apply the target is re-scanned and leftover duplicates are reported
    (skip with --no-recheck).
  * Every apply appends to ~/dedup-tui.log.

"most original": earliest creation time, then earliest mtime, then shortest path.

engine: uses rmlint if on PATH (fast, also detects identical directories), else a
built-in engine (files only, slower). --no-rmlint forces the built-in one.

exit codes:
  0  success (including dry-run and "no duplicates")
  1  error (e.g. target missing, `tui` without a terminal)
  2  invalid arguments
  3  --apply finished but some removals failed (details in ~/dedup-tui.log)
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="dedup",
        usage="dedup [tui] <target> [--apply] [--exclude NAME] [--no-rmlint] [--no-verify] [--no-recheck]",
        description=DESCRIPTION,
        epilog=EPILOG.format(excludes=", ".join(DEFAULT_EXCLUDES)),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {version('dedup-tui')}")
    ap.add_argument("target", metavar="target", help="directory to scan, or an rmlint .json report "
                    "(a directory literally named 'tui' must be passed as ./tui)")
    ap.add_argument("--apply", action="store_true", help="actually move duplicates to quarantine (default: dry-run)")
    ap.add_argument("--exclude", metavar="NAME", action="append", default=[],
                    help="extra directory name (glob ok) whose contents are never removed; repeatable")
    ap.add_argument("--no-rmlint", action="store_true", help="force the built-in engine even if rmlint is installed")
    ap.add_argument("--no-verify", action="store_true", help="skip the re-hash before each removal (faster, less safe)")
    ap.add_argument("--no-recheck", action="store_true", help="skip the post-apply re-scan")
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    tui = bool(argv) and argv[0] == "tui"
    if tui:
        argv = argv[1:]
    args = build_parser().parse_args(argv)

    excludes = list(DEFAULT_EXCLUDES) + args.exclude
    target = args.target

    # validate target up front
    is_dir = os.path.isdir(target)
    is_json = os.path.isfile(target) and target.endswith(".json")
    if not (is_dir or is_json):
        sys.exit(f"error: '{target}' is neither a directory nor an rmlint .json report")
    if tui and not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("error: 'tui' needs an interactive terminal; use `dedup <target>` for headless runs")

    notice = None if (is_json or args.no_rmlint or core.have_rmlint()) else core.rmlint_hint()

    def do_scan(progress=None):
        if is_json:
            return core.groups_from_rmlint_json(target), "json"
        return core.scan(target, excludes, prefer_rmlint=not args.no_rmlint, progress=progress)

    # --- choose decisions ---
    if not tui:
        # headless: print progress on plain stdout, no TUI
        if notice:
            print(f"note: {notice}", file=sys.stderr)
        print(f"Scanning {target} …", flush=True)
        groups, backend = do_scan()
        groups.sort(key=lambda g: g.waste, reverse=True)
        print(f"Backend: {backend}. Found {len(groups)} duplicate groups.")
        if not groups:
            print("No duplicates found. Nothing to do.")
            return 0
        decisions = []
        for g in groups:
            keeper = g.members[0]
            victims = [m for m in g.members[1:] if not core.excluded(m, excludes)]
            if victims:
                decisions.append((keeper, victims, g.kind))
    else:
        # TUI scans in the background and shows a "Scanning…" indicator immediately
        from .app import DedupApp
        app = DedupApp(excludes, scan_fn=do_scan, notice=notice)
        decisions = app.run()
        if not decisions:
            print("No changes (quit without applying).")
            return 0

    reclaim = sum(g_size_for(d) for d in decisions)
    print(f"\nPlan: {len(decisions)} groups, reclaim ~{human(reclaim)}")

    if not args.apply:
        print("(dry-run — not applied. Re-run with --apply to move duplicates to quarantine.)")
        return 0

    log_path = Path.home() / "dedup-tui.log"
    with open(log_path, "a") as lf:
        lf.write(f"# dedup-tui APPLY {datetime.now().isoformat(timespec='seconds')}\n")
        removed, skipped, failed = core.apply_decisions(
            decisions, verify=not args.no_verify, log=lambda m: lf.write(m + "\n")
        )
    msg = f"Done. quarantined={removed} skipped={skipped}"
    if failed:
        msg += f" failed={failed} (see log)"
    print(msg + ".")
    print(f"Recoverable under {QUARANTINE}. Log: {log_path}")

    # Post-apply verification: re-scan and report what (if anything) remains.
    if is_dir and not args.no_recheck:
        print("Verifying (re-scanning for remaining duplicates)…")
        groups2, _ = do_scan()
        remaining = sum(1 for g in groups2
                        if len([m for j, m in enumerate(g.members)
                                if not core.excluded(m, excludes)]) > 1)
        if remaining == 0:
            print("✓ Verified: no removable duplicates remain.")
        else:
            print(f"⚠ {remaining} duplicate groups still removable "
                  f"(likely failures or excluded paths) — re-run to address.")
    return 3 if failed else 0


def g_size_for(decision):
    keeper, victims, kind = decision
    try:
        if kind == "dir":
            return core._dir_size(keeper) * len(victims)
        return os.path.getsize(keeper) * len(victims)
    except OSError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
