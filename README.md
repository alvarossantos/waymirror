# Waymirror

Waymirror is a standalone Wayland screen-mirroring app for **niri** and **umbriel**.
It mirrors one output (for example `eDP-2`) or a window to a normal window or
fullscreen on another output, using `wl-mirror` as the engine. A GTK4/libadwaita
GUI shows previews; a headless CLI exposes the same session state for keybinds
and scripts.

## Scope

- Wayland sessions on niri and umbriel only.
- Output and window sources are supported on niri and umbriel.
- Exactly one mirror session at a time, shared between GUI and CLI via
  `$XDG_RUNTIME_DIR/waymirror/state.json` (fallback: `/tmp/waymirror-$UID/state.json`).
- No `sudo` in app behavior; missing dependencies are reported with Arch package names.

## Requirements

- A Wayland session on niri or umbriel.
- Python 3.11+ and the following Arch packages:

```bash
sudo pacman -S wl-mirror grim gtk4 libadwaita python-gobject
```

Use `wl-mirror` 0.18.5 or newer from the package above.

`python-gobject` provides the `gi` module used by the GUI. The CLI subcommands
(`list`, `status`, `start`, `stop`, `toggle`) work headlessly without GTK; GTK is
imported only when the GUI is launched. If you install into a virtual environment,
create it with `--system-site-packages` (or install PyGObject in it) so the GUI can
see the system GI modules.

## Install from source

```bash
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -e .
```

The editable install places the `waymirror` console script in `.venv/bin`, which
is not on PATH. Link it into `~/.local/bin` so the desktop entry and the commands
below can find it:

```bash
mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/.venv/bin/waymirror" "$HOME/.local/bin/waymirror"
```

If `$HOME/.local/bin` is not already on your PATH, add
`export PATH="$HOME/.local/bin:$PATH"` to your shell profile and restart the
session.

For running the test suite, install the dev extra:

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

To register the launcher without `sudo`, install the desktop entry at user level:

```bash
install -Dm644 resources/io.github.alvaro.waymirror.desktop \
  "$HOME/.local/share/applications/io.github.alvaro.waymirror.desktop"
```

## Usage

Launch the GUI (no arguments) and pick a source output, a mode, and — for
fullscreen — a target output. The commands below assume the `~/.local/bin`
symlink from Install is on PATH; without it, replace `waymirror` with
`.venv/bin/python -m waymirror`:

```bash
waymirror
.venv/bin/python -m waymirror  # equivalent, no console script needed
waymirror --help
waymirror --version
```

The CLI uses output connector names from `waymirror list`; the same name is used
in state, `grim -o`, and `wl-mirror`:

```bash
waymirror list
waymirror list --json
waymirror list windows
waymirror list windows --json
waymirror status
waymirror status --json
waymirror start --source eDP-2 --mode window
waymirror start --source eDP-2 --mode fullscreen --target HDMI-A-1
waymirror start --window 42 --mode window
waymirror start --window 42 --mode fullscreen --target eDP-2
waymirror toggle --source eDP-2 --mode fullscreen --target HDMI-A-1
waymirror stop
```

`list windows` enumerates compositor windows; IDs are the canonical selectors
for `start --window`. The window capture passes the window's current screen region
to `wl-mirror -r`. This captures pixels from the screen region, not an isolated
window surface: a covered or minimized window is not captured independently.
The region is fixed when mirroring starts. Moving or resizing the window causes
drift; stop and start again to use its new geometry. In fullscreen mode,
`--target` must be an output other than the output containing the source window.

`start` is idempotent for the same config and replaces a different active config.
`toggle` starts when inactive, stops when the same config is active, and replaces
a different active config. `stop` signals only the PID recorded in state; stale or
corrupt state is cleared safely. Select the compositor explicitly with
`--backend auto|niri|umbriel` before the subcommand (default: `auto`, which uses
session signals first). Exit codes: `0` success, `2` usage error, `3` no supported
backend, `4` output not found, `5` execution failure (missing `wl-mirror`, failed
stop, or an unexpected internal error).

In fullscreen mode, waymirror reveals the `wl-mirror` window after spawn. If the
compositor placed it on another output, the window is moved to a workspace on
the target output; that workspace is then activated via niri/umbriel IPC. If the
IPC call fails, mirroring stays active and the warning is shown in the CLI/GUI.

Preview snapshots live under `$XDG_RUNTIME_DIR/waymirror/previews/` and are
captured at roughly 2 fps while the GUI is visible: output previews use
`grim -o <output>`, and window previews use `grim -g <region>`.

## v1 limitations

- No Hyprland, sway, GNOME, KDE, or X11 support.
- Window mirroring uses a screen region; there is no portal/pipewire capture or
  automatic tracking. The niri window JSON shape has not been verified on this
  machine; an unrecognized response produces a warning and an empty list.
- No multiple simultaneous sessions, no `--force`, and no `pkill -x wl-mirror`.
- Previews are periodic snapshots, not a continuous stream.
- No custom app icon or official AUR package yet; the desktop entry uses the
  standard `video-display` icon.

## License

MIT — see [LICENSE](LICENSE).

## Tests

```bash
.venv/bin/python -m pytest -v
```

GUI import smoke tests are skipped when no `DISPLAY`/`WAYLAND_DISPLAY` is set;
all other tests run headlessly.
