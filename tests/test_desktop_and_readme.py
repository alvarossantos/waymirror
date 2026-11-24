"""Checks for the shipped desktop entry and user documentation."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_FILE = ROOT / "resources" / "io.github.alvaro.waymirror.desktop"
README = ROOT / "README.md"


def test_desktop_file_has_exec():
    text = DESKTOP_FILE.read_text(encoding="utf-8")
    assert "Exec=waymirror" in text
    assert "Name=Waymirror" in text


@pytest.mark.parametrize(
    "field",
    [
        "[Desktop Entry]",
        "Type=Application",
        "Name=Waymirror",
        "Exec=waymirror",
        "Categories=Utility;AudioVideo;",
        "Keywords=mirror;screen;wayland;niri;umbriel;",
    ],
)
def test_desktop_entry_has_required_fields(field: str) -> None:
    assert field in DESKTOP_FILE.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "snippet",
    [
        "niri",
        "umbriel",
        "Python 3.11",
        "sudo pacman -S wl-mirror grim gtk4 libadwaita python-gobject",
        'mkdir -p "$HOME/.local/bin"',
        'ln -sf "$PWD/.venv/bin/waymirror" "$HOME/.local/bin/waymirror"',
        ".venv/bin/python -m waymirror",
        "5` execution failure",
        "waymirror --help",
        "waymirror list",
        "waymirror list windows",
        "waymirror list windows --json",
        "waymirror status",
        "waymirror start --source eDP-2 --mode window",
        "waymirror start --source eDP-2 --mode fullscreen --target HDMI-A-1",
        "waymirror start --window 42 --mode window",
        "waymirror start --window 42 --mode fullscreen --target eDP-2",
        "waymirror toggle --source eDP-2 --mode fullscreen --target HDMI-A-1",
        "waymirror stop",
        "Hyprland",
        "window capture",
        "wl-mirror -r",
        "covered or minimized",
        "Moving or resizing",
        "stop and start again",
        "--target` must be an output other than the output containing the source window",
        "niri window JSON shape has not been verified",
        "output previews use",
        "grim -g <region>",
    ],
)
def test_readme_documents_scope_deps_and_cli(snippet: str) -> None:
    assert snippet in README.read_text(encoding="utf-8")


def test_gtk_app_id_matches_desktop_entry() -> None:
    # The GTK class is unavailable headlessly, so check the declared id against
    # the shipped desktop file name.
    app_source = (ROOT / "waymirror" / "app.py").read_text(encoding="utf-8")
    assert f'application_id="{DESKTOP_FILE.stem}"' in app_source
