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

    assert find_mirror_window("umbriel", 999, run) is None


def test_find_mirror_window_fallback_with_single_candidate():
    def run(cmd):
        return json.dumps([{"id": "w-1", "pid": 4242, "app_id": "at.yrlf.wl_mirror"}])

    found = find_mirror_window("umbriel", 999, run)
    assert found is not None
    assert found["id"] == "w-1"


def _run_recorder(windows: str, calls: list[list[str]], fail: bool = False):
    def run(cmd):
        calls.append(cmd)
        if fail:
            raise OSError("ipc down")
        if cmd == ["umbriel", "windows", "--json"]:
            return windows
        if cmd == ["umbriel", "workspaces", "--json"]:
            return json.dumps(
                [
                    {"output": "eDP-2", "active": True, "id": "eDP-2:4", "name": "1"},
                    {"output": "eDP-2", "active": False, "id": "eDP-2:11", "name": "3"},
                ]
            )
        return ""

    return run


def test_reveal_same_output_only_switches_workspace():
    calls: list[list[str]] = []
    run = _run_recorder(_windows_payload(), calls)

    assert reveal_mirror_window("umbriel", 4242, "eDP-2", run=run) is None
    assert [c for c in calls if c[1] == "msg"] == [
        ["umbriel", "msg", "workspace-switch", "3", "--output", "eDP-2"]
    ]


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
    ipc = [c for c in calls if c[1] == "msg"]
    assert ipc == [
        ["umbriel", "msg", "window-focus", "w-1"],
        ["umbriel", "msg", "window-move-to-workspace", "1", "--output", "eDP-2"],
        ["umbriel", "msg", "workspace-switch", "1", "--output", "eDP-2"],
    ]


def test_reveal_converts_window_workspace_id_to_ipc_name():
    calls: list[list[str]] = []
    payload = json.dumps(
        [
            {
                "id": "w-1",
                "pid": 4242,
                "app_id": "at.yrlf.wl_mirror",
                "output": "eDP-2",
                "workspace": "eDP-2:4",
            }
        ]
    )
    run = _run_recorder(payload, calls)

    assert reveal_mirror_window("umbriel", 4242, "eDP-2", run=run) is None
    assert [c for c in calls if c[1] == "msg"] == [
        ["umbriel", "msg", "workspace-switch", "1", "--output", "eDP-2"]
    ]


def test_reveal_ipc_failure_is_warning():
    calls: list[list[str]] = []
    run = _run_recorder(_windows_payload(), calls, fail=True)

    warning = reveal_mirror_window("umbriel", 4242, "eDP-2", run=run)
    assert warning is not None
    assert "warn" in warning


def _niri_runner(windows: str, workspaces: str, calls: list[list[str]]):
    def run(cmd):
        calls.append(cmd)
        if cmd == ["niri", "msg", "--json", "windows"]:
            return windows
        if cmd == ["niri", "msg", "--json", "workspaces"]:
            return workspaces
        return ""

    return run


def _niri_payload(workspace_id: int) -> str:
    return json.dumps(
        [
            {
                "id": 123,
                "pid": 4242,
                "app_id": "at.yrlf.wl_mirror",
                "title": "Wayland Output Mirror for HDMI-A-1",
                "workspace_id": workspace_id,
                "is_focused": False,
                "is_floating": True,
                "is_urgent": False,
                "layout": {"tile_size": [1920.0, 1200.0], "window_size": [1920, 1200]},
            }
        ]
    )


_NIRI_WORKSPACES = json.dumps(
    [
        {
            "id": 8,
            "idx": 3,
            "name": None,
            "output": "HDMI-A-1",
            "is_active": True,
            "is_focused": False,
            "is_urgent": False,
            "active_window_id": 123,
        },
        {
            "id": 9,
            "idx": 1,
            "name": "1",
            "output": "eDP-2",
            "is_active": True,
            "is_focused": True,
            "is_urgent": False,
            "active_window_id": 456,
        },
    ]
)


def test_niri_find_mirror_window_derives_output_from_workspace():
    calls: list[list[str]] = []
    run = _niri_runner(_niri_payload(8), _NIRI_WORKSPACES, calls)

    found = find_mirror_window("niri", 4242, run)
    assert found is not None
    assert found == {"id": "123", "output": "HDMI-A-1", "workspace": "3"}


def test_niri_reveal_focuses_moves_and_switches():
    calls: list[list[str]] = []
    run = _niri_runner(_niri_payload(8), _NIRI_WORKSPACES, calls)

    assert reveal_mirror_window("niri", 4242, "eDP-2", run=run) is None
    assert [c for c in calls if c[2] == "action"] == [
        ["niri", "msg", "action", "focus-window", "--id", "123"],
        ["niri", "msg", "action", "move-column-to-monitor", "eDP-2"],
        ["niri", "msg", "action", "focus-workspace", "1"],
    ]


def test_niri_reveal_same_output_only_switches():
    calls: list[list[str]] = []
    run = _niri_runner(_niri_payload(9), _NIRI_WORKSPACES, calls)

    assert reveal_mirror_window("niri", 4242, "eDP-2", run=run) is None
    assert [c for c in calls if c[2] == "action"] == [
        ["niri", "msg", "action", "focus-workspace", "1"]
    ]


def test_invalid_workspaces_json_is_warning():
    calls: list[list[str]] = []
    original = _run_recorder(_windows_payload(), calls)

    def run(cmd):
        return "{bad json" if "workspaces" in cmd else original(cmd)

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
