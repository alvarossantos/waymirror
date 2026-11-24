"""grim-based output preview capture."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

Runner = Callable[[list[str]], Any]
Clock = Callable[[], float]


def _default_runner(cmd: list[str]) -> Any:
    return subprocess.run(cmd, capture_output=True, check=False)


def _default_clock() -> float:
    import time

    return time.time()


def capture_grim_cmd(output_name: str, path: str) -> list[str]:
    """Build grim command for capturing a single output."""
    return ["grim", "-o", output_name, path]


def capture_grim_region_cmd(region: str, path: str) -> list[str]:
    """Build grim command for capturing a region of the screen."""
    return ["grim", "-g", region, path]


def _safe_name(output_name: str) -> str:
    # Keep it readable but filesystem-safe; output connector names are typically
    # simple (eDP-1, HDMI-A-1) but be defensive.
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", output_name).strip("._")
    return safe or "output"


class PreviewManager:
    """Capture and manage per-output preview images."""

    def __init__(
        self,
        runtime_dir: str | Path,
        runner: Runner | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.runner = runner if runner is not None else _default_runner
        self.clock = clock if clock is not None else _default_clock
        self.errors: dict[str, str] = {}

    @property
    def previews_dir(self) -> Path:
        return self.runtime_dir / "waymirror" / "previews"

    def preview_path(self, output_name: str) -> Path:
        return self.previews_dir / f"{_safe_name(output_name)}.png"

    def capture(self, output_name: str, *, region: str | None = None) -> Path | None:
        """Capture an output or region preview; return None on failure."""
        path = self.preview_path(output_name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{os.getpid()}.{int(self.clock() * 1000)}.tmp")
            cmd = (
                capture_grim_region_cmd(region, str(tmp))
                if region is not None
                else capture_grim_cmd(output_name, str(tmp))
            )
            try:
                result = self.runner(cmd)
            except Exception as exc:  # noqa: BLE001 - capture failures must not escape GUI loop
                self._record_error(output_name, exc)
                self._cleanup_tmp(tmp)
                return None

            returncode = getattr(result, "returncode", None)
            if returncode != 0:
                stderr = getattr(result, "stderr", b"")
                if isinstance(stderr, bytes):
                    stderr_text = stderr.decode("utf-8", errors="replace")
                else:
                    stderr_text = str(stderr)
                msg = f"grim failed for {output_name} with exit {returncode}"
                if stderr_text.strip():
                    msg += f": {stderr_text.strip()}"
                self._record_error(output_name, msg)
                self._cleanup_tmp(tmp)
                return None

            if not tmp.exists():
                self._record_error(output_name, f"grim did not create preview file for {output_name}")
                self._cleanup_tmp(tmp)
                return None

            os.replace(tmp, path)
            self.errors.pop(output_name, None)
            return path
        except Exception as exc:  # noqa: BLE001 - capture failures must not escape GUI loop
            self._record_error(output_name, exc)
            return None

    def clear(self) -> None:
        """Remove preview directory contents."""
        directory = self.previews_dir
        if not directory.exists():
            return
        try:
            for child in directory.iterdir():
                try:
                    # Check symlinks first: is_dir() follows them and would traverse
                    # outside the previews directory.
                    if not child.is_symlink() and child.is_dir():
                        # previews dir should only contain files, but be defensive
                        for sub in child.rglob("*"):
                            if sub.is_file() or sub.is_symlink():
                                sub.unlink(missing_ok=True)
                        for sub in sorted(child.rglob("*"), reverse=True):
                            if sub.is_dir():
                                sub.rmdir()
                        child.rmdir()
                    else:
                        child.unlink(missing_ok=True)
                except OSError as exc:
                    self._record_error(f"clear:{child.name}", exc)
        except OSError as exc:
            self._record_error("clear", exc)

    def _record_error(self, output_name: str, error: Exception | str) -> None:
        msg = str(error)
        self.errors[output_name] = msg
        logger.warning("preview capture error for %s: %s", output_name, msg)

    @staticmethod
    def _cleanup_tmp(tmp: Path) -> None:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
