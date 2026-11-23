from __future__ import annotations

import json
import subprocess
import sys

import pytest

import waymirror.cli as cli
from waymirror.backends.base import BackendError, NoBackendError
from waymirror.mirror import (
    MirrorStopError,
    MirrorValidationError,
    OutputNotFoundError,
    StartResult,
    StatusResult,
    StopResult,
    WlMirrorMissingError,
)
from waymirror.models import MirrorSession, Output


class FakeBackend:
    name = "niri"

    def __init__(self, outputs=None, fail: Exception | None = None):
        self.outputs = outputs or []
        self.fail = fail
        self.list_calls = 0

    def list_outputs(self):
        self.list_calls += 1
        if self.fail is not None:
            raise self.fail
        return list(self.outputs)


class FakeManager:
    def __init__(self, *, start_result=None, stop_result=None, status_result=None, toggle_result=None):
        self.start_result = start_result
        self.stop_result = stop_result
        self.status_result = status_result
        self.toggle_result = toggle_result
        self.calls = []

    def start(self, backend, source, mode, target, *, available_outputs=None):
        self.calls.append(("start", backend, source, mode, target, available_outputs))
        if isinstance(self.start_result, Exception):
            raise self.start_result
        return self.start_result

    def stop(self):
        self.calls.append(("stop",))
        if isinstance(self.stop_result, Exception):
            raise self.stop_result
        return self.stop_result

    def status(self):
        self.calls.append(("status",))
        if isinstance(self.status_result, Exception):
            raise self.status_result
        return self.status_result

    def toggle(self, backend, source, mode, target, *, available_outputs=None):
        self.calls.append(("toggle", backend, source, mode, target, available_outputs))
        if isinstance(self.toggle_result, Exception):
            raise self.toggle_result
        return self.toggle_result


def install_fake_runtime(monkeypatch, *, backend=None, manager=None, detect_exc=None):
    backend = backend or FakeBackend([Output(name="eDP-2"), Output(name="HDMI-A-1")])
    manager = manager or FakeManager(
        status_result=StatusResult(active=False, session=None),
        stop_result=StopResult(action="not_running"),
    )
    detect_calls = {}

    def fake_detect(requested, env=None, run=None, exists=None):
        detect_calls["requested"] = requested
        detect_calls["env"] = env
        if detect_exc is not None:
            raise detect_exc
        return backend

    monkeypatch.setattr(cli, "detect_backend", fake_detect)
    monkeypatch.setattr(cli, "StateStore", lambda path: object())
    monkeypatch.setattr(cli, "MirrorManager", lambda store: manager)
    monkeypatch.setattr(cli, "default_state_path", lambda: "/tmp/waymirror-test-state.json")
    return backend, manager, detect_calls


def test_start_requires_target_for_fullscreen():
    r = subprocess.run(
        [sys.executable, "-m", "waymirror", "start", "--source", "eDP-2", "--mode", "fullscreen"],
        capture_output=True,
        text=True,
        cwd="/home/alvaro/Projects/waymirror",
    )
    assert r.returncode == 2


def test_list_json_with_fake_backend(monkeypatch, capsys):
    outputs = [
        Output(name="eDP-2", width=1920, height=1200, refresh_hz=60.0),
        Output(name="HDMI-A-1", width=1920, height=1080, refresh_hz=60.0),
    ]
    backend, manager, detect_calls = install_fake_runtime(
        monkeypatch, backend=FakeBackend(outputs)
    )

    rc = cli.main(["--backend", "niri", "list", "--json"])
    out = capsys.readouterr().out

    assert rc == 0
    assert detect_calls["requested"] == "niri"
    payload = json.loads(out)
    assert payload["backend"] == "niri"
    assert [o["name"] for o in payload["outputs"]] == ["eDP-2", "HDMI-A-1"]
    assert manager.calls == []


def test_list_human_with_fake_backend(monkeypatch, capsys):
    outputs = [Output(name="eDP-2", description="Internal", width=1920, height=1200, refresh_hz=60.0)]
    install_fake_runtime(monkeypatch, backend=FakeBackend(outputs,))

    rc = cli.main(["list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "eDP-2" in out
    assert "1920x1200" in out


def test_status_inactive_json(monkeypatch, capsys):
    install_fake_runtime(
        monkeypatch,
        manager=FakeManager(status_result=StatusResult(active=False, session=None)),
    )
    rc = cli.main(["status", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["active"] is False
    assert payload["session"] is None


def test_status_active_json(monkeypatch, capsys):
    session = MirrorSession("niri", "eDP-2", "window", None, 123, "2026-01-01T00:00:00Z")
    install_fake_runtime(
        monkeypatch,
        manager=FakeManager(status_result=StatusResult(active=True, session=session)),
    )
    rc = cli.main(["status", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["active"] is True
    assert payload["session"]["source"] == "eDP-2"
    assert payload["session"]["pid"] == 123


def test_start_passes_available_outputs_and_backend(monkeypatch, capsys):
    session = MirrorSession("niri", "eDP-2", "window", None, 123, "t")
    backend = FakeBackend([Output(name="eDP-2"), Output(name="HDMI-A-1")])
    manager = FakeManager(start_result=StartResult(action="started", session=session))
    install_fake_runtime(monkeypatch, backend=backend, manager=manager)

    rc = cli.main(["--backend", "niri", "start", "--source", "eDP-2", "--mode", "window"])
    out = capsys.readouterr().out
    assert rc == 0
    assert manager.calls == [
        ("start", "niri", "eDP-2", "window", None, ["eDP-2", "HDMI-A-1"])
    ]
    assert "started" in out.lower() or "eDP-2" in out


def test_toggle_passes_available_outputs(monkeypatch):
    session = MirrorSession("niri", "eDP-2", "fullscreen", "HDMI-A-1", 123, "t")
    backend = FakeBackend([Output(name="eDP-2"), Output(name="HDMI-A-1")])
    manager = FakeManager(toggle_result=StartResult(action="started", session=session))
    install_fake_runtime(monkeypatch, backend=backend, manager=manager)

    rc = cli.main([
        "toggle", "--source", "eDP-2", "--mode", "fullscreen", "--target", "HDMI-A-1"
    ])
    assert rc == 0
    assert manager.calls == [
        ("toggle", "niri", "eDP-2", "fullscreen", "HDMI-A-1", ["eDP-2", "HDMI-A-1"])
    ]


def test_start_missing_source_maps_to_exit_4(monkeypatch, capsys):
    backend = FakeBackend([Output(name="eDP-2")])
    manager = FakeManager(start_result=OutputNotFoundError("source output not found: NOPE"))
    install_fake_runtime(monkeypatch, backend=backend, manager=manager)

    rc = cli.main(["start", "--source", "NOPE", "--mode", "window"])
    err = capsys.readouterr().err
    assert rc == 4
    assert "NOPE" in err or "not found" in err.lower()


def test_start_validation_error_maps_to_exit_2(monkeypatch):
    backend = FakeBackend([Output(name="eDP-2")])
    manager = FakeManager(start_result=MirrorValidationError("target must differ"))
    install_fake_runtime(monkeypatch, backend=backend, manager=manager)

    rc = cli.main(["start", "--source", "eDP-2", "--mode", "fullscreen", "--target", "eDP-2"])
    assert rc == 2


def test_backend_missing_maps_to_exit_3(monkeypatch):
    install_fake_runtime(monkeypatch, detect_exc=NoBackendError("no supported backend detected"))

    rc = cli.main(["list"])
    assert rc == 3


def test_wl_mirror_missing_maps_to_exit_5(monkeypatch):
    backend = FakeBackend([Output(name="eDP-2")])
    manager = FakeManager(start_result=WlMirrorMissingError("wl-mirror not found"))
    install_fake_runtime(monkeypatch, backend=backend, manager=manager)

    rc = cli.main(["start", "--source", "eDP-2", "--mode", "window"])
    assert rc == 5


def test_stop_kill_failure_maps_to_exit_5(monkeypatch):
    manager = FakeManager(stop_result=MirrorStopError("wl-mirror pid 123 did not exit after SIGTERM"))
    install_fake_runtime(monkeypatch, manager=manager)
    rc = cli.main(["stop"])
    assert rc == 5


def test_stop_not_running(monkeypatch, capsys):
    manager = FakeManager(stop_result=StopResult(action="not_running", session=None))
    install_fake_runtime(monkeypatch, manager=manager)
    rc = cli.main(["stop"])
    out = capsys.readouterr().out.lower()
    assert rc == 0
    assert "not running" in out or "inactive" in out


def test_unknown_command_returns_usage_error(monkeypatch):
    # argparse should exit 2; cli.main should normalize
    rc = cli.main(["nope"])
    assert rc == 2


def test_list_backend_command_failure_maps_to_exit_3(monkeypatch):
    backend = FakeBackend(fail=BackendError("niri failed"))
    install_fake_runtime(monkeypatch, backend=backend)
    rc = cli.main(["list"])
    assert rc == 3


def test_start_uses_detected_backend_name(monkeypatch):
    session = MirrorSession("umbriel", "HDMI-A-1", "window", None, 55, "t")
    backend = FakeBackend([Output(name="HDMI-A-1")])
    backend.name = "umbriel"
    manager = FakeManager(start_result=StartResult(action="started", session=session))
    install_fake_runtime(monkeypatch, backend=backend, manager=manager)
    rc = cli.main(["--backend", "auto", "start", "--source", "HDMI-A-1", "--mode", "window"])
    assert rc == 0
    assert manager.calls[0][1] == "umbriel"


def test_status_reports_inactive_when_no_state_file(monkeypatch, capsys):
    manager = FakeManager(status_result=StatusResult(active=False, session=None, warning=None))
    install_fake_runtime(monkeypatch, manager=manager)
    rc = cli.main(["status"])
    out = capsys.readouterr().out.lower()
    assert rc == 0
    assert "inactive" in out or "not running" in out
