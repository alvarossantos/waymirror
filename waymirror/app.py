"""GTK4/libadwaita GUI for waymirror."""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

from .backends.base import BackendError, NoBackendError, detect_backend
from .mirror import MirrorManager, MirrorStopError, MirrorValidationError, OutputNotFoundError, WlMirrorMissingError
from .models import MirrorMode, Output, SourceKind, Window
from .preview import PreviewManager
from .state import StateStore

logger = logging.getLogger(__name__)

_GTK_AVAILABLE = False
_GTK_IMPORT_ERROR: Exception | None = None

try:  # pragma: no cover - depends on system GI
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk

    _GTK_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on system GI
    Adw = None  # type: ignore[assignment]
    Gdk = None  # type: ignore[assignment]
    GLib = None  # type: ignore[assignment]
    Gtk = None  # type: ignore[assignment]
    _GTK_IMPORT_ERROR = exc


def default_state_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "waymirror" / "state.json"
    return Path("/tmp") / f"waymirror-{os.getuid()}" / "state.json"


def default_runtime_dir() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime)
    return Path("/tmp") / f"waymirror-{os.getuid()}"


def _format_output_label(output: Output) -> str:
    size = f"{output.width}x{output.height}" if output.width and output.height else "unknown"
    rate = f"@{output.refresh_hz:g}Hz" if output.refresh_hz else ""
    desc = output.description or " ".join(part for part in [output.make, output.model] if part)
    details = f"{size}{rate}"
    if desc:
        details += f" - {desc}"
    return f"{output.name} ({details})"


if _GTK_AVAILABLE:

    class OutputCard(Gtk.Box):
        def __init__(self, output: Output) -> None:
            super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            self.output = output
            self.add_css_class("card")
            self.set_margin_top(6)
            self.set_margin_bottom(6)
            self.set_margin_start(6)
            self.set_margin_end(6)

            self.picture = Gtk.Picture()
            self.picture.set_size_request(320, 180)
            self.picture.set_can_shrink(True)
            self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            self.picture.set_hexpand(True)
            self.picture.set_vexpand(True)

            self.name_label = Gtk.Label(label=output.name)
            self.name_label.add_css_class("heading")
            self.name_label.set_halign(Gtk.Align.START)

            size = f"{output.width}x{output.height}" if output.width and output.height else "unknown"
            rate = f"@{output.refresh_hz:g}Hz" if output.refresh_hz else ""
            self.meta_label = Gtk.Label(label=f"{size}{rate}")
            self.meta_label.set_halign(Gtk.Align.START)
            self.meta_label.add_css_class("dim-label")

            desc = output.description or " ".join(part for part in [output.make, output.model] if part).strip()
            self.desc_label = Gtk.Label(label=desc or " ")
            self.desc_label.set_halign(Gtk.Align.START)
            self.desc_label.set_wrap(True)
            self.desc_label.set_xalign(0)
            self.desc_label.add_css_class("dim-label")

            self.error_label = Gtk.Label(label="")
            self.error_label.set_halign(Gtk.Align.START)
            self.error_label.set_wrap(True)
            self.error_label.set_xalign(0)
            self.error_label.add_css_class("error")

            self.append(self.picture)
            self.append(self.name_label)
            self.append(self.meta_label)
            self.append(self.desc_label)
            self.append(self.error_label)

        def set_preview(self, path: Path | None, error: str | None) -> None:
            if path is not None and path.exists():
                try:
                    texture = Gdk.Texture.new_from_filename(str(path))
                except Exception:
                    texture = None
                if texture is not None:
                    self.picture.set_paintable(texture)
            if error:
                self.error_label.set_text(error)
                self.error_label.set_visible(True)
            else:
                self.error_label.set_text("")
                self.error_label.set_visible(False)


    class WindowCard(Gtk.Box):
        def __init__(self, window: Window) -> None:
            super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            self.window = window
            self.add_css_class("card")
            for method in ("set_margin_top", "set_margin_bottom", "set_margin_start", "set_margin_end"):
                getattr(self, method)(6)
            self.picture = Gtk.Picture()
            self.picture.set_size_request(320, 180)
            self.picture.set_can_shrink(True)
            self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            self.picture.set_hexpand(True)
            self.picture.set_vexpand(True)
            name = window.app_id or window.title or window.id
            self.name_label = Gtk.Label(label=name)
            self.name_label.add_css_class("heading")
            self.name_label.set_halign(Gtk.Align.START)
            self.title_label = Gtk.Label(label=window.title or " ")
            self.title_label.set_halign(Gtk.Align.START)
            self.title_label.set_wrap(True)
            self.title_label.set_xalign(0)
            self.title_label.add_css_class("dim-label")
            self.meta_label = Gtk.Label(label=f"{window.w}x{window.h}")
            self.meta_label.set_halign(Gtk.Align.START)
            self.meta_label.add_css_class("dim-label")
            self.error_label = Gtk.Label(label="")
            self.error_label.set_halign(Gtk.Align.START)
            self.error_label.set_wrap(True)
            self.error_label.set_xalign(0)
            self.error_label.add_css_class("error")
            for child in (self.picture, self.name_label, self.title_label, self.meta_label, self.error_label):
                self.append(child)

        def set_preview(self, path: Path | None, error: str | None) -> None:
            if path is not None and path.exists():
                try:
                    texture = Gdk.Texture.new_from_filename(str(path))
                except Exception:
                    texture = None
                if texture is not None:
                    self.picture.set_paintable(texture)
            self.error_label.set_text(error or "")
            self.error_label.set_visible(bool(error))

        def update_meta(self, window: Window) -> None:
            self.window = window
            self.name_label.set_label(window.app_id or window.title or window.id)
            self.title_label.set_label(window.title or " ")
            self.meta_label.set_label(f"{window.w}x{window.h}")


    class WaymirrorWindow(Adw.ApplicationWindow):
        def __init__(
            self,
            app: Adw.Application,
            *,
            backend_name: str = "auto",
            state_store: StateStore | None = None,
            preview_manager: PreviewManager | None = None,
            mirror_manager: MirrorManager | None = None,
        ) -> None:
            super().__init__(application=app)
            self.set_title("Waymirror")
            self.set_default_size(1000, 700)

            self.backend_name = backend_name
            self.backend = None
            self.outputs: list[Output] = []
            self.windows: list[Window] = []
            self.window_error: str | None = None
            self.cards: dict[str, OutputCard | WindowCard] = {}
            self.preview_paths: dict[str, Path | None] = {}
            self._refresh_pending = False
            self._preview_inflight = False
            self._refresh_timer_id: int | None = None
            self._closed = False
            self._status_warning: str | None = None
            self._action_error: str | None = None

            self.state_store = state_store or StateStore(default_state_path())
            self.preview_manager = preview_manager or PreviewManager(default_runtime_dir())
            self.mirror_manager = mirror_manager or MirrorManager(self.state_store)

            self._build_ui()
            self.connect("map", lambda *_: self._ensure_refresh_timer())
            self.connect("unmap", lambda *_: self._stop_refresh_timer())
            self.connect("close-request", self._on_close_request)

            self._load_outputs()
            self._refresh_status()
            self._ensure_refresh_timer()

        def _build_ui(self) -> None:
            toolbar = Adw.ToolbarView()
            header = Adw.HeaderBar()
            title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            title = Gtk.Label(label="Waymirror")
            title.add_css_class("title")
            subtitle = Gtk.Label(label="Wayland screen mirroring")
            subtitle.add_css_class("dim-label")
            title_box.append(title)
            title_box.append(subtitle)
            header.set_title_widget(title_box)
            toolbar.add_top_bar(header)

            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            content.set_margin_top(12)
            content.set_margin_bottom(12)
            content.set_margin_start(12)
            content.set_margin_end(12)

            self.banner = Adw.Banner(title="")
            self.banner.set_revealed(False)
            content.append(self.banner)

            controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            controls.set_halign(Gtk.Align.FILL)

            self.kind_model = Gtk.StringList.new(["Output", "Window"])
            self.kind_dropdown = Gtk.DropDown(model=self.kind_model)
            self.kind_dropdown.connect("notify::selected", lambda *_: self._rebuild_outputs_ui())

            self.source_model = Gtk.StringList()
            self.source_dropdown = Gtk.DropDown(model=self.source_model)
            self.source_dropdown.set_hexpand(True)
            self.source_dropdown.connect("notify::selected", lambda *_: self._on_source_changed())

            self.mode_model = Gtk.StringList.new(["Window", "Fullscreen"])
            self.mode_dropdown = Gtk.DropDown(model=self.mode_model)
            self.mode_dropdown.connect("notify::selected", lambda *_: self._update_target_sensitivity())

            self.target_model = Gtk.StringList()
            self.target_dropdown = Gtk.DropDown(model=self.target_model)
            self.target_dropdown.set_hexpand(True)

            self.start_stop_button = Gtk.Button(label="Start")
            self.start_stop_button.add_css_class("suggested-action")
            self.start_stop_button.connect("clicked", lambda *_: self._on_start_stop())

            controls.append(Gtk.Label(label="Kind"))
            controls.append(self.kind_dropdown)
            controls.append(Gtk.Label(label="Source"))
            controls.append(self.source_dropdown)
            controls.append(Gtk.Label(label="Mode"))
            controls.append(self.mode_dropdown)
            controls.append(Gtk.Label(label="Target"))
            controls.append(self.target_dropdown)
            controls.append(self.start_stop_button)
            content.append(controls)

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_vexpand(True)
            scrolled.set_hexpand(True)
            self.flow = Gtk.FlowBox()
            self.flow.set_valign(Gtk.Align.START)
            self.flow.set_max_children_per_line(4)
            self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
            scrolled.set_child(self.flow)
            content.append(scrolled)

            toolbar.set_content(content)
            self.set_content(toolbar)
            self._update_target_sensitivity()

        def _render_banner(self) -> None:
            message = self._action_error or self._status_warning or ""
            self.banner.set_title(message)
            self.banner.set_revealed(bool(message))

        def _set_action_error(self, message: str | None) -> None:
            self._action_error = message or None
            self._render_banner()

        def _set_status_warning(self, message: str | None) -> None:
            self._status_warning = message or None
            self._render_banner()

        def _show_error(self, message: str) -> None:
            self._set_action_error(message)

        def _clear_error(self) -> None:
            self._set_action_error(None)

        def _load_outputs(self) -> None:
            try:
                self.backend = detect_backend(self.backend_name)
                self.outputs = self.backend.list_outputs()
                self._set_action_error(None)
            except (NoBackendError, BackendError) as exc:
                self.backend = None
                self.outputs = []
                self._set_action_error(str(exc))
            except Exception as exc:  # noqa: BLE001 - GUI must stay alive
                self.backend = None
                self.outputs = []
                self._set_action_error(f"Failed to load outputs: {exc}")
            self._load_sources()

        def _load_sources(self) -> None:
            self.windows = []
            self.window_error = None
            if self.backend is not None:
                try:
                    self.windows = [window for window in self.backend.list_windows() if window.is_capturable()]
                except Exception as exc:  # noqa: BLE001 - window discovery must not hide outputs
                    self.window_error = str(exc)
                    self._set_action_error(f"Failed to load windows: {exc}")
            self._rebuild_outputs_ui()

        def _rebuild_outputs_ui(self) -> None:
            while True:
                child = self.flow.get_first_child()
                if child is None:
                    break
                self.flow.remove(child)
            self.cards.clear()

            is_window = self._selected_kind() == "window"
            sources = self.windows if is_window else self.outputs
            labels = [f"{w.app_id or w.title or w.id} — {w.title or w.id}" for w in self.windows] if is_window else [o.name for o in self.outputs]
            self.source_model.splice(0, self.source_model.get_n_items(), labels)
            self.target_model.splice(0, self.target_model.get_n_items(), [o.name for o in self.outputs])

            for source in sources:
                if is_window:
                    card = WindowCard(source)
                    key = f"window:{source.id}"
                else:
                    card = OutputCard(source)
                    key = source.name
                self.cards[key] = card
                self.flow.append(card)

            if sources:
                if self.source_dropdown.get_selected() == Gtk.INVALID_LIST_POSITION or self.source_dropdown.get_selected() >= len(sources):
                    self.source_dropdown.set_selected(0)
            else:
                self.source_dropdown.set_selected(Gtk.INVALID_LIST_POSITION)
            if self.outputs:
                if self.target_dropdown.get_selected() == Gtk.INVALID_LIST_POSITION:
                    # Prefer a different target than source when possible.
                    self.target_dropdown.set_selected(1 if len(self.outputs) > 1 else 0)
            self._ensure_distinct_target()
            self._update_target_sensitivity()

        def _selected_source(self) -> str | None:
            idx = self.source_dropdown.get_selected()
            sources = self.windows if self._selected_kind() == "window" else self.outputs
            if idx == Gtk.INVALID_LIST_POSITION or idx < 0 or idx >= len(sources):
                return None
            return sources[idx].id if self._selected_kind() == "window" else sources[idx].name

        def _selected_kind(self) -> SourceKind:
            dropdown = getattr(self, "kind_dropdown", None)
            return "window" if dropdown is not None and dropdown.get_selected() == 1 else "output"

        def _selected_window(self) -> Window | None:
            if self._selected_kind() != "window" or not getattr(self, "windows", None):
                return None
            idx = self.source_dropdown.get_selected()
            if idx == Gtk.INVALID_LIST_POSITION or idx < 0 or idx >= len(self.windows):
                return None
            return self.windows[idx]

        def _selected_target(self) -> str | None:
            idx = self.target_dropdown.get_selected()
            if idx == Gtk.INVALID_LIST_POSITION or idx < 0 or idx >= len(self.outputs):
                return None
            return self.outputs[idx].name

        def _selected_mode(self) -> MirrorMode:
            return "fullscreen" if self.mode_dropdown.get_selected() == 1 else "window"

        def _ensure_distinct_target(self) -> None:
            if self._selected_kind() != "output" or len(self.outputs) < 2:
                return
            source = self._selected_source()
            if source is None or self._selected_target() != source:
                return
            index = next((i for i, output in enumerate(self.outputs) if output.name != source), None)
            if index is not None:
                self.target_dropdown.set_selected(index)

        def _on_source_changed(self) -> None:
            self._ensure_distinct_target()
            self._update_target_sensitivity()

        def _update_target_sensitivity(self) -> None:
            fullscreen = self._selected_mode() == "fullscreen"
            self.target_dropdown.set_sensitive(fullscreen and len(self.outputs) > 1)

        def _refresh_status(self) -> None:
            try:
                result = self.mirror_manager.status()
            except Exception as exc:  # noqa: BLE001
                self._set_status_warning(f"Status error: {exc}")
                return
            self._set_status_warning(result.warning)
            if result.active and result.session is not None:
                self.start_stop_button.set_label("Stop")
                self.start_stop_button.remove_css_class("suggested-action")
                self.start_stop_button.add_css_class("destructive-action")
            else:
                self.start_stop_button.set_label("Start")
                self.start_stop_button.remove_css_class("destructive-action")
                self.start_stop_button.add_css_class("suggested-action")

        def _on_start_stop(self) -> None:
            try:
                status = self.mirror_manager.status()
            except Exception as exc:  # noqa: BLE001
                self._set_action_error(f"Status error: {exc}")
                self._refresh_status()
                return

            if status.active and status.session is not None:
                try:
                    result = self.mirror_manager.stop()
                except (MirrorStopError, Exception) as exc:  # noqa: BLE001
                    self._set_action_error(str(exc))
                    self._refresh_status()
                    return
                if result.warning:
                    self._set_action_error(result.warning)
                else:
                    self._set_action_error(None)
                self._refresh_status()
                return

            source_kind = self._selected_kind()
            source = self._selected_source()
            if not source:
                self._set_action_error("Select a source window" if source_kind == "window" else "Select a source output")
                return
            selected_window = self._selected_window()
            if source_kind == "window" and (selected_window is None or not selected_window.is_capturable()):
                self._set_action_error("Select a capturable source window")
                return
            mode = self._selected_mode()
            target = self._selected_target() if mode == "fullscreen" else None
            if mode == "fullscreen" and not target:
                self._set_action_error("Select a target output for fullscreen mode")
                return
            backend_name = self.backend.name if self.backend is not None else self.backend_name
            available = [o.name for o in self.outputs]
            try:
                result = self.mirror_manager.start(
                    backend_name,
                    source,
                    mode,
                    target,
                    available_outputs=available,
                    source_kind=source_kind,
                    available_windows=self.windows if source_kind == "window" else None,
                )
            except (OutputNotFoundError, MirrorValidationError, WlMirrorMissingError, MirrorStopError, Exception) as exc:  # noqa: BLE001
                self._set_action_error(str(exc))
                self._refresh_status()
                return
            if result.warning:
                self._set_action_error(result.warning)
            else:
                self._set_action_error(None)
            self._refresh_status()

        def _ensure_refresh_timer(self) -> None:
            if self._closed or self._refresh_timer_id is not None:
                return
            if not self.get_mapped():
                return
            self._refresh_timer_id = GLib.timeout_add(500, self._on_refresh_tick)

        def _stop_refresh_timer(self) -> None:
            if self._refresh_timer_id is not None:
                GLib.source_remove(self._refresh_timer_id)
                self._refresh_timer_id = None

        def _refresh_window_geometry(self) -> None:
            if self._selected_kind() != "window" or self.backend is None:
                return
            try:
                fresh = [window for window in self.backend.list_windows() if window.is_capturable()]
            except Exception:  # noqa: BLE001 - keep last known geometry on backend failure
                return
            fresh_by_id = {window.id: window for window in fresh}
            if set(fresh_by_id) != {window.id for window in self.windows}:
                self._load_sources()
                return
            for window in self.windows:
                updated = fresh_by_id[window.id]
                window.x = updated.x
                window.y = updated.y
                window.w = updated.w
                window.h = updated.h
                window.title = updated.title
                window.app_id = updated.app_id
                window.output = updated.output
                card = self.cards.get(f"window:{window.id}")
                if card is not None:
                    card.update_meta(window)

        def _on_refresh_tick(self) -> bool:
            if self._closed or not self.get_mapped():
                self._refresh_timer_id = None
                return False
            self._refresh_status()
            self._refresh_window_geometry()
            self._schedule_preview_refresh()
            return True

        def _schedule_preview_refresh(self) -> None:
            if self._refresh_pending or self._preview_inflight or not (self.outputs or self.windows):
                return
            self._refresh_pending = True
            self._preview_inflight = True
            output_names = [o.name for o in self.outputs]
            windows = list(self.windows) if self._selected_kind() == "window" else []
            try:
                status = self.mirror_manager.status()
                session = status.session if status.active else None
            except Exception:
                session = None
            window_regions = {window.id: self._window_region_for_preview(window, session) for window in windows}
            preview_manager = self.preview_manager

            def worker() -> None:
                results: dict[str, tuple[Path | None, str | None]] = {}
                for name in output_names:
                    try:
                        path = preview_manager.capture(name)
                        err = preview_manager.errors.get(name)
                    except Exception as exc:  # noqa: BLE001
                        path = None
                        err = str(exc)
                    results[name] = (path, err)
                for window in windows:
                    name = f"window:{window.id}"
                    try:
                        path = preview_manager.capture(name, region=window_regions[window.id])
                        err = preview_manager.errors.get(name)
                    except Exception as exc:  # noqa: BLE001
                        path = None
                        err = str(exc)
                    results[name] = (path, err)
                GLib.idle_add(self._apply_preview_results, results)

            try:
                threading.Thread(target=worker, daemon=True).start()
            except Exception as exc:  # noqa: BLE001
                self._refresh_pending = False
                self._preview_inflight = False
                logger.exception("failed to start preview refresh worker")
                self._set_action_error(f"Preview refresh failed: {exc}")

        @staticmethod
        def _window_region_for_preview(window: Window, session: Any = None) -> str:
            if session is not None and getattr(session, "source_kind", "output") == "window" and getattr(session, "source", None) == window.id and getattr(session, "region", None):
                return session.region
            return window.grim_region()

        def _apply_preview_results(self, results: dict[str, tuple[Path | None, str | None]]) -> bool:
            self._refresh_pending = False
            self._preview_inflight = False
            if self._closed:
                return False
            for name, (path, err) in results.items():
                self.preview_paths[name] = path
                card = self.cards.get(name)
                if card is not None:
                    card.set_preview(path, err)
            return False

        def _on_close_request(self, *_args: Any) -> bool:
            self._closed = True
            self._stop_refresh_timer()
            try:
                self.preview_manager.clear()
            except Exception:  # noqa: BLE001
                logger.exception("failed to clear previews on close")
            return False


    class WaymirrorApp(Adw.Application):
        def __init__(self, backend_name: str = "auto") -> None:
            super().__init__(application_id="io.github.alvaro.waymirror")
            self.backend_name = backend_name
            self.window: WaymirrorWindow | None = None

        def do_activate(self) -> None:  # noqa: N802 - GTK API
            if self.window is None:
                self.window = WaymirrorWindow(self, backend_name=self.backend_name)
            self.window.present()

else:

    class WaymirrorApp:  # type: ignore[no-redef]
        """Placeholder when GTK dependencies are unavailable."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError(f"GTK4/libadwaita unavailable: {_GTK_IMPORT_ERROR}")


def main_gui(argv: list[str] | None = None) -> int:
    """Launch the GTK GUI. Returns process-style exit code."""
    if not _GTK_AVAILABLE:
        message = f"GTK4/libadwaita unavailable: {_GTK_IMPORT_ERROR}"
        print(message, file=sys.stderr)
        return 1

    backend_name = "auto"
    args = list(argv) if argv is not None else []
    # Minimal argv handling: allow --backend <name> when launched from CLI.
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--backend" and i + 1 < len(args):
            backend_name = args[i + 1]
            i += 2
            continue
        if arg.startswith("--backend="):
            backend_name = arg.split("=", 1)[1]
            i += 1
            continue
        i += 1

    app = WaymirrorApp(backend_name=backend_name)
    # Do not forward custom args to GTK; GTK expects its own argv.
    return int(app.run([]))
