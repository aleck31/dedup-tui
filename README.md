# dedup-tui

Cross-platform interactive duplicate-file finder with a full-screen TUI. Keeps the **most original** copy of each duplicate set; removals go to a recoverable quarantine.

Works on macOS, Linux, and Windows. No manual pre-scan step — point it at a directory.

## Install / run

With [uv](https://docs.astral.sh/uv/) (no install, ephemeral):

```bash
uvx --from /Users/aleckx/tools/dedup-tui dedup-tui /path/to/dir
```

Or install as a persistent tool:

```bash
uv tool install /Users/aleckx/tools/dedup-tui     # or: pipx install /Users/aleckx/tools/dedup-tui
dedup-tui /path/to/dir
```

## Usage

```bash
dedup-tui <dir>                 # scan + TUI review; dry-run (nothing moved)
dedup-tui <dir> --apply         # scan + TUI review; apply chosen removals
dedup-tui <dir> --auto --apply  # non-interactive: keep most-original everywhere, then apply
dedup-tui <rmlint.json>         # reuse an existing rmlint -D JSON report (skip scanning)
```

Options: `--exclude NAME` (extra dir to skip, repeatable) · `--no-rmlint` (force built-in engine) · `--no-verify` (skip the pre-removal re-hash).

## TUI keys

Arrow keys are primary; **WASD** are fallbacks for keyboards without arrows.

| Key | Action |
|---|---|
| ↑/↓ (or w/s) | move between groups |
| ←/→ (or a/d) | move the highlighted file within the current group |
| space | toggle keep/drop on the highlighted file — **multiple keepers allowed**, at least 1 enforced |
| r | reset all groups to default (keep most-original only) |
| f | toggle filter: show only groups ≥ 10 MB |
| x | apply (build the plan and exit) |
| q | quit without applying |

By default each group keeps only its most-original copy (★). Use ←/→ to land on another copy and `space` to also keep it (or to drop a copy). You can keep several copies of the same content if you need duplicates in different locations.

The status bar shows total groups, how many are shown, and the space reclaimed if applied.

## "Most original" rule

Per group, the default keeper (★) is the earliest **creation time**, ties broken by earliest **modification time**, then shortest path. Creation time is platform-aware:

- macOS: `st_birthtime`
- Windows: `st_ctime` (creation on Windows)
- Linux: `st_birthtime` if the filesystem exposes it, otherwise falls back to `mtime`

## Duplicate engine

- **rmlint** if on PATH (fast; also merges fully-identical directories into one group via `-D`).
- **Built-in** pure-Python otherwise (size → 4 KiB partial hash → full SHA-256). Slower on huge trees but zero external dependency, so it works on Windows where rmlint is usually absent.

Force the built-in engine with `--no-rmlint`.

## Safety

- Default is **dry-run**; `--apply` is required to change anything.
- Removals are **moved to `~/dedup-quarantine/`** (full original path preserved), never `rm`.
- Before each removal the victim is **re-hashed against the keeper** (directories compared file-by-file); a mismatch skips it. Disable with `--no-verify`.
- Excluded by default (won't be removed): `node_modules`, `.cache`, `.venv`, `venv`, `.git`, `__pycache__`, `.tox`, `.gradle`, `.npm`, `site-packages`, `.dist-info`, `vendor`, `.Trash`, `$RECYCLE.BIN`.
- Full action log at `~/dedup-tui.log`.

## Restore

Move files back from `~/dedup-quarantine/<original path>` to their original location.

## Development

Versioning follows [SemVer](https://semver.org/): **PATCH** for bug fixes, **MINOR** for backward-compatible features, **MAJOR** for breaking changes. Bump the version in `pyproject.toml` and `src/dedup_tui/__init__.py` together, and only to reflect the *nature of the change* — not as a trick to refresh caches.

To pick up local edits when installed via `uv tool` (uv may reuse a cached build of the same version), reinstall without relying on a version bump:

```bash
uv tool install --reinstall .          # or: uv cache clean dedup-tui && uv tool install --reinstall .
```
