import json

from waymirror.reveal import find_mirror_window, reveal_mirror_window


def _windows_payload() -> str:
    return json.dumps(
        [
            {
                "id": "w-other",
                "pid": 7777,
                "app_id": "at.yrlf.wl_mirror",
                "title": "Wayland Output Mirror for eDP-2",
                "output": "eDP-2",
                "workspace": "eDP-2:1",
            },
            {
                "id": "w-1",
                "pid": 4242,
                "app_id": "at.yrlf.wl_mirror",
                "title": "Wayland Output Mirror for HDMI-A-1",
                "output": "eDP-2",
                "workspace": "eDP-2:11",
            },
        ]
    )


def test_find_mirror_window_by_pid_then_fallback_app_id():
    def run(cmd):
        return _windows_payload()

    found = find_mirror_window("umbriel", 4242, run)
    assert found is not None
    assert found["id"] == "w-1"
    assert found["output"] == "eDP-2"
    assert found["workspace"] == "eDP-2:11"

    fallback = find_mirror_window("umbriel", 999, run)
    assert fallback is not None
    assert fallback["id"] == "w-other"


def _run_recorder(windows: str, calls: list[list[str]], fail: bool = False):
    def run(cmd):
        calls.append(cmd)
        if fail:
            raise OSError("ipc down")
        if cmd == ["umbriel", "windows", "--json"]:
            return windows
        if cmd == ["umbriel", "workspaces", "--json"]:
            return json.dumps([{"output": "eDP-2", "active": True, "name": "3"}])
        return ""

    return run


def test_reveal_same_output_only_switches_workspace():
    calls: list[list[str]] = []
    run = _run_recorder(_windows_payload(), calls)

    assert reveal_mirror_window("umbriel", 4242, "eDP-2", run=run) is None
    assert calls == [["umbriel", "windows", "--json"], ["umbriel", "msg", "workspace-switch", "eDP-2:11", "--output", "eDP-2"]]


def test_reveal_other_output_focuses_moves_then_switches():
    calls: list[list[str]] = []
    payload = json.dumps(
        [
            {
                "id": "w-1",
                "pid": 4242,
                "app_id": "at.yrlf.wl_mirror",
                "output": "HDMI-A-1",
                "workspace": "HDMI-A-1:5",
            }
        ]
    )
    run = _run_recorder(payload, calls)

    assert reveal_mirror_window("umbriel", 4242, "eDP-2", run=run) is None
    assert [c[:3] for c in calls[1:]] == [
        ["umbriel", "msg", "window-focus"],
        ["umbriel", "msg", "window-move-to-workspace"],
        ["umbriel", "msg", "workspace-switch"],
    ]


def test_reveal_ipc_failure_is_warning():
    calls: list[list[str]] = []
    run = _run_recorder(_windows_payload(), calls, fail=True)

    warning = reveal_mirror_window("umbriel", 4242, "eDP-2", run=run)
    assert warning is not None
    assert "warn" in warning


def test_reveal_window_not_found_after_attempts():
    calls: list[list[str]] = []
    run = _run_recorder(json.dumps([]), calls)
    sleeps: list[float] = []

    warning = reveal_mirror_window(
        "umbriel", 4242, "eDP-2", run=run, sleep=sleeps.append, attempts=2
    )
    assert warning is not None
    assert "not found" in warning
    assert sleeps == [0.1]
