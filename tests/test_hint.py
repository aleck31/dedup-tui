import pytest

from dedup_tui import core


def fake(monkeypatch, system, present):
    monkeypatch.setattr(core.platform, "system", lambda: system)
    monkeypatch.setattr(core.shutil, "which", lambda b: f"/bin/{b}" if b in present else None)


@pytest.mark.parametrize("system,present,expected", [
    ("Darwin", {"brew"}, "brew install rmlint"),
    ("Darwin", {"port"}, "sudo port install rmlint"),
    ("Linux", {"apt-get"}, "sudo apt-get install rmlint"),
    ("Linux", {"dnf"}, "sudo dnf install rmlint"),
    ("Linux", {"pacman"}, "sudo pacman -S rmlint"),
    ("Linux", {"apk"}, "sudo apk add rmlint"),
    ("Linux", {"brew"}, "brew install rmlint"),
])
def test_install_command_follows_platform_and_package_manager(monkeypatch, system, present, expected):
    fake(monkeypatch, system, present)
    assert core.rmlint_install_hint() == expected


def test_first_matching_manager_wins(monkeypatch):
    fake(monkeypatch, "Linux", {"apt-get", "brew"})
    assert core.rmlint_install_hint() == "sudo apt-get install rmlint"


def test_windows_mentions_wsl(monkeypatch):
    fake(monkeypatch, "Windows", set())
    assert "WSL" in core.rmlint_install_hint()


@pytest.mark.parametrize("system", ["Linux", "Darwin", "FreeBSD"])
def test_no_known_manager_falls_back_to_link(monkeypatch, system):
    fake(monkeypatch, system, set())
    assert "github.com/sahib/rmlint" in core.rmlint_install_hint()
