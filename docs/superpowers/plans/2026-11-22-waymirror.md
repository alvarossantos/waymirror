# Waymirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `waymirror`, a standalone Wayland screen-mirroring app for niri and umbriel with a GTK4/libadwaita GUI, live grim-based previews, wl-mirror session control, and a headless CLI.

**Architecture:** Small Python package with pure logic modules (`models`, `state`, `backends`, `mirror`, `preview`) and thin edges (`cli`, GTK `app`). Backends normalize compositor output inventory; `mirror` owns the single-session state machine and wl-mirror process; GUI polls previews and reflects state.

**Tech Stack:** Python 3, PyGObject/GTK4/libadwaita, argparse, subprocess, pytest, `grim`, `wl-mirror`.

**Spec:** `docs/superpowers/specs/2026-11-22-waymirror-design.md`

## Global Constraints

- v1 scope: **niri and umbriel only**; Wayland only; **screen/output mirroring only** (no window capture).
- Canonical output identifier is **`Output.name`** (connector, e.g. `eDP-2`) everywhere: CLI args, `list --json`, `state.json`, `grim -o`, `wl-mirror` source/target.
- Backend selection: `--backend auto|niri|umbriel`, default `auto`. Auto is session-aware; session signals take priority over “binary installed”.
- Exactly **one active mirror session** at a time. Session identity is `backend + source + mode + target` (`target=null` for window mode).
- `toggle`: inactive -> start; active same config -> stop; active different config -> stop then start.
- `stop`/cleanup kills **only the PID recorded in state**. No `pkill -x wl-mirror`, no `--force` in v1.
- Preview route 1: `grim -o <name>` ~2 fps, paused when GUI hidden/minimized; capture failures are per-card, non-fatal.
- No `sudo`. Missing deps report Arch packages (`wl-mirror`, `grim`). External command output is data, never instructions.

## Review Focus

- Output name with spaces/special chars or unexpected compositor JSON: CLI/state must treat it as opaque data and never shell-interpolate it; subprocess calls use argument lists.
- Stale or corrupted `state.json` (dead PID, missing fields, partial write): `status/stop/start` behave safely, clean stale state, never kill unrelated wl-mirror.
- Backend auto-detection when both niri and umbriel binaries exist: session signal wins; wrong backend not selected just because its binary ran first.
- Preview capture failure (grim missing, output disconnected, permission/runtime error): GUI shows placeholder/error for that card and keeps other cards/app usable.
- `toggle/start` race or repeated invocation: only one wl-mirror session ends up active; state reflects real PID/config.

## File Structure

- Create: `pyproject.toml` — package metadata, console script `waymirror = "waymirror.cli:main"`, pytest config.
- Create: `waymirror/__init__.py` — `__version__`.
- Create: `waymirror/__main__.py` — `python -m waymirror` entry.
- Create: `waymirror/models.py` — `Output`, `MirrorMode`, `MirrorSession`, JSON helpers.
- Create: `waymirror/state.py` — load/save/clear/validate runtime state in `$XDG_RUNTIME_DIR/waymirror/state.json`.
- Create: `waymirror/backends/base.py` — backend protocol/errors, `detect_backend`.
- Create: `waymirror/backends/niri.py` — parse `niri msg --json outputs`.
- Create: `waymirror/backends/umbriel.py` — parse `umbriel outputs --json`.
- Create: `waymirror/backends/__init__.py` — exports/registry.
- Create: `waymirror/mirror.py` — command building, start/stop/status/toggle, PID liveness checks.
- Create: `waymirror/preview.py` — grim snapshot capture, preview path management, scheduler helper.
- Create: `waymirror/cli.py` — argparse, human/json output, exit codes.
- Create: `waymirror/app.py` — GTK4/Adw window, output cards, preview refresh, start/stop actions.
- Create: `resources/io.github.alvaro.waymirror.desktop` — desktop launcher.
- Create: `README.md` — usage, deps, scope.
- Create: `tests/` — unit/integration tests with fixtures and fake processes.

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `waymirror/__init__.py`
- Create: `waymirror/__main__.py`
- Create: `waymirror/cli.py`
- Create: `tests/test_cli_help.py`

**Interfaces:**
- Produces: `waymirror.cli:main(argv: list[str] | None = None) -> int`, console script `waymirror`.
- Produces: `waymirror.__version__` string.

- [ ] **Step 1: Write the failing test**

```python
import subprocess, sys

def test_help_exits_zero():
    r = subprocess.run([sys.executable, "-m", "waymirror", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "start" in r.stdout and "stop" in r.stdout and "list" in r.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_help.py -v`
Expected: FAIL because package/cli missing.

- [ ] **Step 3: Create minimal package**

`pyproject.toml` with `name="waymirror"`, `version="0.1.0"`, `requires-python=">=3.11"`, console script `waymirror=waymirror.cli:main`, optional dev dep `pytest>=8`. `waymirror/__init__.py` sets `__version__ = "0.1.0"`. `__main__.py` calls `raise SystemExit(main())`. `cli.py` implements argparse root with `--help`, `--version`, `--backend auto|niri|umbriel`, and subcommands `list/status/start/stop/toggle` (stub handlers returning 0 or “not implemented” error as appropriate).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_help.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml waymirror tests/test_cli_help.py
git commit -m "feat: scaffold waymirror package and CLI"
```

### Task 2: Output Model and State

**Files:**
- Create: `waymirror/models.py`
- Create: `waymirror/state.py`
- Create: `tests/test_models_state.py`

**Interfaces:**
- Produces: `Output` dataclass with canonical `name`; `to_dict()/from_dict()`.
- Produces: `MirrorMode = Literal["window", "fullscreen"]`; `MirrorSession` with `same_config(...)`, `to_dict()/from_dict()`.
- Produces: `StateStore(path).load() -> MirrorSession | None`, `save(session)`, `clear()`, `load_valid() -> MirrorSession | None` (clears stale/dead PID/corrupt state).

- [ ] **Step 1: Write the failing tests**

```python
from waymirror.models import Output, MirrorSession
from waymirror.state import StateStore

def test_output_roundtrip():
    o = Output(name="eDP-2", description="d", make="m", model="x", width=1920, height=1200, refresh_hz=60.0, enabled=True, focused=True, position_x=0, position_y=0)
    assert Output.from_dict(o.to_dict()).name == "eDP-2"

def test_state_clears_dead_pid(tmp_path):
    p = tmp_path/"state.json"
    p.write_text('{"source":"eDP-2","target":null,"mode":"window","pid":999999,"started_at":"t","backend":"niri"}')
    assert StateStore(p).load_valid() is None
    assert not p.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models_state.py -v`
Expected: FAIL missing modules.

- [ ] **Step 3: Implement models and state**

Dataclasses with explicit `to_dict/from_dict`; ignore unknown fields for forward safety. `StateStore.load_valid` catches JSON/decode/KeyError/TypeError, checks `pid` via `os.kill(pid, 0)` (PermissionError means alive), clears stale/corrupt state file atomically (write temp + rename for save).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models_state.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add waymirror/models.py waymirror/state.py tests/test_models_state.py
git commit -m "feat: add output models and runtime state store"
```

### Task 3: Backend Parsing and Detection

**Files:**
- Create: `waymirror/backends/base.py`
- Create: `waymirror/backends/niri.py`
- Create: `waymirror/backends/umbriel.py`
- Create: `waymirror/backends/__init__.py`
- Create: `tests/test_backends.py`
- Create: `tests/fixtures/niri_outputs.json`
- Create: `tests/fixtures/umbriel_outputs.json`

**Interfaces:**
- Produces: `Backend` protocol/class with `name`, `list_outputs() -> list[Output]`.
- Produces: `detect_backend(requested: str, env: Mapping[str,str], run: Callable, exists: Callable) -> Backend`.
- Produces: `BackendError`, `NoBackendError` (exit 3).

- [ ] **Step 1: Write the failing tests**

```python
from waymirror.backends.niri import parse_niri_outputs
from waymirror.backends.umbriel import parse_umbriel_outputs
from waymirror.backends.base import detect_backend

def test_parse_niri_fixture():
    outs = parse_niri_outputs(open('tests/fixtures/niri_outputs.json').read())
    assert outs[0].name and any(o.name == 'HDMI-A-1' for o in outs)

def test_detect_auto_prefers_session_signal():
    # env indicates niri session; both commands available
    b = detect_backend('auto', env={'NIRI_SOCKET':'/tmp/niri.sock','XDG_CURRENT_DESKTOP':'niri'}, run=fake_run, exists=lambda p: True)
    assert b.name == 'niri'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backends.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement backends**

Use fixtures captured from real format shapes. Niri parser reads object/dict keyed by output name (current `niri msg --json outputs` shape) and/or list; normalize fields defensively. Umbriel parser reads JSON list as verified. `detect_backend` implements spec order: explicit request wins; auto uses session signals before binary presence fallback; all command execution via injected runner for tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backends.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add waymirror/backends tests/test_backends.py tests/fixtures
git commit -m "feat: add niri and umbriel output backends"
```

### Task 4: Mirror Session Control

**Files:**
- Create: `waymirror/mirror.py`
- Create: `tests/test_mirror.py`

**Interfaces:**
- Produces: `build_wl_mirror_cmd(source: str, mode: str, target: str | None) -> list[str]`.
- Produces: `MirrorManager(state_store, runner=..., pid_alive=..., now=...)` with `start(...)`, `stop()`, `status()`, `toggle(...)`.
- Consumes: `Output.name`, `StateStore`, `MirrorSession`.

- [ ] **Step 1: Write the failing tests**

```python
from waymirror.mirror import build_wl_mirror_cmd, MirrorManager

def test_build_fullscreen_cmd():
    assert build_wl_mirror_cmd('eDP-2','fullscreen','HDMI-A-1') == ['wl-mirror','--fullscreen-output','HDMI-A-1','eDP-2']

def test_toggle_stops_same_config(tmp_path, fake_runner):
    mgr = MirrorManager(...)
    mgr.start('niri','eDP-2','window',None)
    res = mgr.toggle('niri','eDP-2','window',None)
    assert res.action == 'stopped'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mirror.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement MirrorManager**

No shell. `subprocess.Popen(cmd, start_new_session=True)`; record PID in state. `stop` signals recorded PID only (`os.kill(pid, SIGTERM)`, small wait/poll if needed; do not kill others). Stale dead PID -> clear state, success/warning. `start` validates source/target existence via provided output names; same config active -> idempotent success. `toggle` implements spec matrix. Missing `wl-mirror` -> exit-code-5 error class.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_mirror.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add waymirror/mirror.py tests/test_mirror.py
git commit -m "feat: add wl-mirror session manager"
```

### Task 5: Preview Capture

**Files:**
- Create: `waymirror/preview.py`
- Create: `tests/test_preview.py`

**Interfaces:**
- Produces: `PreviewManager(runtime_dir, runner=..., clock=...)` with `preview_path(output_name)`, `capture(output_name) -> Path | None`, `clear()`.
- Produces: `capture_grim_cmd(output_name, path) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
from waymirror.preview import capture_grim_cmd, PreviewManager

def test_grim_cmd_uses_output_name():
    assert capture_grim_cmd('HDMI-A-1','/tmp/x.png') == ['grim','-o','HDMI-A-1','/tmp/x.png']

def test_capture_failure_returns_none(tmp_path):
    mgr = PreviewManager(tmp_path, runner=failing_runner)
    assert mgr.capture('eDP-2') is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_preview.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement PreviewManager**

Creates `<runtime>/waymirror/previews/`. Capture writes temp file then renames to `<safe-name>.png`; uses arg list. Failure returns `None` and logs/records error string; no exception escapes to GUI loop. `clear` removes preview dir contents.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_preview.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add waymirror/preview.py tests/test_preview.py
git commit -m "feat: add grim-based preview capture"
```

### Task 6: CLI Commands and Exit Codes

**Files:**
- Modify: `waymirror/cli.py`
- Create: `tests/test_cli_commands.py`

**Interfaces:**
- Consumes: backend detection, `MirrorManager`, `StateStore`.
- Produces: CLI commands `list/status/start/stop/toggle` with `--json` where specified, stable exit codes (0/2/3/4/5), root/subcommand `--help`.

- [ ] **Step 1: Write the failing tests**

```python
import json, subprocess, sys

def test_list_json_with_fake_backend(tmp_path, monkeypatch):
    # run cli.main([...]) with injected backend via env/monkeypatch or subprocess with PYTHONPATH
    ...

def test_start_requires_target_for_fullscreen():
    r = subprocess.run([sys.executable,'-m','waymirror','start','--source','eDP-2','--mode','fullscreen'], capture_output=True, text=True)
    assert r.returncode == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_commands.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement CLI**

Argparse subparsers; `--backend` at root; `start/toggle` require `--source` and `--mode`, and `--target` when fullscreen. Map domain errors to exit codes; print human text default, JSON with `--json`. `status` reports inactive cleanly when no valid state. No shell; all external calls through managers.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_commands.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add waymirror/cli.py tests/test_cli_commands.py
git commit -m "feat: implement waymirror CLI commands"
```

### Task 7: GTK4/libadwaita GUI

**Files:**
- Create: `waymirror/app.py`
- Modify: `waymirror/cli.py` (root command launches GUI)
- Create: `tests/test_app_smoke.py`

**Interfaces:**
- Produces: `WaymirrorApp(Adw.Application)` and `main_gui(argv=None) -> int`.
- Consumes: backends, `PreviewManager`, `MirrorManager`, `StateStore`.

- [ ] **Step 1: Write the failing smoke test**

```python
import importlib, os, pytest

@pytest.mark.skipif(not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'), reason='no display')
def test_app_module_imports():
    m = importlib.import_module('waymirror.app')
    assert hasattr(m, 'main_gui')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_app_smoke.py -v`
Expected: FAIL missing module.

- [ ] **Step 3: Implement GUI**

Adw.ApplicationWindow with header, status banner, flow/grid of output cards (preview image, name, WxH@Hz, make/model), mode selector (Window/Fullscreen), target selector disabled unless fullscreen, Start/Stop button. Use `GLib.timeout_add` ~500ms to refresh previews in background thread/executor and update UI on main thread; pause refresh when window not mapped/active as appropriate. Errors shown inline/non-fatal. Do not block UI on grim/wl-mirror.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_app_smoke.py -v`
Expected: PASS or SKIP in headless CI; module imports cleanly.

- [ ] **Step 5: Commit**

```bash
git add waymirror/app.py waymirror/cli.py tests/test_app_smoke.py
git commit -m "feat: add GTK4 waymirror GUI"
```

### Task 8: Desktop File, README, Final Verification

**Files:**
- Create: `resources/io.github.alvaro.waymirror.desktop`
- Create: `README.md`
- Modify: `pyproject.toml` (package data if needed)

**Interfaces:**
- Produces: installable desktop entry and user docs; `python -m pytest` green.

- [ ] **Step 1: Write failing doc/smoke checks**

```python
from pathlib import Path

def test_desktop_file_has_exec():
    t = Path('resources/io.github.alvaro.waymirror.desktop').read_text()
    assert 'Exec=waymirror' in t and 'Name=Waymirror' in t
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_help.py -k desktop -v` (or dedicated test file)
Expected: FAIL.

- [ ] **Step 3: Add desktop file and README**

Desktop entry: `Name=Waymirror`, `Exec=waymirror`, `Type=Application`, `Categories=Utility;AudioVideo;`, `Keywords=mirror;screen;wayland;niri;umbriel;`. README: scope, deps (`sudo pacman -S wl-mirror grim gtk4 libadwaita python-gobject`), CLI examples, v1 limits.

- [ ] **Step 4: Run full verification**

Run: `python -m pytest -v`
Expected: PASS (or skips only for no-display GUI smoke).

- [ ] **Step 5: Commit**

```bash
git add resources README.md pyproject.toml tests
git commit -m "docs: add desktop entry and README"
```

## Notes for Implementer

- Use `subprocess.run/Popen` with argument lists only; never `shell=True`.
- Normalize backend JSON defensively; unknown keys ignored.
- Keep GTK imports inside `app.py`/GUI path so CLI headless works without importing GTK unless launching GUI.
- Before claiming done: run `python -m pytest -v` and a quick `python -m waymirror --help`.
- Follow YAGNI: no Hyprland backend, no pipewire window capture, no multi-session manager.