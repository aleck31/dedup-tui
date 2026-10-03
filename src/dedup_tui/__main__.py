"""dedup-tui entry point: scan a directory, review duplicates in a TUI, apply safely."""
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
    ap.add_argument("--no-recheck", action="store_true", help="skip the post-apply re-scan verification")
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
                decisions.append((keeper, victims, g.kind))
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


def g_size_for(decision):
    keeper, victims, kind = decision
    try:
        if kind == "dir":
            return core._dir_size(keeper) * len(victims)
        return os.path.getsize(keeper) * len(victims)
    except OSError:
        return 0


if __name__ == "__main__":
    main()
