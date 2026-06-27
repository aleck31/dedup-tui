"""dedup-tui entry point: scan a directory, review duplicates in a TUI, apply safely."""
from __future__ import annotations
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from . import core
from .core import DEFAULT_EXCLUDES, QUARANTINE, human


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="dedup-tui",
        description="Interactive cross-platform duplicate remover; keeps the most original copy.",
    )
    ap.add_argument("target", help="directory to scan, or an existing rmlint .json report")
    ap.add_argument("--apply", action="store_true", help="actually move duplicates (else dry-run)")
    ap.add_argument("--auto", action="store_true", help="non-interactive: keep most-original everywhere")
    ap.add_argument("--exclude", action="append", default=[], help="extra dir name to exclude (repeatable)")
    ap.add_argument("--no-rmlint", action="store_true", help="force built-in engine even if rmlint exists")
    ap.add_argument("--no-verify", action="store_true", help="skip re-hash before removing (faster)")
    args = ap.parse_args(argv)

    excludes = list(DEFAULT_EXCLUDES) + args.exclude
    target = args.target

    # validate target up front
    is_dir = os.path.isdir(target)
    is_json = os.path.isfile(target) and target.endswith(".json")
    if not (is_dir or is_json):
        sys.exit(f"error: '{target}' is neither a directory nor an rmlint .json report")

    def do_scan(progress=None):
        if is_json:
            return core.groups_from_rmlint_json(target), "json"
        return core.scan(target, excludes, prefer_rmlint=not args.no_rmlint, progress=progress)

    # --- choose decisions ---
    if args.auto:
        # headless: print progress on plain stdout, no TUI
        print(f"Scanning {target} …", flush=True)
        groups, backend = do_scan()
        groups.sort(key=lambda g: g.waste, reverse=True)
        print(f"Backend: {backend}. Found {len(groups)} duplicate groups.")
        if not groups:
            print("No duplicates found. Nothing to do.")
            return
        decisions = []
        for g in groups:
            keeper = g.members[0]
            victims = [m for m in g.members[1:] if not core.excluded(m, excludes)]
            if victims:
                decisions.append((keeper, victims, g.kind, None))
    else:
        # TUI scans in the background and shows a "Scanning…" indicator immediately
        from .app import DedupApp
        app = DedupApp(excludes, scan_fn=do_scan)
        decisions = app.run()
        if not decisions:
            print("No changes (quit without applying).")
            return

    reclaim = sum(g_size_for(d) for d in decisions)
    print(f"\nPlan: {len(decisions)} groups, reclaim ~{human(reclaim)}")

    if not args.apply:
        print("(dry-run — not applied. Re-run with --apply to move duplicates to quarantine.)")
        return

    log_path = Path.home() / "dedup-tui.log"
    lf = open(log_path, "w")
    lf.write(f"# dedup-tui APPLY {datetime.now().isoformat(timespec='seconds')}\n")
    removed, skipped = core.apply_decisions(
        decisions, verify=not args.no_verify, log=lambda m: lf.write(m + "\n")
    )
    lf.close()
    print(f"Done. quarantined={removed} skipped={skipped}.")
    print(f"Recoverable under {QUARANTINE}. Log: {log_path}")


def g_size_for(decision):
    keeper, victims, kind, _ = decision
    try:
        if kind == "dir":
            return core._dir_size(keeper) * len(victims)
        return os.path.getsize(keeper) * len(victims)
    except OSError:
        return 0


if __name__ == "__main__":
    main()
