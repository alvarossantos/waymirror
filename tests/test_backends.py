from __future__ import annotations

import json
from pathlib import Path

import pytest

from waymirror.backends.base import BackendError, NoBackendError, detect_backend
from waymirror.backends.niri import parse_niri_outputs
from waymirror.backends.umbriel import parse_umbriel_outputs
from waymirror.backends.niri import parse_niri_windows
from waymirror.backends.umbriel import parse_umbriel_windows

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_niri_fixture():
    outs = parse_niri_outputs((FIXTURES / "niri_outputs.json").read_text())
    assert outs[0].name
    assert any(o.name == "HDMI-A-1" for o in outs)
    edp = next(o for o in outs if o.name == "eDP-2")
    assert edp.width == 1920
    assert edp.height == 1200
    assert edp.refresh_hz == 60.0


def test_parse_umbriel_fixture():
    outs = parse_umbriel_outputs((FIXTURES / "umbriel_outputs.json").read_text())
    assert outs[0].name
    assert any(o.name == "HDMI-A-1" for o in outs)
    hdmi = next(o for o in outs if o.name == "HDMI-A-1")
    assert hdmi.width == 1920
    assert hdmi.height == 1080
    assert hdmi.refresh_hz == 60.0
    assert hdmi.position_x == 1920


def test_detect_auto_prefers_session_signal():
    # env indicates niri session; both commands available
    def fake_run(cmd):
        if cmd[:3] == ["niri", "msg", "--json"]:
            return (FIXTURES / "niri_outputs.json").read_text()
        if cmd[:3] == ["umbriel", "outputs", "--json"]:
            return (FIXTURES / "umbriel_outputs.json").read_text()
        raise AssertionError(cmd)

    b = detect_backend(
        "auto",
        env={"NIRI_SOCKET": "/tmp/niri.sock", "XDG_CURRENT_DESKTOP": "niri"},
        run=fake_run,
        exists=lambda p: True,
    )
    assert b.name == "niri"


def test_detect_explicit_request_wins():
    def fake_run(cmd):
        if cmd[:3] == ["umbriel", "outputs", "--json"]:
            return (FIXTURES / "umbriel_outputs.json").read_text()
        raise AssertionError(f"should not call {cmd}")

    b = detect_backend(
        "umbriel",
        env={"NIRI_SOCKET": "/tmp/niri.sock", "XDG_CURRENT_DESKTOP": "niri"},
        run=fake_run,
        exists=lambda p: True,
    )
    assert b.name == "umbriel"


def test_detect_auto_umbriel_session_signal():
    def fake_run(cmd):
        if cmd[:3] == ["umbriel", "outputs", "--json"]:
            return (FIXTURES / "umbriel_outputs.json").read_text()
        raise AssertionError(f"unexpected {cmd}")

    b = detect_backend(
        "auto",
        env={"XDG_CURRENT_DESKTOP": "umbriel"},
        run=fake_run,
        exists=lambda p: True,
    )
    assert b.name == "umbriel"


def test_detect_auto_fallback_when_no_session_signal():
    calls = []

    def fake_run(cmd):
        calls.append(cmd[0])
        if cmd[0] == "niri":
            raise BackendError("niri failed")
        if cmd[0] == "umbriel":
            return (FIXTURES / "umbriel_outputs.json").read_text()
        raise AssertionError(cmd)

    b = detect_backend("auto", env={}, run=fake_run, exists=lambda p: True)
    assert b.name == "umbriel"
    assert calls[0] == "niri"


def test_detect_no_backend_raises():
    def fake_run(cmd):
        raise BackendError("fail")

    with pytest.raises(NoBackendError):
        detect_backend("auto", env={}, run=fake_run, exists=lambda p: False)


def test_detect_auto_niri_socket_path_uses_default_exists(tmp_path):
    socket_path = tmp_path / "niri.sock"
    socket_path.write_text("")

    def fake_run(cmd):
        if cmd[:3] == ["niri", "msg", "--json"]:
            return (FIXTURES / "niri_outputs.json").read_text()
        raise AssertionError(f"unexpected {cmd}")

    b = detect_backend("auto", env={"NIRI_SOCKET": str(socket_path)}, run=fake_run)
    assert b.name == "niri"


def test_detect_signaled_backend_failure_hard_fails_no_fallback():
    calls = []

    def fake_run(cmd):
        calls.append(cmd[0])
        if cmd[0] == "niri":
            raise BackendError("niri broken")
        if cmd[0] == "umbriel":
            return (FIXTURES / "umbriel_outputs.json").read_text()
        raise AssertionError(cmd)

    with pytest.raises(NoBackendError) as excinfo:
        detect_backend(
            "auto",
            env={"NIRI_SOCKET": "/tmp/niri.sock", "XDG_CURRENT_DESKTOP": "niri"},
            run=fake_run,
            exists=lambda p: True,
        )

    assert calls == ["niri"]
    assert "niri: niri broken" in str(excinfo.value)


def test_detect_probe_handles_command_and_json_like_failures():
    calls = []

    def fake_run(cmd):
        calls.append(cmd[0])
        if cmd[0] == "niri":
            raise ValueError("invalid json")
        if cmd[0] == "umbriel":
            raise OSError("command failed")
        raise AssertionError(cmd)

    with pytest.raises(NoBackendError) as excinfo:
        detect_backend("auto", env={}, run=fake_run, exists=lambda p: False)

    assert calls == ["niri", "umbriel"]
    assert "niri: invalid json" in str(excinfo.value)
    assert "umbriel: command failed" in str(excinfo.value)


def test_niri_parser_handles_list_shape():
    data = json.dumps(
        [
            {
                "name": "DP-1",
                "make": "M",
                "model": "X",
                "logical": {"x": 0, "y": 0, "width": 1280, "height": 720, "scale": 1},
                "modes": [{"width": 1280, "height": 720, "refresh_rate": 60000, "is_preferred": True}],
                "current_mode": 0,
            }
        ]
    )
    outs = parse_niri_outputs(data)
    assert len(outs) == 1
    assert outs[0].name == "DP-1"
    assert outs[0].width == 1280


def test_umbriel_parser_defensive_unknown_fields():
    data = json.dumps(
        [
            {
                "name": "DP-2",
                "mystery": {"nested": True},
                "logical_size": {"width": 100, "height": 100},
                "modes": [{"width": 100, "height": 100, "refresh_mhz": 50000, "current": True}],
                "enabled": True,
                "focused": False,
                "position": {"x": 1, "y": 2},
            }
        ]
    )
    outs = parse_umbriel_outputs(data)
    assert outs[0].name == "DP-2"
    assert outs[0].refresh_hz == 50.0
    assert outs[0].position_x == 1


def test_parse_umbriel_windows_fixture():
    windows = parse_umbriel_windows((FIXTURES / "umbriel_windows.json").read_text())
    assert len(windows) == 2
    window = next(w for w in windows if w.app_id == "firefox")
    assert window.id == "42"
    assert (window.x, window.y, window.w, window.h) == (-1903, 10, 800, 600)
    assert window.output == "HDMI-A-1"
    assert window.visible is True
    assert window.minimized is False


def test_parse_niri_windows_nested_geometry():
    windows = parse_niri_windows((FIXTURES / "niri_windows.json").read_text())
    assert len(windows) == 1
    assert windows[0].id == "7"
    assert windows[0].app_id == "org.example.App"
    assert (windows[0].x, windows[0].y, windows[0].w, windows[0].h) == (-20, 30, 400, 300)
    assert windows[0].output == "eDP-1"


def test_parse_niri_windows_unknown_shape():
    assert parse_niri_windows('{"unexpected": 1}') == []


def test_parse_windows_discards_invalid_or_incomplete_geometry():
    data = json.dumps([
        {"id": 1, "x": "bad", "y": 0, "w": 100, "h": 100},
        {"id": 2, "x": 0, "y": 0, "width": 100},
    ])
    assert parse_umbriel_windows(data) == []


def test_list_windows_implemented_by_backends():
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if cmd == ["umbriel", "windows", "--json"]:
            return (FIXTURES / "umbriel_windows.json").read_text()
        if cmd == ["niri", "msg", "--json", "windows"]:
            return (FIXTURES / "niri_windows.json").read_text()
        raise AssertionError(cmd)

    from waymirror.backends.niri import NiriBackend
    from waymirror.backends.umbriel import UmbrielBackend

    assert len(UmbrielBackend(run=fake_run).list_windows()) == 2
    assert len(NiriBackend(run=fake_run).list_windows()) == 1
    assert calls == [["umbriel", "windows", "--json"], ["niri", "msg", "--json", "windows"]]
