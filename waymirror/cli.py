"""Command-line interface for waymirror."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .backends.base import BackendError, NoBackendError, detect_backend
from .mirror import (
    MirrorError,
    MirrorManager,
    MirrorStopError,
    MirrorValidationError,
    OutputNotFoundError,
    StartResult,
    StatusResult,
    StopResult,
    WlMirrorMissingError,
)
from .state import StateStore

EXIT_USAGE = 2
EXIT_BACKEND = 3
EXIT_OUTPUT_NOT_FOUND = 4
EXIT_EXECUTION = 5


def default_state_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "waymirror" / "state.json"
    return Path("/tmp") / f"waymirror-{os.getuid()}" / "state.json"


def _emit(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    if text:
        stream.write(text if text.endswith("\n") else text + "\n")


def _json_dump(payload: object) -> str:
    return json.dumps(payload, sort_keys=True)


def _cmd_list(args: argparse.Namespace) -> int:
    backend = detect_backend(args.backend)
    outputs = backend.list_outputs()
    if args.json:
        _emit(
            _json_dump(
                {
                    "backend": backend.name,
                    "outputs": [o.to_dict() for o in outputs],
                }
            ),
        )
    else:
        if not outputs:
            _emit("No outputs found.")
        for o in outputs:
            desc = f" {o.description}" if o.description else ""
            size = f"{o.width}x{o.height}" if o.width and o.height else "unknown"
            rate = f"@{o.refresh_hz:g}Hz" if o.refresh_hz else ""
            flags = []
            if o.focused:
                flags.append("focused")
            if not o.enabled:
                flags.append("disabled")
            suffix = f" [{' '.join(flags)}]" if flags else ""
            _emit(f"{o.name}\t{size}{rate}{desc}{suffix}")
    return 0


def _format_session(session) -> dict | None:
    if session is None:
        return None
    return session.to_dict()


def _cmd_status(args: argparse.Namespace) -> int:
    manager = MirrorManager(StateStore(default_state_path()))
    result: StatusResult = manager.status()
    if args.json:
        payload = {
            "active": result.active,
            "session": _format_session(result.session),
        }
        if result.warning:
            payload["warning"] = result.warning
        _emit(_json_dump(payload))
    else:
        if result.warning:
            _emit(f"Warning: {result.warning}", err=True)
        if not result.active or result.session is None:
            _emit("inactive")
        else:
            s = result.session
            target = f" -> {s.target}" if s.target else ""
            _emit(
                f"active backend={s.backend} source={s.source} mode={s.mode}{target} pid={s.pid}",
            )
    return 0


def _available_output_names(backend) -> list[str]:
    outputs = backend.list_outputs()
    return [o.name for o in outputs]


def _cmd_start(args: argparse.Namespace) -> int:
    backend = detect_backend(args.backend)
    available = _available_output_names(backend)
    manager = MirrorManager(StateStore(default_state_path()))
    result: StartResult = manager.start(
        backend.name,
        args.source,
        args.mode,
        args.target,
        available_outputs=available,
    )
    if result.warning:
        _emit(f"Warning: {result.warning}", err=True)
    if result.session is None:
        _emit(result.action)
    else:
        s = result.session
        target = f" -> {s.target}" if s.target else ""
        _emit(
            f"{result.action}: {s.source} [{s.mode}{target}] pid={s.pid} backend={s.backend}",
        )
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    manager = MirrorManager(StateStore(default_state_path()))
    result: StopResult = manager.stop()
    if result.warning:
        _emit(f"Warning: {result.warning}", err=True)
    if result.action == "not_running":
        _emit("not running")
    elif result.action == "stale_cleared":
        _emit("stale state cleared")
    else:
        _emit("stopped")
    return 0


def _cmd_toggle(args: argparse.Namespace) -> int:
    backend = detect_backend(args.backend)
    available = _available_output_names(backend)
    manager = MirrorManager(StateStore(default_state_path()))
    result = manager.toggle(
        backend.name,
        args.source,
        args.mode,
        args.target,
        available_outputs=available,
    )
    warning = getattr(result, "warning", None)
    if warning:
        _emit(f"Warning: {warning}", err=True)
    if isinstance(result, StopResult):
        if result.action == "stale_cleared":
            _emit("stale state cleared")
        else:
            _emit("stopped")
    else:
        s = result.session
        if s is None:
            _emit(result.action)
        else:
            target = f" -> {s.target}" if s.target else ""
            _emit(
                f"{result.action}: {s.source} [{s.mode}{target}] pid={s.pid} backend={s.backend}",
            )
    return 0


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: A003 - argparse API
        raise argparse.ArgumentError(None, message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="waymirror", description="Wayland screen mirroring")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--backend",
        choices=["auto", "niri", "umbriel"],
        default="auto",
        help="Compositor backend to use",
    )

    sub = parser.add_subparsers(dest="command", required=False)

    p_list = sub.add_parser("list", help="List outputs")
    p_list.add_argument("--json", action="store_true", help="Output JSON")
    p_list.set_defaults(_handler=_cmd_list)

    p_status = sub.add_parser("status", help="Show mirror status")
    p_status.add_argument("--json", action="store_true", help="Output JSON")
    p_status.set_defaults(_handler=_cmd_status)

    p_start = sub.add_parser("start", help="Start mirroring")
    p_start.add_argument("--source", required=True, help="Source output name")
    p_start.add_argument("--mode", required=True, choices=["window", "fullscreen"], help="Mirror mode")
    p_start.add_argument("--target", help="Target output name (required for fullscreen)")
    p_start.set_defaults(_handler=_cmd_start)

    p_stop = sub.add_parser("stop", help="Stop mirroring")
    p_stop.set_defaults(_handler=_cmd_stop)

    p_toggle = sub.add_parser("toggle", help="Toggle mirroring")
    p_toggle.add_argument("--source", required=True, help="Source output name")
    p_toggle.add_argument("--mode", required=True, choices=["window", "fullscreen"], help="Mirror mode")
    p_toggle.add_argument("--target", help="Target output name (required for fullscreen)")
    p_toggle.set_defaults(_handler=_cmd_toggle)

    return parser


def _usage_error(message: str) -> int:
    _emit(f"error: {message}", err=True)
    return EXIT_USAGE


def _map_exception(exc: Exception) -> int:
    code = getattr(exc, "exit_code", None)
    if isinstance(exc, argparse.ArgumentError):
        return _usage_error(str(exc))
    if isinstance(exc, SystemExit):
        c = exc.code
        if c == 0:
            return 0
        return EXIT_USAGE
    if isinstance(exc, (NoBackendError, BackendError)):
        _emit(f"error: {exc}", err=True)
        return EXIT_BACKEND if code is None else int(code)
    if isinstance(exc, OutputNotFoundError):
        _emit(f"error: {exc}", err=True)
        return EXIT_OUTPUT_NOT_FOUND
    if isinstance(exc, MirrorValidationError):
        _emit(f"error: {exc}", err=True)
        return EXIT_USAGE
    if isinstance(exc, (WlMirrorMissingError, MirrorStopError)):
        _emit(f"error: {exc}", err=True)
        return EXIT_EXECUTION
    if isinstance(exc, MirrorError):
        _emit(f"error: {exc}", err=True)
        return int(code) if code is not None else EXIT_EXECUTION
    _emit(f"error: {exc}", err=True)
    return EXIT_EXECUTION


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except argparse.ArgumentError as exc:
        return _usage_error(str(exc))
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        # argparse may raise SystemExit(2) for usage errors; normalize
        return EXIT_USAGE

    handler = getattr(args, "_handler", None)
    command = getattr(args, "command", None)

    # Additional validation required by spec
    if command in ("start", "toggle"):
        if args.mode == "fullscreen" and not args.target:
            return _usage_error("--target is required when --mode fullscreen")

    if handler is None:
        # Root command launches GUI; lazy import keeps GTK out of headless CLI paths.
        from .app import main_gui

        gui_argv: list[str] = []
        backend = getattr(args, "backend", "auto")
        if backend and backend != "auto":
            gui_argv.extend(["--backend", str(backend)])
        return int(main_gui(gui_argv))

    try:
        return int(handler(args))
    except Exception as exc:  # noqa: BLE001 - CLI maps known errors to exit codes
        return _map_exception(exc)
