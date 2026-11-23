from __future__ import annotations

from dataclasses import dataclass

from waymirror.preview import capture_grim_cmd, PreviewManager


@dataclass
class FakeResult:
    returncode: int = 0
    stdout: bytes = b""
    stderr: bytes = b""


def failing_runner(cmd):
    raise OSError("grim failed")


def test_grim_cmd_uses_output_name():
    assert capture_grim_cmd('HDMI-A-1','/tmp/x.png') == ['grim','-o','HDMI-A-1','/tmp/x.png']


def test_capture_failure_returns_none(tmp_path):
    mgr = PreviewManager(tmp_path, runner=failing_runner)
    assert mgr.capture('eDP-2') is None


def test_preview_path_is_under_runtime_dir(tmp_path):
    mgr = PreviewManager(tmp_path, runner=failing_runner)
    assert mgr.preview_path("HDMI-A-1") == tmp_path / "waymirror" / "previews" / "HDMI-A-1.png"


def test_preview_path_sanitizes_name(tmp_path):
    mgr = PreviewManager(tmp_path, runner=failing_runner)
    path = mgr.preview_path("weird/name with spaces")
    assert path.parent == tmp_path / "waymirror" / "previews"
    assert path.name == "weird_name_with_spaces.png"


def test_capture_success_writes_temp_then_renames(tmp_path):
    calls = []

    def runner(cmd):
        calls.append(list(cmd))
        # simulate grim writing the temp output file passed as last arg
        from pathlib import Path

        Path(cmd[-1]).write_bytes(b"pngdata")
        return FakeResult(returncode=0)

    clock_values = iter([1000.0, 1000.0])

    mgr = PreviewManager(tmp_path, runner=runner, clock=lambda: next(clock_values))
    path = mgr.capture("eDP-2")

    assert path == tmp_path / "waymirror" / "previews" / "eDP-2.png"
    assert path.read_bytes() == b"pngdata"
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0:3] == ["grim", "-o", "eDP-2"]
    tmp_arg = cmd[3]
    assert tmp_arg != str(path)
    assert ".eDP-2.png." in tmp_arg
    assert tmp_arg.endswith(".tmp")
    # temp file should be gone after rename
    assert not list((tmp_path / "waymirror" / "previews").glob("*.tmp"))


def test_capture_nonzero_return_records_error_and_returns_none(tmp_path):
    def runner(cmd):
        return FakeResult(returncode=1, stderr=b"bad output")

    mgr = PreviewManager(tmp_path, runner=runner)
    assert mgr.capture("eDP-2") is None
    assert "eDP-2" in mgr.errors
    assert "exit 1" in mgr.errors["eDP-2"]
    assert "bad output" in mgr.errors["eDP-2"]


def test_capture_missing_output_file_returns_none(tmp_path):
    def runner(cmd):
        # does not create file
        return FakeResult(returncode=0)

    mgr = PreviewManager(tmp_path, runner=runner)
    assert mgr.capture("eDP-2") is None
    assert "eDP-2" in mgr.errors


def test_capture_exception_does_not_escape(tmp_path):
    mgr = PreviewManager(tmp_path, runner=failing_runner)
    assert mgr.capture("eDP-2") is None
    assert "grim failed" in mgr.errors["eDP-2"]


def test_capture_failure_is_per_output(tmp_path):
    def runner(cmd):
        if cmd[2] == "BAD-1":
            return FakeResult(returncode=1, stderr=b"nope")
        from pathlib import Path

        Path(cmd[-1]).write_bytes(b"ok")
        return FakeResult(returncode=0)

    mgr = PreviewManager(tmp_path, runner=runner)
    assert mgr.capture("BAD-1") is None
    good = mgr.capture("eDP-2")
    assert good is not None and good.exists()
    assert mgr.capture("BAD-1") is None


def test_clear_removes_preview_contents(tmp_path):
    previews = tmp_path / "waymirror" / "previews"
    previews.mkdir(parents=True)
    (previews / "a.png").write_bytes(b"a")
    (previews / "b.png").write_bytes(b"b")
    nested = previews / "nested"
    nested.mkdir()
    (nested / "c.png").write_bytes(b"c")

    mgr = PreviewManager(tmp_path, runner=failing_runner)
    mgr.clear()

    assert previews.exists()
    assert list(previews.iterdir()) == []


def test_clear_unlinks_symlink_to_directory_without_touching_target(tmp_path):
    previews = tmp_path / "waymirror" / "previews"
    previews.mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    link = previews / "linked"
    link.symlink_to(target, target_is_directory=True)

    mgr = PreviewManager(tmp_path, runner=failing_runner)
    mgr.clear()

    assert not link.is_symlink()
    assert list(previews.iterdir()) == []
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"
