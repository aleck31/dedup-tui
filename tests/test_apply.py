import os
from pathlib import Path

from dedup_tui import core


def logs():
    buf = []
    return buf, buf.append


def test_moves_victims_keeps_keeper(tree, qdir):
    k, v = tree("k", b"same"), tree("v", b"same")
    buf, log = logs()
    assert core.apply_decisions([(k, [v], "file")], log=log) == (1, 0, 0)
    assert os.path.exists(k) and not os.path.exists(v)
    assert (qdir / Path(v).relative_to("/")).read_bytes() == b"same"


def test_content_changed_since_scan_is_skipped(tree):
    k, v = tree("k", b"same"), tree("v", b"same")
    Path(v).write_bytes(b"CHANGED")
    assert core.apply_decisions([(k, [v], "file")]) == (0, 1, 0)
    assert os.path.exists(v)


def test_no_verify_skips_hash_check(tree):
    k, v = tree("k", b"aaa"), tree("v", b"bbb")
    assert core.apply_decisions([(k, [v], "file")], verify=False) == (1, 0, 0)


def test_missing_keeper_skips_group(tree):
    v = tree("v", b"x")
    assert core.apply_decisions([(f"{tree.root}/gone", [v], "file")]) == (0, 1, 0)
    assert os.path.exists(v)


def test_vanished_victim_ignored(tree):
    k = tree("k", b"x")
    assert core.apply_decisions([(k, [f"{tree.root}/gone"], "file")]) == (0, 0, 0)


def test_one_failure_does_not_abort_rest(tree, monkeypatch):
    k, v1, v2 = tree("k", b"s"), tree("v1", b"s"), tree("v2", b"s")
    real = core.quarantine

    def flaky(p):
        if p == v1:
            raise PermissionError("locked")
        return real(p)

    monkeypatch.setattr(core, "quarantine", flaky)
    assert core.apply_decisions([(k, [v1, v2], "file")]) == (1, 0, 1)
    assert os.path.exists(v1) and not os.path.exists(v2)


def test_quarantine_collision_keeps_earlier_copy(tree, qdir):
    k, v = tree("k", b"same"), tree("v", b"same")
    core.apply_decisions([(k, [v], "file")])
    Path(v).write_bytes(b"same")   # same path reappears, gets removed again
    core.apply_decisions([(k, [v], "file")])
    dest = qdir / Path(v).relative_to("/")
    assert dest.exists() and dest.with_name(dest.name + ".1").exists()


def test_dir_duplicates(tree, qdir):
    tree("d1/a", b"1"); tree("d1/s/b", b"2"); tree("d2/a", b"1"); tree("d2/s/b", b"2")
    d1, d2 = f"{tree.root}/d1", f"{tree.root}/d2"
    assert core.apply_decisions([(d1, [d2], "dir")]) == (1, 0, 0)
    assert os.path.isdir(d1) and not os.path.exists(d2)


def test_dir_with_different_content_skipped(tree):
    tree("d1/a", b"1"); tree("d2/a", b"2")
    d1, d2 = f"{tree.root}/d1", f"{tree.root}/d2"
    assert core.apply_decisions([(d1, [d2], "dir")]) == (0, 1, 0)


def test_nested_victim_is_never_moved(tree):
    tree("d/a", b"1"); tree("d/inner/a", b"1")
    outer, inner = f"{tree.root}/d", f"{tree.root}/d/inner"
    assert core.apply_decisions([(outer, [inner], "dir")], verify=False) == (0, 1, 0)
    assert os.path.exists(f"{outer}/a") and os.path.exists(f"{inner}/a")


def test_symlink_to_keeper_is_never_moved(tree):
    k = tree("k", b"x")
    link = f"{tree.root}/link"
    os.symlink(k, link)
    assert core.apply_decisions([(k, [link], "file")], verify=False) == (0, 1, 0)
    assert os.path.exists(k)


def test_accounting_balances(tree, qdir):
    k = tree("k", b"s")
    vs = [tree(f"v{i}", b"s") for i in range(5)]
    removed, skipped, failed = core.apply_decisions([(k, vs, "file")])
    assert removed == 5 and skipped == failed == 0
    assert sum(1 for p in qdir.rglob("v*") if p.is_file()) == 5
    assert sorted(os.listdir(tree.root)) == ["k"]
