import os

from dedup_tui import __main__ as cli


def run(tree, *args):
    return cli.main([tree.root, "--no-rmlint", *args])


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


def test_hint_when_rmlint_missing(tree, capsys, monkeypatch):
    from dedup_tui import core
    tree("a", b"same"); tree("b", b"same")
    monkeypatch.setattr(core, "have_rmlint", lambda: False)
    cli.main([tree.root])
    assert "rmlint not found" in capsys.readouterr().err


def test_no_hint_with_no_rmlint_flag(tree, capsys, monkeypatch):
    from dedup_tui import core
    monkeypatch.setattr(core, "have_rmlint", lambda: False)
    run(tree)
    assert "rmlint not found" not in capsys.readouterr().err


def test_help_documents_modes_and_safety(capsys):
    import pytest
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert e.value.code == 0
    for word in ("dedup tui <target>", "--apply", "dry-run", "quarantine", "exit codes", "rmlint"):
        assert word in out


def test_tui_requires_terminal(tree):
    import pytest
    with pytest.raises(SystemExit) as e:
        cli.main(["tui", tree.root])
    assert "interactive terminal" in str(e.value)


def test_tui_prefix_launches_tui(tree, monkeypatch):
    import sys
    from dedup_tui import app
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    seen = {}

    class Fake:
        def __init__(self, excludes, scan_fn, notice):
            seen["ok"] = True

        def run(self):
            return []

    monkeypatch.setattr(app, "DedupApp", Fake)
    assert cli.main(["tui", tree.root]) == 0 and seen["ok"]


def test_exit_code_3_when_apply_has_failures(tree, monkeypatch):
    from dedup_tui import core
    tree("a", b"same"); tree("b", b"same")
    monkeypatch.setattr(core, "quarantine", lambda p: (_ for _ in ()).throw(PermissionError("locked")))
    assert run(tree, "--apply") == 3


def test_exit_code_0_on_success(tree):
    tree("a", b"same"); tree("b", b"same")
    assert run(tree) == 0 and run(tree, "--apply") == 0
