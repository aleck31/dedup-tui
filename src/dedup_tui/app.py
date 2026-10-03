"""Textual TUI for reviewing duplicate groups and choosing which copy to keep.

Uses a virtualized DataTable (one row per group) so it stays fast with thousands
of groups. Per-group state (chosen keeper index, skip flag) is kept in plain lists,
NOT in widgets — adding 7000+ widgets would freeze the terminal.
"""
import os

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.events import Key
from textual.widgets import DataTable, Footer, Header, Static

from . import __version__
from .core import Group, human, fmt_date, excluded


class DedupApp(App):
    TITLE = "Duplicate Finder"
    SUB_TITLE = f"v{__version__}"
    CSS = """
    #status { background: $boost; color: $text; padding: 0 1; height: 1; }
    #table { height: 1fr; width: 50%; }
    #detail-scroll { height: 1fr; width: 50%; border-left: solid $primary; padding: 0 1; }
    #detail-head { width: 100%; height: auto; }
    #members { height: 1fr; width: 100%; }
    /* highlight the focused panel so it's clear where ↑/↓ act */
    DataTable:focus { background: $boost; }
    """
    # Arrow keys are primary; WASD are fallbacks for keyboards without arrows.
    # ↑/↓ move the row in the focused panel; ←/→ switch focus between panels.
    BINDINGS = [
        Binding("up,w", "nav_up", "row", show=True, key_display="↑/↓"),
        Binding("down,s", "nav_down", "row", show=False),
        Binding("left,a", "focus_left", "panel", show=True, key_display="←/→"),
        Binding("right,d", "focus_right", "panel", show=False),
        Binding("space", "toggle_keep", "keep/drop", show=True, key_display="space"),
        Binding("f", "filter", "filter>10MB", show=True),
        Binding("r", "all_default", "reset", show=True),
        Binding("x", "apply", "apply", show=True),
        Binding("q,escape", "quit", "quit", show=True, key_display="q/esc"),
    ]

    def on_key(self, event: Key) -> None:
        # A focused DataTable swallows arrows/wasd for its own cursor; intercept
        # here so ↑/↓ move the row in the focused panel and ←/→ switch panels.
        if event.key in ("left", "a"):
            event.stop(); event.prevent_default(); self._focus_panel("table")
        elif event.key in ("right", "d"):
            event.stop(); event.prevent_default(); self._focus_panel("members")
        elif event.key in ("up", "w"):
            event.stop(); event.prevent_default(); self._nav(-1)
        elif event.key in ("down", "s"):
            event.stop(); event.prevent_default(); self._nav(+1)

    _SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, excludes, scan_fn=None, groups: list[Group] | None = None):
        super().__init__()
        self.excludes = excludes
        self.scan_fn = scan_fn
        self.all_groups: list[Group] = groups or []
        # keep_flags[g][m] = keep this member? (multiple keepers allowed; ≥1 enforced)
        self.keep_flags: list[list[bool]] = []
        self.cursor: list[int] = []     # per-group: which member is highlighted (for ←/→)
        self.visible_idx: list[int] = []  # group indices currently shown (after filter)
        self.filtered = False
        self.scanning = scan_fn is not None
        self.result = None
        self._spin = 0
        self._elapsed = 0.0
        self._scan_msg = "starting…"
        self._scan_count = 0
        self._scan_timer = None
        self._backend = None

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="status")
        with Horizontal():
            yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="detail-scroll"):
                yield Static(id="detail-head")
                yield DataTable(id="members", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self):
        t = self.query_one("#table", DataTable)
        t.add_columns("#", "kind", "size", "keep →")
        m = self.query_one("#members", DataTable)
        m.add_column("", key="mark", width=8)
        m.add_column("date", key="date", width=10)
        m.add_column("filename", key="filename", width=22)
        m.add_column("path", key="path")   # auto-width: takes the differing dir path
        if self.scanning:
            self._scan_timer = self.set_interval(0.1, self._tick_scan)
            self._scan_worker()
        else:
            self._after_scan_init()

    # ------------------------------------------------------------------ scanning
    def _tick_scan(self):
        self._spin = (self._spin + 1) % len(self._SPINNER)
        self._elapsed += 0.1
        ch = self._SPINNER[self._spin]
        extra = f" · {self._scan_count} files" if self._scan_count else ""
        self.query_one("#status", Static).update(
            f" {ch} Scanning for duplicates… {self._elapsed:.0f}s{extra} · {self._scan_msg}"
        )

    def _on_scan_progress(self, done: int, msg: str):
        def upd():
            self._scan_count = done
            self._scan_msg = msg
        self.call_from_thread(upd)

    @work(thread=True, exclusive=True)
    def _scan_worker(self):
        groups, backend = self.scan_fn(self._on_scan_progress)
        groups.sort(key=lambda g: g.waste, reverse=True)
        self.call_from_thread(self._scan_done, groups, backend)

    def _scan_done(self, groups, backend):
        if self._scan_timer is not None:
            self._scan_timer.stop()
            self._scan_timer = None
        self.all_groups = groups
        self.scanning = False
        self._backend = backend
        if not groups:
            self.query_one("#status", Static).update(
                f" No duplicates found (backend: {backend}, {self._elapsed:.0f}s). Press q to quit."
            )
            return
        from . import core
        if backend == "rmlint" and core.LAST_STATS.aborted:
            self.notify(
                "rmlint scan was interrupted — results are PARTIAL and may miss duplicates. "
                "Re-run without interrupting before applying.",
                title="Partial scan", severity="warning", timeout=10,
            )
        self._after_scan_init()

    def _after_scan_init(self):
        # default: keep the most-original (index 0), drop the rest; cursor on it
        self.keep_flags = [[j == 0 for j in range(len(g.members))] for g in self.all_groups]
        self.cursor = [0] * len(self.all_groups)
        self._rebuild_table()
        self._update_status()
        self._update_detail()
        self.set_focus(self.query_one("#table", DataTable))   # start on the group list

    # ------------------------------------------------------------------ table
    def _rebuild_table(self):
        t = self.query_one("#table", DataTable)
        t.clear()
        self.visible_idx = [
            i for i, g in enumerate(self.all_groups)
            if (not self.filtered) or g.size >= 10 * 1024 * 1024
        ]
        rows = []
        for i in self.visible_idx:
            rows.append(self._row_cells(i))
        if rows:
            t.add_rows(rows)

    def _row_cells(self, i: int):
        g = self.all_groups[i]
        return (str(i + 1), g.kind, human(g.size), self._keep_summary(i))

    def _keep_summary(self, i: int) -> str:
        """Compact 'keep' column: how many kept + the kept name(s)."""
        g = self.all_groups[i]
        kept = [m for j, m in enumerate(g.members) if self.keep_flags[i][j]]
        if len(kept) == 1:
            return _short(kept[0])
        if len(kept) == 0:
            return "⚠ none!"
        return f"keep {len(kept)}: " + _short(kept[0], 22)

    def _selected_group(self) -> int | None:
        t = self.query_one("#table", DataTable)
        r = t.cursor_row
        if r is None or not (0 <= r < len(self.visible_idx)):
            return None
        return self.visible_idx[r]

    def _refresh_current_row(self):
        t = self.query_one("#table", DataTable)
        r = t.cursor_row
        gi = self._selected_group()
        if gi is None:
            return
        t.update_cell_at((r, 3), self._keep_summary(gi))

    # ------------------------------------------------------------------ detail panel
    def _member_row(self, gi: int, j: int):
        """One row in the members table: marker, date, filename, path(dir)."""
        from rich.text import Text
        full = self.all_groups[gi].members[j]
        keep = self.keep_flags[gi][j]
        star = "★ " if j == 0 else "  "
        base = os.path.basename(full.rstrip("/")) or full
        fname = base if len(base) <= 22 else base[:19] + "…"
        folder = os.path.dirname(full) or full      # path column shows the directory
        if keep:
            marker = Text(star + "✔ KEEP", style="bold black on green")
            filename = Text(fname, style="green")
            path = Text(folder, style="green")
        else:
            marker = Text(star + " drop ", style="dim")
            filename = Text(fname, style="dim")
            path = Text(folder, style="dim")
        return (marker, fmt_date(full), filename, path)

    def _update_detail(self, rebuild: bool = True):
        gi = self._selected_group()
        head = self.query_one("#detail-head", Static)
        m = self.query_one("#members", DataTable)
        if gi is None:
            head.update("")
            m.clear()
            return
        g = self.all_groups[gi]
        nkeep = sum(self.keep_flags[gi])
        head.update(
            f"Group #{gi + 1} · {g.kind} · {human(g.size)} each · keeping {nkeep}\n"
            "→ focus here · ↑/↓ pick file · space keep/drop (≥1 required)"
        )
        if rebuild:
            # group changed → repopulate the members table and seat the cursor
            m.clear()
            for j in range(len(g.members)):
                m.add_row(*self._member_row(gi, j), key=str(j))
            cur = self.cursor[gi]
            if m.row_count:
                m.move_cursor(row=min(cur, m.row_count - 1))

    # ------------------------------------------------------------------ status
    def _update_status(self):
        from . import core
        total = len(self.all_groups)
        # reclaimable = size × (#members dropped) per group
        reclaim_bytes = 0
        for i, g in enumerate(self.all_groups):
            dropped = sum(1 for j in range(len(g.members)) if not self.keep_flags[i][j])
            reclaim_bytes += g.size * dropped
        kept_waste = reclaim_bytes
        shown = len(self.visible_idx)
        flt = " · filter>10MB" if self.filtered else ""
        be = ""
        if self._backend == "rmlint":
            warn = "⚠PARTIAL " if core.LAST_STATS.aborted else ""
            be = f"{warn}rmlint {self._elapsed:.0f}s · "
        elif self._backend:
            be = f"{self._backend} {self._elapsed:.0f}s · "
        self.query_one("#status", Static).update(
            f" {be}groups {total} · showing {shown}{flt} · reclaim ~{human(kept_waste)}"
        )

    # ------------------------------------------------------------------ focus / navigation
    def _focused_panel(self) -> str:
        """'members' if the right panel is focused, else 'table' (the default)."""
        f = self.focused
        return "members" if (f is not None and f.id == "members") else "table"

    def _focus_panel(self, which: str):
        """←/→ switch focus between the group table (left) and members table (right)."""
        target = "#members" if which == "members" else "#table"
        try:
            w = self.query_one(target, DataTable)
        except Exception:
            return
        if which == "members" and w.row_count == 0:
            return  # nothing to focus into
        if which == "members":
            gi = self._selected_group()
            if gi is not None and w.row_count:
                w.move_cursor(row=min(self.cursor[gi], w.row_count - 1))
        self.set_focus(w)

    def _nav(self, delta: int):
        """↑/↓ move the row in whichever panel is focused."""
        if self._focused_panel() == "members":
            self._move_member(delta)
        else:
            self._move_group(delta)

    def _move_group(self, delta: int):
        t = self.query_one("#table", DataTable)
        if delta < 0:
            t.action_cursor_up()
        else:
            t.action_cursor_down()
        self._update_detail(rebuild=True)

    def _move_member(self, delta: int):
        """Move the highlighted file within the current group (members table auto-scrolls)."""
        gi = self._selected_group()
        if gi is None:
            return
        n = len(self.all_groups[gi].members)
        self.cursor[gi] = (self.cursor[gi] + delta) % n
        m = self.query_one("#members", DataTable)
        if m.row_count:
            m.move_cursor(row=self.cursor[gi])   # DataTable scrolls the row into view

    def action_toggle_keep(self):
        """space: toggle keep/drop on the highlighted file; always keep ≥1."""
        gi = self._selected_group()
        if gi is None:
            return
        j = self.cursor[gi]
        flags = self.keep_flags[gi]
        if flags[j]:
            if sum(flags) <= 1:
                self.notify("At least one copy must be kept.", severity="warning", timeout=3)
                return
            flags[j] = False
        else:
            flags[j] = True
        # update just this member row + the group's keep-summary + header count
        m = self.query_one("#members", DataTable)
        marker, _date, filename, path = self._member_row(gi, j)
        m.update_cell(str(j), "mark", marker)
        m.update_cell(str(j), "filename", filename)
        m.update_cell(str(j), "path", path)
        self._refresh_current_row()
        self._update_detail(rebuild=False)
        self._update_status()

    def action_filter(self):
        self.filtered = not self.filtered
        self._rebuild_table()
        self._update_status()
        self._update_detail()

    def action_all_default(self):
        """Reset every group to: keep most-original only."""
        for i, g in enumerate(self.all_groups):
            self.keep_flags[i] = [j == 0 for j in range(len(g.members))]
            self.cursor[i] = 0
        self._rebuild_table()
        self._update_status()
        self._update_detail()

    def action_apply(self):
        decisions = []
        for i, g in enumerate(self.all_groups):
            keepers = [m for j, m in enumerate(g.members) if self.keep_flags[i][j]]
            if not keepers:
                continue  # safety: never delete a whole group
            # victims = members marked drop AND not under an excluded dir
            victims = [m for j, m in enumerate(g.members)
                       if not self.keep_flags[i][j] and not excluded(m, self.excludes)]
            if victims:
                # keeper passed to apply is just the verify reference; any kept copy works
                decisions.append((keepers[0], victims, g.kind))
        self.result = decisions
        self.exit(decisions)


def _short(path: str, width: int = 32) -> str:
    """Tail-truncate a path for the narrow table cell."""
    return path if len(path) <= width else "…" + path[-(width - 1):]
