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


def test_output_ignores_unknown_fields():
    data = {
        "name": "eDP-2",
        "description": "d",
        "make": "m",
        "model": "x",
        "width": 1920,
        "height": 1200,
        "refresh_hz": 60.0,
        "enabled": True,
        "focused": True,
        "position_x": 0,
        "position_y": 0,
        "future_field": "ignored",
    }
    out = Output.from_dict(data)
    assert out.name == "eDP-2"
    assert out.to_dict()["name"] == "eDP-2"
    assert "future_field" not in out.to_dict()


def test_mirror_session_roundtrip_and_same_config():
    s = MirrorSession(
        backend="niri",
        source="eDP-2",
        mode="window",
        target=None,
        pid=123,
        started_at="2026-11-23T00:00:00Z",
    )
    restored = MirrorSession.from_dict(s.to_dict())
    assert restored == s
    assert s.same_config(backend="niri", source="eDP-2", mode="window", target=None)
    assert not s.same_config(backend="niri", source="eDP-2", mode="fullscreen", target="HDMI-A-1")


def test_mirror_session_ignores_unknown_fields():
    data = {
        "backend": "umbriel",
        "source": "HDMI-A-1",
        "target": "eDP-2",
        "mode": "fullscreen",
        "pid": 42,
        "started_at": "t",
        "extra": {"keep": False},
    }
    s = MirrorSession.from_dict(data)
    assert s.target == "eDP-2"
    assert s.mode == "fullscreen"


def test_state_store_save_load_clear(tmp_path):
    p = tmp_path / "state.json"
    store = StateStore(p)
    session = MirrorSession("niri", "eDP-2", "window", None, 123, "t")
    store.save(session)
    loaded = store.load()
    assert loaded == session
    store.clear()
    assert store.load() is None
    assert not p.exists()


def test_state_store_load_valid_clears_corrupt(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json", encoding="utf-8")
    assert StateStore(p).load_valid() is None
    assert not p.exists()


def test_state_store_load_valid_clears_missing_fields(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('{"source":"eDP-2"}', encoding="utf-8")
    assert StateStore(p).load_valid() is None
    assert not p.exists()


def test_state_store_load_valid_keeps_live_pid(tmp_path):
    import os

    p = tmp_path / "state.json"
    store = StateStore(p)
    session = MirrorSession("niri", "eDP-2", "window", None, os.getpid(), "t")
    store.save(session)
    loaded = store.load_valid()
    assert loaded == session
    assert p.exists()


def test_state_store_load_valid_treats_permission_error_pid_as_alive(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    store = StateStore(p)
    session = MirrorSession("niri", "eDP-2", "window", None, 12345, "t")
    store.save(session)

    def raise_permission_error(pid, sig):
        raise PermissionError("operation not permitted")

    monkeypatch.setattr("waymirror.state.os.kill", raise_permission_error)
    loaded = store.load_valid()
    assert loaded == session
    assert p.exists()
