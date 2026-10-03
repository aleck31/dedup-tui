import os

from dedup_tui import __main__ as cli


def run(tree, *args):
    cli.main([tree.root, "--auto", "--no-rmlint", *args])


def test_auto_is_dry_run_by_default(tree, capsys):
    tree("a", b"same"); tree("b", b"same")
    run(tree)
    assert "dry-run" in capsys.readouterr().out
    assert sorted(os.listdir(tree.root)) == ["a", "b"]


def test_auto_apply_quarantines_and_verifies(tree, qdir, capsys, tmp_path):
    for n in "abc":
        tree(n, b"same")
    run(tree, "--apply")
    out = capsys.readouterr().out
    assert "quarantined=2" in out and "no removable duplicates remain" in out
    assert len(os.listdir(tree.root)) == 1
    assert sum(1 for p in qdir.rglob("*") if p.is_file()) == 2
    assert "APPLY" in (tmp_path / "_home" / "dedup-tui.log").read_text()


def test_log_is_appended_not_overwritten(tree, tmp_path):
    tree("a", b"same"); tree("b", b"same")
    run(tree, "--apply")
    tree("c", b"other"); tree("d", b"other")
    run(tree, "--apply")
    assert (tmp_path / "_home" / "dedup-tui.log").read_text().count("# dedup-tui APPLY") == 2


def test_no_duplicates(tree, capsys):
    tree("a", b"1"); tree("b", b"2")
    run(tree)
    assert "No duplicates" in capsys.readouterr().out


def test_bad_target_exits(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        cli.main([str(tmp_path / "nope")])
