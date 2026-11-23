"""Command-line interface for waymirror."""

from __future__ import annotations

import argparse
from typing import Sequence

from . import __version__


def _stub(_args: argparse.Namespace) -> int:
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="waymirror", description="Wayland screen mirroring")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--backend",
        choices=["auto", "niri", "umbriel"],
        default="auto",
        help="Compositor backend to use",
    )

    sub = parser.add_subparsers(dest="command", required=False)
    for name in ("list", "status", "start", "stop", "toggle"):
        cmd = sub.add_parser(name)
        cmd.set_defaults(_handler=_stub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)
