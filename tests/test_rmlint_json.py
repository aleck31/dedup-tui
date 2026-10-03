import json

import pytest

from dedup_tui import core


def write(tmp_path, data):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_groups_and_footer(tmp_path, tree):
    a, b = tree("a", b"same"), tree("b", b"same")
    j = write(tmp_path, [
        {"description": "header"},
        {"type": "duplicate_file", "checksum": "c1", "path": a},
        {"type": "duplicate_file", "checksum": "c1", "path": b},
        {"total_files": 9, "duplicates": 1, "duplicate_sets": 1, "total_lint_size": 4, "aborted": True},
    ])
    (g,) = core.groups_from_rmlint_json(j)
    assert sorted(g.members) == sorted([a, b]) and g.size == 4
    assert core.LAST_STATS.aborted and core.LAST_STATS.total_files == 9
    assert "PARTIAL" in core.LAST_STATS.summary()


def test_missing_footer_resets_stats(tmp_path, tree):
    a, b = tree("a", b"same"), tree("b", b"same")
    j = write(tmp_path, [
        {"type": "duplicate_file", "checksum": "c", "path": a},
        {"type": "duplicate_file", "checksum": "c", "path": b},
    ])
    core.groups_from_rmlint_json(j)
    assert core.LAST_STATS == core.ScanStats()


def test_part_of_directory_and_vanished_paths_dropped(tmp_path, tree):
    a, b = tree("a", b"same"), tree("b", b"same")
    j = write(tmp_path, [
        {"type": "duplicate_file", "checksum": "c", "path": a},
        {"type": "duplicate_file", "checksum": "c", "path": b, "part_of_directory": True},
        {"type": "duplicate_file", "checksum": "c", "path": str(tmp_path / "gone")},
    ])
    assert core.groups_from_rmlint_json(j) == []


def test_dir_groups(tmp_path, tree):
    tree("d1/f", b"x"); tree("d2/f", b"x")
    d1, d2 = f"{tree.root}/d1", f"{tree.root}/d2"
    j = write(tmp_path, [
        {"type": "duplicate_dir", "checksum": "c", "path": d1},
        {"type": "duplicate_dir", "checksum": "c", "path": d2},
    ])
    (g,) = core.groups_from_rmlint_json(j)
    assert g.kind == "dir" and g.size == 1 and len(g.members) == 2


def test_symlink_members_dropped(tmp_path, tree):
    import os
    a = tree("a", b"same")
    os.symlink(a, f"{tree.root}/l")
    j = write(tmp_path, [
        {"type": "duplicate_file", "checksum": "c", "path": a},
        {"type": "duplicate_file", "checksum": "c", "path": f"{tree.root}/l"},
    ])
    assert core.groups_from_rmlint_json(j) == []


def test_rmlint_failure_falls_back_to_builtin(tree, monkeypatch):
    tree("a", b"dup"); tree("b", b"dup")
    monkeypatch.setattr(core, "have_rmlint", lambda: True)

    def boom(target):
        raise core.ScanError("no report")

    monkeypatch.setattr(core, "scan_with_rmlint", boom)
    groups, backend = core.scan(tree.root, core.DEFAULT_EXCLUDES)
    assert backend == "builtin" and len(groups) == 1


def test_scan_with_rmlint_raises_without_report(tree, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 2, "", "boom"))
    with pytest.raises(core.ScanError):
        core.scan_with_rmlint(tree.root)
