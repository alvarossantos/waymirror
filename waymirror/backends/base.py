"""Backend protocol, errors, and detection."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from typing import Protocol

from waymirror.models import Output, Window


class BackendError(RuntimeError):
    """Backend command failed or returned invalid data."""

    exit_code = 3


class NoBackendError(BackendError):
    """No supported backend could be detected."""


class Backend(Protocol):
    name: str

    def list_outputs(self) -> list[Output]: ...

    def list_windows(self) -> list[Window]: ...


RunFunc = Callable[[list[str]], str]
ExistsFunc = Callable[[str], bool]


def _default_run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise BackendError(f"command not found: {cmd[0]}") from exc
    except OSError as exc:
        raise BackendError(f"failed to run {cmd[0]}: {exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise BackendError(f"{cmd[0]} failed: {err}")
    return proc.stdout


def _default_exists(path: str) -> bool:
    return os.path.exists(path) or shutil.which(path) is not None


def _env_has_session(env: Mapping[str, str], name: str) -> bool:
    needle = name.lower()
    for key in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "XDG_SESSION_DESKTOP"):
        value = env.get(key, "")
        if needle in value.lower():
            return True
    return False


def _niri_session_signal(env: Mapping[str, str], exists: ExistsFunc) -> bool:
    if _env_has_session(env, "niri"):
        return True
    socket = env.get("NIRI_SOCKET")
    return bool(socket) and exists(socket)


def _umbriel_session_signal(env: Mapping[str, str]) -> bool:
    return _env_has_session(env, "umbriel")


def detect_backend(
    requested: str,
    env: Mapping[str, str] | None = None,
    run: RunFunc | None = None,
    exists: ExistsFunc | None = None,
) -> Backend:
    """Detect or select a compositor backend.

    Explicit request wins. Auto detection is session-aware: session signals take
    priority over binary presence fallback. All command execution goes through
    the injected runner for testability.

    Policy: when a session signal identifies a backend but that backend is
    unusable, detection hard-fails with NoBackendError and does not fall back to
    another backend. This prevents wrong-backend selection in stale/ambiguous
    environments.
    """
    from .niri import NiriBackend
    from .umbriel import UmbrielBackend

    env_map: Mapping[str, str] = env if env is not None else {}
    run_fn = run if run is not None else _default_run
    exists_fn = exists if exists is not None else _default_exists

    builders = {
        "niri": lambda: NiriBackend(run=run_fn),
        "umbriel": lambda: UmbrielBackend(run=run_fn),
    }

    if requested != "auto":
        if requested not in builders:
            raise NoBackendError(f"unsupported backend: {requested}")
        return builders[requested]()

    errors: list[str] = []

    def try_backend(name: str) -> Backend | None:
        try:
            backend = builders[name]()
            backend.list_outputs()
            return backend
        except (BackendError, OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
            return None

    niri_signal = _niri_session_signal(env_map, exists_fn)
    umbriel_signal = _umbriel_session_signal(env_map)

    if niri_signal and not umbriel_signal:
        found = try_backend("niri")
        if found is not None:
            return found
        # Signaled backend unusable: hard fail, no cross-backend fallback.
    elif umbriel_signal and not niri_signal:
        found = try_backend("umbriel")
        if found is not None:
            return found
        # Signaled backend unusable: hard fail, no cross-backend fallback.
    elif niri_signal and umbriel_signal:
        # Ambiguous dual signal: try only signaled backends deterministically.
        for name in ("niri", "umbriel"):
            found = try_backend(name)
            if found is not None:
                return found
        # Both signaled backends unusable: hard fail.
    else:
        # No session signal: fallback try niri then umbriel.
        for name in ("niri", "umbriel"):
            found = try_backend(name)
            if found is not None:
                return found

    detail = "; ".join(errors) if errors else "no session signal and no working backend"
    raise NoBackendError(f"no supported backend detected: {detail}")
