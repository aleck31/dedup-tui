import os

import pytest

from dedup_tui import core


@pytest.fixture(autouse=True)
def qdir(tmp_path, monkeypatch):
    """Point the quarantine and $HOME at tmp so tests never touch the real home."""
    q = tmp_path / "_quarantine"
    monkeypatch.setattr(core, "QUARANTINE", q)
    monkeypatch.setenv("HOME", str(tmp_path / "_home"))
    (tmp_path / "_home").mkdir()
    return q


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "data"
    root.mkdir()

    def make(rel: str, content: bytes = b"x", mtime: float | None = None) -> str:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return str(p)

    make.root = str(root)
    return make
