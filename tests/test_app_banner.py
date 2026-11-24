from __future__ import annotations

import importlib
import sys
import types


class _DummyBanner:
    def __init__(self):
        self.title = ""
        self.revealed = False

    def set_title(self, title):
        self.title = title

    def set_revealed(self, revealed):
        self.revealed = revealed


class _DummyButton:
    def __init__(self):
        self.label = ""
        self.classes = set()

    def set_label(self, label):
        self.label = label

    def add_css_class(self, name):
        self.classes.add(name)

    def remove_css_class(self, name):
        self.classes.discard(name)


def _load_app_with_fake_gtk(monkeypatch):
    # Minimal fake gi modules so waymirror.app defines WaymirrorWindow.
    gi = types.ModuleType("gi")
    gi.require_version = lambda *args, **kwargs: None
    repo = types.ModuleType("gi.repository")

    class _Base:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            return 0

        def add_css_class(self, *args, **kwargs):
            pass

        def remove_css_class(self, *args, **kwargs):
            pass

        def set_margin_top(self, *a):
            pass

        def set_margin_bottom(self, *a):
            pass

        def set_margin_start(self, *a):
            pass

        def set_margin_end(self, *a):
            pass

        def set_hexpand(self, *a):
            pass

        def set_size_request(self, *a):
            pass

        def set_can_shrink(self, *a):
            pass

        def set_content_fit(self, *a):
            pass

        def set_paintable(self, *a):
            pass

        def set_wrap(self, *a):
            pass

        def set_xalign(self, *a):
            pass

        def set_text(self, *a):
            pass

        def set_visible(self, *a):
            pass

        def set_vexpand(self, *a):
            pass

        def set_halign(self, *a):
            pass

        def set_valign(self, *a):
            pass

        def set_cross_fade(self, *a):
            pass

        def set_transition_type(self, *a):
            pass

        def set_child(self, *a):
            pass

        def append(self, *a):
            pass

        def set_content(self, *a):
            pass

        def add_top_bar(self, *a):
            pass

        def set_title_widget(self, *a):
            pass

        def set_title(self, *a):
            pass

        def set_default_size(self, *a):
            pass

        def set_revealed(self, *a):
            pass

        def set_max_children_per_line(self, *a):
            pass

        def set_selection_mode(self, *a):
            pass

        def get_first_child(self):
            return None

        def remove(self, *a):
            pass

        def get_mapped(self):
            return True

        def present(self):
            pass

    class _StringList(_Base):
        def __init__(self, items=None):
            super().__init__()
            self.items = list(items or [])

        def splice(self, pos, n, items):
            self.items[pos : pos + n] = list(items)

        def get_n_items(self):
            return len(self.items)

    class _DropDown(_Base):
        def __init__(self, model=None):
            super().__init__()
            self.model = model
            self.selected = 0

        def get_selected(self):
            return self.selected

        def set_selected(self, idx):
            self.selected = idx

        def set_sensitive(self, *a):
            pass

    class _Banner(_DummyBanner, _Base):
        pass

    class _Button(_DummyButton, _Base):
        pass

    class _Flow(_Base):
        def get_first_child(self):
            return None

    gtk = types.ModuleType("gi.repository.Gtk")
    gtk.Box = _Base
    gtk.Label = _Base
    gtk.Button = _Button
    gtk.Picture = _Base
    gtk.DropDown = _DropDown
    gtk.StringList = _StringList
    gtk.ScrolledWindow = _Base
    gtk.FlowBox = _Flow
    gtk.Orientation = types.SimpleNamespace(VERTICAL=1, HORIZONTAL=0)
    gtk.Align = types.SimpleNamespace(START=0, FILL=1)
    gtk.SelectionMode = types.SimpleNamespace(NONE=0)
    gtk.ContentFit = types.SimpleNamespace(CONTAIN=0)
    gtk.RevealerTransitionType = types.SimpleNamespace(CROSSFADE=0)
    gtk.INVALID_LIST_POSITION = 4294967295

    adw = types.ModuleType("gi.repository.Adw")
    adw.ApplicationWindow = _Base
    adw.Application = _Base
    adw.ToolbarView = _Base
    adw.HeaderBar = _Base
    adw.Banner = _Banner
    adw.Bin = _Base

    gdk = types.ModuleType("gi.repository.Gdk")
    gdkpixbuf = types.ModuleType("gi.repository.GdkPixbuf")

    glib = types.ModuleType("gi.repository.GLib")
    glib.timeout_add = lambda *a, **k: 1
    glib.source_remove = lambda *a, **k: None
    glib.idle_add = lambda fn, *a: fn(*a)

    repo.Gtk = gtk
    repo.Adw = adw
    repo.Gdk = gdk
    repo.GLib = glib
    repo.GdkPixbuf = gdkpixbuf

    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repo)
    monkeypatch.setitem(sys.modules, "gi.repository.Gtk", gtk)
    monkeypatch.setitem(sys.modules, "gi.repository.Adw", adw)
    monkeypatch.setitem(sys.modules, "gi.repository.Gdk", gdk)
    monkeypatch.setitem(sys.modules, "gi.repository.GLib", glib)
    monkeypatch.setitem(sys.modules, "gi.repository.GdkPixbuf", gdkpixbuf)

    sys.modules.pop("waymirror.app", None)
    return importlib.import_module("waymirror.app")


class _FakeStatusResult:
    def __init__(self, warning=None, active=False, session=None):
        self.warning = warning
        self.active = active
        self.session = session


class _FakeMirrorManager:
    def __init__(self, results):
        self._results = list(results)

    def status(self):
        if self._results:
            return self._results.pop(0)
        return _FakeStatusResult()


def test_status_warning_clears_when_warning_disappears(monkeypatch):
    app = _load_app_with_fake_gtk(monkeypatch)
    win = object.__new__(app.WaymirrorWindow)
    win.banner = _DummyBanner()
    win.start_stop_button = _DummyButton()
    win._status_warning = None
    win._action_error = None
    win.mirror_manager = _FakeMirrorManager([
        _FakeStatusResult(warning="cleared stale session for dead pid 1"),
        _FakeStatusResult(warning=None),
    ])

    win._refresh_status()
    assert win.banner.revealed is True
    assert win.banner.title == "cleared stale session for dead pid 1"

    win._refresh_status()
    assert win.banner.revealed is False
    assert win.banner.title == ""


def test_action_error_persists_across_status_refresh_without_warning(monkeypatch):
    app = _load_app_with_fake_gtk(monkeypatch)
    win = object.__new__(app.WaymirrorWindow)
    win.banner = _DummyBanner()
    win.start_stop_button = _DummyButton()
    win._status_warning = None
    win._action_error = None
    win.mirror_manager = _FakeMirrorManager([_FakeStatusResult(warning=None)])

    win._set_action_error("Start failed")
    win._refresh_status()

    assert win.banner.revealed is True
    assert win.banner.title == "Start failed"


def test_status_warning_overrides_display_but_action_error_returns(monkeypatch):
    app = _load_app_with_fake_gtk(monkeypatch)
    win = object.__new__(app.WaymirrorWindow)
    win.banner = _DummyBanner()
    win.start_stop_button = _DummyButton()
    win._status_warning = None
    win._action_error = "Start failed"
    win.mirror_manager = _FakeMirrorManager([
        _FakeStatusResult(warning="status warning"),
        _FakeStatusResult(warning=None),
    ])

    win._refresh_status()
    assert win.banner.title == "Start failed"  # action error has priority in render
    assert win._status_warning == "status warning"

    win._set_action_error(None)
    assert win.banner.title == "status warning"

    win._refresh_status()
    assert win.banner.revealed is False
    assert win.banner.title == ""


def test_preview_thread_start_failure_resets_flags(monkeypatch):
    app = _load_app_with_fake_gtk(monkeypatch)
    win = object.__new__(app.WaymirrorWindow)
    win.banner = _DummyBanner()
    win._refresh_pending = False
    win._preview_inflight = False
    win._status_warning = None
    win._action_error = None
    win.outputs = [types.SimpleNamespace(name="eDP-1")]
    win.preview_manager = types.SimpleNamespace(capture=lambda name: None, errors={})

    class _BoomThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(app.threading, "Thread", _BoomThread)
    win._schedule_preview_refresh()

    assert win._refresh_pending is False
    assert win._preview_inflight is False
    assert "boom" in win.banner.title


class _Model:
    def __init__(self):
        self.items = []

    def splice(self, pos, n, items):
        self.items[pos : pos + n] = list(items)

    def get_n_items(self):
        return len(self.items)


class _Dropdown:
    def __init__(self, selected=0):
        self.selected = selected

    def get_selected(self):
        return self.selected

    def set_selected(self, value):
        self.selected = value

    def set_sensitive(self, value):
        self.sensitive = value


class _Flow:
    def __init__(self):
        self.children = []

    def get_first_child(self):
        return self.children[0] if self.children else None

    def remove(self, child):
        self.children.remove(child)

    def append(self, child):
        self.children.append(child)


def _bare_window(app, *, outputs=(), windows=(), kind=0):
    win = object.__new__(app.WaymirrorWindow)
    win.outputs = list(outputs)
    win.windows = list(windows)
    win.window_error = None
    win.cards = {}
    win.preview_paths = {}
    win.flow = _Flow()
    win.source_model = _Model()
    win.target_model = _Model()
    win.kind_dropdown = _Dropdown(kind)
    win.source_dropdown = _Dropdown(0)
    win.target_dropdown = _Dropdown(0)
    win.mode_dropdown = _Dropdown(0)
    win.start_stop_button = _DummyButton()
    win.banner = _DummyBanner()
    win._status_warning = None
    win._action_error = None
    win.backend_name = "niri"
    win._refresh_pending = False
    win._preview_inflight = False
    return win


def test_kind_dropdown_switches_source_list(monkeypatch):
    app = _load_app_with_fake_gtk(monkeypatch)
    from waymirror.models import Output, Window

    win = _bare_window(app, outputs=[Output("DP-1")], windows=[Window("42", app_id="firefox", title="Docs", w=800, h=600)])
    win._rebuild_outputs_ui()
    assert win.source_model.items == ["DP-1"]
    win.kind_dropdown.set_selected(1)
    win._rebuild_outputs_ui()
    assert win.source_model.items == ["firefox — Docs"]
    assert len(win.flow.children) == 1
    win.kind_dropdown.set_selected(0)
    win._rebuild_outputs_ui()
    assert win.source_model.items == ["DP-1"]
    assert len(win.flow.children) == 1


def test_gui_window_discovery_failure_nonfatal(monkeypatch):
    app = _load_app_with_fake_gtk(monkeypatch)
    from waymirror.models import Output

    output = Output("DP-1")

    class Backend:
        name = "niri"

        def list_outputs(self):
            return [output]

        def list_windows(self):
            raise RuntimeError("window listing failed")

    win = _bare_window(app)
    monkeypatch.setattr(app, "detect_backend", lambda _name: Backend())
    win._load_outputs()
    assert win.outputs == [output]
    assert len(win.flow.children) == 1
    assert "window listing failed" in win.banner.title


def test_start_passes_window_source(monkeypatch):
    app = _load_app_with_fake_gtk(monkeypatch)
    from waymirror.models import Window

    window = Window("42", app_id="firefox", title="Docs", x=4, y=8, w=800, h=600, output="DP-1")
    win = _bare_window(app, windows=[window], kind=1)
    win.outputs = [types.SimpleNamespace(name="DP-1")]

    class Manager(_FakeMirrorManager):
        def __init__(self):
            super().__init__([_FakeStatusResult()])
            self.calls = []

        def start(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return types.SimpleNamespace(warning=None)

    manager = Manager()
    win.mirror_manager = manager
    win.backend = types.SimpleNamespace(name="niri")
    win.source_dropdown = _Dropdown(0)
    win.mode_dropdown = _Dropdown(0)
    win._refresh_status = lambda: None
    win._on_start_stop()
    assert manager.calls[0][1]["source_kind"] == "window"
    assert manager.calls[0][1]["available_windows"] == [window]
    assert manager.calls[0][0][1] == "42"


def test_preview_uses_region_for_window(monkeypatch):
    app = _load_app_with_fake_gtk(monkeypatch)
    from waymirror.models import Window

    window = Window("42", w=800, h=600)
    win = _bare_window(app, windows=[window], kind=1)
    win.outputs = [types.SimpleNamespace(name="DP-1")]
    win.mirror_manager = types.SimpleNamespace(status=lambda: _FakeStatusResult(active=True, session=types.SimpleNamespace(source_kind="window", source="42", region="4,8 800x600")))
    calls = []
    win.preview_manager = types.SimpleNamespace(capture=lambda name, **kwargs: calls.append((name, kwargs)) or None, errors={})
    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(app.threading, "Thread", ImmediateThread)
    win._schedule_preview_refresh()
    assert ("window:42", {"region": "4,8 800x600"}) in calls


def test_preview_keeps_selected_window_when_other_session_active(monkeypatch):
    app = _load_app_with_fake_gtk(monkeypatch)
    from waymirror.models import Window

    first = Window("A", w=800, h=600)
    selected = Window("B", x=100, w=400, h=300)
    win = _bare_window(app, windows=[first, selected], kind=1)
    win.source_dropdown.set_selected(1)
    win.outputs = []
    win.mirror_manager = types.SimpleNamespace(status=lambda: _FakeStatusResult(
        active=True,
        session=types.SimpleNamespace(source_kind="window", source="A", region="0,0 800x600"),
    ))
    calls = []
    win.preview_manager = types.SimpleNamespace(capture=lambda name, **kwargs: calls.append((name, kwargs)), errors={})

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target
        def start(self):
            self.target()

    monkeypatch.setattr(app.threading, "Thread", ImmediateThread)
    win._schedule_preview_refresh()
    assert calls == [("window:B", {"region": "100,0 400x300"})]
