from dedup_tui import core


def test_originality_orders_by_creation_then_mtime_then_path_length(tree, monkeypatch):
    births = {}
    monkeypatch.setattr(core, "creation_time", lambda st: births[st.st_mtime])
    old = tree("old", b"x", mtime=1_000_000_000); births[1_000_000_000] = 1.0
    new = tree("new", b"x", mtime=2_000_000_000); births[2_000_000_000] = 2.0
    assert sorted([new, old], key=core.originality_key) == [old, new]

    births[3_000_000_000] = births[3_000_000_001] = 5.0
    short = tree("s", b"x", mtime=3_000_000_000)
    longer = tree("longer-name", b"x", mtime=3_000_000_000)
    assert sorted([longer, short], key=core.originality_key) == [short, longer]


def test_originality_missing_path_sorts_last(tree):
    real = tree("a", b"x")
    assert sorted([f"{tree.root}/missing", real], key=core.originality_key)[0] == real


def test_human():
    assert core.human(0) == "0.0B" and core.human(1536) == "1.5KB" and core.human(1 << 40) == "1.0TB"


def test_fmt_date_missing():
    assert core.fmt_date("/no/such/file") == "?"


def test_group_waste():
    assert core.Group("file", ["a", "b", "c"], 10).waste == 20


def test_cli_version_matches_pyproject(capsys):
    import tomllib
    from pathlib import Path
    import pytest
    from dedup_tui import __main__ as cli
    meta = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == f"dedup-tui {meta['project']['version']}"
