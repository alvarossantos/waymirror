from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass

import pytest

from waymirror.mirror import MirrorManager, MirrorStopError, WlMirrorMissingError, MirrorValidationError, OutputNotFoundError, build_wl_mirror_cmd
from waymirror.models import MirrorSession, Window
from waymirror.state import StateStore


@dataclass
class FakeProc:
    pid: int


class FakeRunner:
    def __init__(self, pid=12345, fail_missing=False, fail_os=False):
        self.pid = pid
        self.fail_missing = fail_missing
        self.fail_os = fail_os
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if self.fail_missing:
            raise FileNotFoundError("wl-mirror")
        if self.fail_os:
            raise OSError("boom")
        return FakeProc(pid=self.pid)


def make_manager(tmp_path, runner=None, pid_alive=None, now=None, killer=None, waiter=None, revealer=None):
    store = StateStore(tmp_path / "state.json")
    runner = runner or FakeRunner()
    pid_alive = pid_alive or (lambda pid: True)
    now = now or (lambda: "2026-01-01T00:00:00Z")
    killer = killer or (lambda pid, sig: None)
    waiter = waiter or (lambda pid: True)
    return MirrorManager(store, runner=runner, pid_alive=pid_alive, now=now, killer=killer, waiter=waiter, revealer=revealer), store, runner


def test_build_fullscreen_cmd():
    assert build_wl_mirror_cmd("eDP-2", "fullscreen", "HDMI-A-1") == [
        "wl-mirror",
        "--fullscreen-output",
        "HDMI-A-1",
        "eDP-2",
    ]


def test_build_window_cmd():
    assert build_wl_mirror_cmd("eDP-2", "window", None) == ["wl-mirror", "eDP-2"]


def test_start_window_records_state(tmp_path):
    mgr, store, runner = make_manager(tmp_path)
    res = mgr.start("niri", "eDP-2", "window", None, available_outputs=["eDP-2", "HDMI-A-1"])
    assert res.action == "started"
    assert runner.calls == [["wl-mirror", "eDP-2"]]
    session = store.load()
    assert session is not None
    assert session.backend == "niri"
    assert session.source == "eDP-2"
    assert session.mode == "window"
    assert session.target is None
    assert session.pid == 12345


def test_start_same_config_idempotent(tmp_path):
    mgr, store, runner = make_manager(tmp_path)
    mgr.start("niri", "eDP-2", "window", None, available_outputs=["eDP-2"])
    res = mgr.start("niri", "eDP-2", "window", None, available_outputs=["eDP-2"])
    assert res.action == "already_running"
    assert len(runner.calls) == 1


def test_start_restarts_window_when_region_changes(tmp_path):
    mgr, store, runner = make_manager(tmp_path)
    original = Window("abc", x=10, y=20, w=300, h=200, output="HDMI-A-1")
    moved = Window("abc", x=30, y=40, w=300, h=200, output="HDMI-A-1")
    mgr.start("niri", "abc", "window", None, source_kind="window", available_windows=[original])
    runner.pid = 54321
    result = mgr.start("niri", "abc", "window", None, source_kind="window", available_windows=[moved])
    assert result.action == "started"
    assert runner.calls[-1] == ["wl-mirror", "-r", "30,40 300x200 HDMI-A-1"]
    assert store.load().region == "30,40 300x200 HDMI-A-1"


def test_start_different_config_stops_previous(tmp_path):
    killed = []
    mgr, store, runner = make_manager(
        tmp_path,
        killer=lambda pid, sig: killed.append((pid, sig)),
        waiter=lambda pid: True,
    )
    mgr.start("niri", "eDP-2", "window", None, available_outputs=["eDP-2", "HDMI-A-1"])
    runner.pid = 54321
    res = mgr.start("niri", "eDP-2", "fullscreen", "HDMI-A-1", available_outputs=["eDP-2", "HDMI-A-1"])
    assert res.action == "started"
    assert killed == [(12345, signal.SIGTERM)]
    assert store.load().pid == 54321
    assert store.load().mode == "fullscreen"


def test_start_fullscreen_reveals_mirror_window(tmp_path):
    calls = []
    runner = FakeRunner(pid=4242)
    mgr, store, _ = make_manager(
        tmp_path,
        runner=runner,
        revealer=lambda backend, pid, target: calls.append((backend, pid, target)) or "warn: reveal failed",
    )

    res = mgr.start("umbriel", "HDMI-A-1", "fullscreen", "eDP-2", available_outputs=["eDP-2", "HDMI-A-1"])

    assert res.action == "started"
    assert calls == [("umbriel", 4242, "eDP-2")]
    assert res.warning == "warn: reveal failed"
    assert store.load().pid == 4242


def test_start_window_does_not_reveal(tmp_path):
    calls = []
    mgr, _, _ = make_manager(
        tmp_path,
        revealer=lambda backend, pid, target: calls.append((backend, pid, target)),
    )

    res = mgr.start("umbriel", "eDP-2", "window", None, available_outputs=["eDP-2", "HDMI-A-1"])

    assert res.action == "started"
    assert calls == []
    assert res.warning is None


def test_start_fullscreen_joins_stale_and_reveal_warnings(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save(MirrorSession("umbriel", "HDMI-A-1", "fullscreen", "eDP-2", 999999, "t"))
    mgr = MirrorManager(
        store,
        runner=FakeRunner(pid=4242),
        pid_alive=lambda pid: False,
        revealer=lambda backend, pid, target: "warn: reveal failed",
    )

    res = mgr.start("umbriel", "HDMI-A-1", "fullscreen", "eDP-2", available_outputs=["eDP-2", "HDMI-A-1"])

    assert res.action == "started"
    assert "cleared stale session" in res.warning
    assert "warn: reveal failed" in res.warning
    assert res.warning == "cleared stale session for dead pid 999999; warn: reveal failed"


def test_toggle_stops_same_config(tmp_path):
    killed = []
    mgr, store, runner = make_manager(tmp_path, killer=lambda pid, sig: killed.append((pid, sig)))
    mgr.start("niri", "eDP-2", "window", None, available_outputs=["eDP-2"])
    res = mgr.toggle("niri", "eDP-2", "window", None, available_outputs=["eDP-2"])
    assert res.action == "stopped"
    assert killed == [(12345, signal.SIGTERM)]
    assert store.load() is None


def test_toggle_starts_when_inactive(tmp_path):
    mgr, store, runner = make_manager(tmp_path)
    res = mgr.toggle("niri", "eDP-2", "window", None, available_outputs=["eDP-2"])
    assert res.action == "started"
    assert store.load() is not None


def test_toggle_different_config_replaces(tmp_path):
    killed = []
    mgr, store, runner = make_manager(tmp_path, killer=lambda pid, sig: killed.append((pid, sig)))
    mgr.start("niri", "eDP-2", "window", None, available_outputs=["eDP-2", "HDMI-A-1"])
    runner.pid = 999
    res = mgr.toggle("niri", "eDP-2", "fullscreen", "HDMI-A-1", available_outputs=["eDP-2", "HDMI-A-1"])
    assert res.action == "started"
    assert killed == [(12345, signal.SIGTERM)]
    assert store.load().pid == 999


def test_stop_kills_recorded_pid_only(tmp_path):
    killed = []
    mgr, store, _ = make_manager(tmp_path, killer=lambda pid, sig: killed.append((pid, sig)))
    mgr.start("niri", "eDP-2", "window", None, available_outputs=["eDP-2"])
    res = mgr.stop()
    assert res.action == "stopped"
    assert killed == [(12345, signal.SIGTERM)]
    assert store.load() is None


def test_stop_dead_pid_clears_state(tmp_path):
    # stale pid: pid_alive false
    mgr, store, _ = make_manager(tmp_path, pid_alive=lambda pid: False)
    store.save(MirrorSession("niri", "eDP-2", "window", None, 999999, "t"))
    res = mgr.stop()
    assert res.action == "stale_cleared"
    assert store.load() is None


def test_stop_live_pid_kill_failure_errors(tmp_path):
    def bad_kill(pid, sig):
        raise PermissionError("nope")

    mgr, store, _ = make_manager(tmp_path, killer=bad_kill, pid_alive=lambda pid: True)
    store.save(MirrorSession("niri", "eDP-2", "window", None, 123, "t"))
    with pytest.raises(Exception) as excinfo:
        mgr.stop()
    err = excinfo.value
    assert getattr(err, "exit_code", None) == 5
    assert store.load() is not None


def test_missing_wl_mirror_raises_exit5(tmp_path):
    runner = FakeRunner(fail_missing=True)
    mgr, store, _ = make_manager(tmp_path, runner=runner)
    with pytest.raises(WlMirrorMissingError) as excinfo:
        mgr.start("niri", "eDP-2", "window", None, available_outputs=["eDP-2"])
    assert excinfo.value.exit_code == 5
    assert store.load() is None


def test_status_reports_inactive(tmp_path):
    mgr, _, _ = make_manager(tmp_path)
    res = mgr.status()
    assert res.active is False
    assert res.session is None


def test_status_reports_active(tmp_path):
    mgr, store, _ = make_manager(tmp_path)
    mgr.start("niri", "eDP-2", "window", None, available_outputs=["eDP-2"])
    res = mgr.status()
    assert res.active is True
    assert res.session is not None
    assert res.session.source == "eDP-2"


def test_start_validates_source_exists(tmp_path):
    from waymirror.mirror import OutputNotFoundError

    mgr, _, _ = make_manager(tmp_path)
    with pytest.raises(OutputNotFoundError):
        mgr.start("niri", "NOPE", "window", None, available_outputs=["eDP-2"])


def test_start_validates_target_exists_fullscreen(tmp_path):
    from waymirror.mirror import OutputNotFoundError

    mgr, _, _ = make_manager(tmp_path)
    with pytest.raises(OutputNotFoundError):
        mgr.start("niri", "eDP-2", "fullscreen", "NOPE", available_outputs=["eDP-2"])


def test_start_fullscreen_requires_different_target(tmp_path):
    from waymirror.mirror import MirrorValidationError

    mgr, _, _ = make_manager(tmp_path)
    with pytest.raises(MirrorValidationError):
        mgr.start("niri", "eDP-2", "fullscreen", "eDP-2", available_outputs=["eDP-2"])


def test_stop_clears_invalid_state_file(tmp_path):
    mgr, store, _ = make_manager(tmp_path)
    store.path.write_text('{bad json', encoding='utf-8')
    res = mgr.stop()
    assert res.action == 'stale_cleared'
    assert not store.path.exists()


def test_default_waiter_honors_injected_pid_alive(tmp_path):
    # The real pid is dead, but the injected predicate says it stays alive:
    # the default waiter must therefore report a stop timeout.
    store = StateStore(tmp_path / "state.json")
    mgr = MirrorManager(
        store,
        runner=FakeRunner(),
        pid_alive=lambda pid: True,
        now=lambda: "2026-01-01T00:00:00Z",
        killer=lambda pid, sig: None,
    )
    store.save(MirrorSession("niri", "eDP-2", "window", None, 2_000_000_000, "t"))

    with pytest.raises(MirrorStopError):
        mgr.stop()


def test_build_cmd_window_region():
    assert build_wl_mirror_cmd("ignored", "window", None, source_kind="window", region="10,20 300x200 HDMI-A-1") == ["wl-mirror", "-r", "10,20 300x200 HDMI-A-1"]
    assert build_wl_mirror_cmd("ignored", "fullscreen", "eDP-2", source_kind="window", region="10,20 300x200 HDMI-A-1") == ["wl-mirror", "--fullscreen-output", "eDP-2", "-r", "10,20 300x200 HDMI-A-1"]


def test_build_cmd_output_unchanged():
    assert build_wl_mirror_cmd("eDP-2", "window", None) == ["wl-mirror", "eDP-2"]
    assert build_wl_mirror_cmd("eDP-2", "fullscreen", "HDMI-A-1") == ["wl-mirror", "--fullscreen-output", "HDMI-A-1", "eDP-2"]


def test_window_source_not_validated_as_output(tmp_path):
    mgr, store, runner = make_manager(tmp_path)
    window = Window(id="abc", output="HDMI-A-1", x=10, y=20, w=300, h=200)
    res = mgr.start("niri", "abc", "window", None, available_outputs=["eDP-2", "HDMI-A-1"], source_kind="window", available_windows=[window])
    assert res.action == "started"
    assert runner.calls == [["wl-mirror", "-r", "10,20 300x200 HDMI-A-1"]]
    assert store.load().source_kind == "window"


def test_window_missing_exit_4(tmp_path):
    mgr, _, _ = make_manager(tmp_path)
    with pytest.raises(OutputNotFoundError):
        mgr.start("niri", "abc", "window", None, source_kind="window", available_windows=[])


def test_start_rejects_hidden_window(tmp_path):
    mgr, _, _ = make_manager(tmp_path)
    with pytest.raises(MirrorValidationError):
        mgr.start("niri", "abc", "window", None, source_kind="window", available_windows=[Window(id="abc", output="HDMI-A-1", w=300, h=200, minimized=True)])


def test_fullscreen_window_target_must_differ_from_source_output(tmp_path):
    mgr, _, _ = make_manager(tmp_path)
    with pytest.raises(MirrorValidationError):
        mgr.start("niri", "abc", "fullscreen", "HDMI-A-1", available_outputs=["eDP-2", "HDMI-A-1"], source_kind="window", available_windows=[Window(id="abc", output="HDMI-A-1", w=300, h=200)])
