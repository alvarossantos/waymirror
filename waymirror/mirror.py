"""wl-mirror session management."""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from .models import MirrorMode, MirrorSession, SourceKind, Window
from .reveal import reveal_mirror_window
from .state import StateStore


class MirrorError(RuntimeError):
    """Base error for mirror operations."""

    exit_code = 5


class OutputNotFoundError(MirrorError):
    """Requested output does not exist."""

    exit_code = 4


class MirrorValidationError(MirrorError):
    """Invalid mirror request."""

    exit_code = 2


class WlMirrorMissingError(MirrorError):
    """wl-mirror is missing or cannot be executed."""

    exit_code = 5


class MirrorStopError(MirrorError):
    """Failed to stop a live mirror process."""

    exit_code = 5


@dataclass
class StartResult:
    action: str
    session: MirrorSession | None
    warning: str | None = None


@dataclass
class StopResult:
    action: str
    session: MirrorSession | None = None
    warning: str | None = None


@dataclass
class StatusResult:
    active: bool
    session: MirrorSession | None
    warning: str | None = None


Runner = Callable[[list[str]], Any]
PidAlive = Callable[[int], bool]
Now = Callable[[], str]
Killer = Callable[[int, int], None]
Waiter = Callable[[int], bool]
Revealer = Callable[[str, int, str], str | None]


def build_wl_mirror_cmd(
    source: str,
    mode: MirrorMode,
    target: str | None,
    *,
    source_kind: SourceKind = "output", region: str | None = None,
) -> list[str]:
    if source_kind == "window":
        if not region:
            raise MirrorValidationError("window source requires a region")
        if mode == "fullscreen":
            if not target:
                raise MirrorValidationError("fullscreen mode requires --target")
            return ["wl-mirror", "--fullscreen-output", target, "-r", region]
        if mode == "window":
            return ["wl-mirror", "-r", region]
        raise MirrorValidationError(f"unsupported mode: {mode!r}")
    if mode == "fullscreen":
        if not target:
            raise MirrorValidationError("fullscreen mode requires --target")
        return ["wl-mirror", "--fullscreen-output", target, source]
    if mode == "window":
        return ["wl-mirror", source]
    raise MirrorValidationError(f"unsupported mode: {mode!r}")


def _default_runner(cmd: list[str]) -> Any:
    return subprocess.Popen(cmd, start_new_session=True)


def _default_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _default_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _default_killer(pid: int, sig: int) -> None:
    os.kill(pid, sig)


def _default_waiter(
    pid: int,
    *,
    pid_alive: PidAlive = _default_pid_alive,
    timeout_s: float = 1.0,
    interval_s: float = 0.05,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(interval_s)
    return not pid_alive(pid)


class MirrorManager:
    """Manage a single wl-mirror session recorded in StateStore."""

    def __init__(
        self,
        state_store: StateStore,
        runner: Runner | None = None,
        pid_alive: PidAlive | None = None,
        now: Now | None = None,
        killer: Killer | None = None,
        waiter: Waiter | Callable[[int], bool] | None = None,
        revealer: Revealer | None = None,
    ) -> None:
        self.state_store = state_store
        self.runner = runner if runner is not None else _default_runner
        self.pid_alive = pid_alive if pid_alive is not None else _default_pid_alive
        self.now = now if now is not None else _default_now
        self.killer = killer if killer is not None else _default_killer
        self.waiter = waiter if waiter is not None else (
            lambda pid: _default_waiter(pid, pid_alive=self.pid_alive)
        )
        self.revealer = revealer if revealer is not None else (
            lambda backend, pid, target: reveal_mirror_window(backend, pid, target)
        )

    @contextmanager
    def _session_lock(self) -> Iterator[None]:
        """Serialize the load -> decide -> spawn/kill -> save state machine."""
        lock_path = self.state_store.path.parent / "waymirror.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _validate_outputs(
        self,
        source: str,
        mode: MirrorMode,
        target: str | None,
        available_outputs: list[str] | None,
    ) -> None:
        if available_outputs is None:
            # Caller must provide output names when validation is required.
            # For safety, do not guess.
            if mode == "fullscreen" and (not target or target == source):
                raise MirrorValidationError("fullscreen mode requires a target different from source")
            return
        available = set(available_outputs)
        if source not in available:
            raise OutputNotFoundError(f"source output not found: {source}")
        if mode == "fullscreen":
            if not target:
                raise MirrorValidationError("fullscreen mode requires --target")
            if target not in available:
                raise OutputNotFoundError(f"target output not found: {target}")
            if target == source:
                raise MirrorValidationError("target must differ from source in fullscreen mode")

    def _validate_request(
        self,
        source: str,
        mode: MirrorMode,
        target: str | None,
        available_outputs: list[str] | None,
        source_kind: SourceKind,
        available_windows: list[Window] | None,
    ) -> str | None:
        if source_kind == "window":
            window = next((w for w in (available_windows or []) if w.id == source), None)
            if window is None:
                raise OutputNotFoundError(f"source window not found: {source}")
            if not window.is_capturable():
                raise MirrorValidationError(f"window is not capturable: {source}")
            if mode == "fullscreen":
                if not target:
                    raise MirrorValidationError("fullscreen mode requires --target")
                if available_outputs is not None and target not in set(available_outputs):
                    raise OutputNotFoundError(f"target output not found: {target}")
                if target == window.output:
                    raise MirrorValidationError("target must differ from source window output in fullscreen mode")
            return window.wl_mirror_region()
        self._validate_outputs(source, mode, target, available_outputs)
        return None

    def _load_active(self) -> tuple[MirrorSession | None, str | None]:
        session = self.state_store.load()
        if session is None:
            # load() returns None for missing/corrupt/invalid. Clear corrupt/invalid
            # state files so stale/bad state does not persist.
            if self.state_store.path.exists():
                self.state_store.clear()
                return None, "cleared invalid mirror state"
            return None, None
        if not self.pid_alive(session.pid):
            self.state_store.clear()
            return None, f"cleared stale session for dead pid {session.pid}"
        return session, None

    def start(
        self,
        backend: str,
        source: str,
        mode: MirrorMode,
        target: str | None,
        *,
        available_outputs: list[str] | None = None,
        source_kind: SourceKind = "output",
        available_windows: list[Window] | None = None,
    ) -> StartResult:
        with self._session_lock():
            return self._start_locked(
                backend,
                source,
                mode,
                target,
                available_outputs=available_outputs,
                source_kind=source_kind,
                available_windows=available_windows,
            )

    def _start_locked(
        self,
        backend: str,
        source: str,
        mode: MirrorMode,
        target: str | None,
        *,
        available_outputs: list[str] | None = None,
        source_kind: SourceKind = "output",
        available_windows: list[Window] | None = None,
    ) -> StartResult:
        region = self._validate_request(source, mode, target, available_outputs, source_kind, available_windows)
        active, stale_warning = self._load_active()
        if active is not None and active.same_config(
            backend=backend, source=source, mode=mode, target=target, source_kind=source_kind, region=region
        ):
            return StartResult(action="already_running", session=active, warning=stale_warning)
        if active is not None:
            self._stop_active(active)

        cmd = build_wl_mirror_cmd(source, mode, target, source_kind=source_kind, region=region)
        try:
            proc = self.runner(cmd)
        except FileNotFoundError as exc:
            raise WlMirrorMissingError("wl-mirror not found") from exc
        except OSError as exc:
            raise WlMirrorMissingError(f"failed to start wl-mirror: {exc}") from exc

        pid = getattr(proc, "pid", None)
        if not isinstance(pid, int) or pid <= 0:
            raise MirrorError("wl-mirror runner returned invalid pid")

        session = MirrorSession(
            backend=backend,
            source=source,
            mode=mode,
            target=target,
            pid=pid,
            started_at=self.now(),
            source_kind=source_kind,
            region=region,
        )
        self.state_store.save(session)
        warnings = [w for w in (stale_warning,) if w]
        if mode == "fullscreen":
            reveal_warning = self.revealer(backend, pid, target or "")
            if reveal_warning:
                warnings.append(reveal_warning)
        return StartResult(action="started", session=session, warning="; ".join(warnings) or None)

    def stop(self) -> StopResult:
        with self._session_lock():
            return self._stop_locked()

    def _stop_locked(self) -> StopResult:
        session = self.state_store.load()
        if session is None:
            if self.state_store.path.exists():
                self.state_store.clear()
                return StopResult(action="stale_cleared", session=None, warning="cleared invalid mirror state")
            return StopResult(action="not_running", session=None)
        if not self.pid_alive(session.pid):
            self.state_store.clear()
            return StopResult(
                action="stale_cleared",
                session=None,
                warning=f"cleared stale session for dead pid {session.pid}",
            )
        self._stop_active(session)
        return StopResult(action="stopped", session=None)

    def status(self) -> StatusResult:
        session, warning = self._load_active()
        return StatusResult(active=session is not None, session=session, warning=warning)

    def toggle(
        self,
        backend: str,
        source: str,
        mode: MirrorMode,
        target: str | None,
        *,
        available_outputs: list[str] | None = None,
        source_kind: SourceKind = "output",
        available_windows: list[Window] | None = None,
    ) -> StartResult | StopResult:
        with self._session_lock():
            return self._toggle_locked(backend, source, mode, target, available_outputs=available_outputs, source_kind=source_kind, available_windows=available_windows)

    def _toggle_locked(
        self,
        backend: str,
        source: str,
        mode: MirrorMode,
        target: str | None,
        *,
        available_outputs: list[str] | None = None,
        source_kind: SourceKind = "output",
        available_windows: list[Window] | None = None,
    ) -> StartResult | StopResult:
        region = self._validate_request(source, mode, target, available_outputs, source_kind, available_windows)
        active, stale_warning = self._load_active()
        if active is None:
            return self._start_locked(backend, source, mode, target, available_outputs=available_outputs, source_kind=source_kind, available_windows=available_windows)
        if active.same_config(backend=backend, source=source, mode=mode, target=target, source_kind=source_kind, region=region):
            self._stop_active(active)
            return StopResult(action="stopped", session=None, warning=stale_warning)
        self._stop_active(active)
        return self._start_locked(
            backend,
            source,
            mode,
            target,
            available_outputs=available_outputs,
            source_kind=source_kind,
            available_windows=available_windows,
        )

    def _stop_active(self, session: MirrorSession) -> None:
        try:
            self.killer(session.pid, signal.SIGTERM)
        except ProcessLookupError:
            self.state_store.clear()
            return
        except OSError as exc:
            # PID may have died between check and kill.
            if not self.pid_alive(session.pid):
                self.state_store.clear()
                return
            raise MirrorStopError(f"failed to stop wl-mirror pid {session.pid}: {exc}") from exc

        if not self.waiter(session.pid):
            if self.pid_alive(session.pid):
                raise MirrorStopError(f"wl-mirror pid {session.pid} did not exit after SIGTERM")
        self.state_store.clear()
