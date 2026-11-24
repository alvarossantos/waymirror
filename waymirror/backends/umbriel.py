"""Umbriel output backend."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from waymirror.models import Output, Window

from .base import BackendError

RunFunc = Callable[[list[str]], str]
logger = logging.getLogger(__name__)


def _parse_window_items(payload: Any, backend: str) -> list[Window]:
    if isinstance(payload, dict) and isinstance(payload.get("windows"), list):
        payload = payload["windows"]
    if not isinstance(payload, list):
        logger.warning("unsupported %s windows JSON shape", backend)
        return []

    windows: list[Window] = []
    for item in payload:
        if not isinstance(item, dict) or "id" not in item or item["id"] is None:
            continue
        geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
        values = {}
        for field, alternatives in {
            "x": ("x",),
            "y": ("y",),
            "w": ("w", "width"),
            "h": ("h", "height"),
        }.items():
            key = next((key for key in alternatives if key in item), None)
            source = item
            if key is None:
                key = next((key for key in alternatives if key in geometry), None)
                source = geometry
            if key is None:
                break
            parsed = _as_int(source[key], None)
            if parsed is None:
                break
            values[field] = parsed
        if len(values) != 4:
            continue
        app_id = item.get("app_id", item.get("app-id", ""))
        output = item.get("output", geometry.get("output", ""))
        try:
            windows.append(
                Window.from_dict(
                    {
                        "id": str(item["id"]),
                        "app_id": str(app_id or ""),
                        "title": str(item.get("title") or ""),
                        "output": str(output or ""),
                        **values,
                        "visible": item.get("visible", True),
                        "minimized": item.get("minimized", False),
                    }
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return windows


def parse_umbriel_windows(text: str) -> list[Window]:
    """Parse `umbriel windows --json` into normalized Windows."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("invalid umbriel windows JSON: %s", exc)
        return []
    return _parse_window_items(payload, "umbriel")


def _as_int(value: Any, default: int | None = 0) -> int | None:
    try:
        return int(value)
    except Exception:  # noqa: BLE001 - defensive parse
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001 - defensive parse
        return default


def _refresh_hz_from_mhz(refresh_mhz: Any) -> float:
    mhz = _as_float(refresh_mhz, 0.0)
    if mhz <= 0:
        return 0.0
    if mhz > 1000:
        return round(mhz / 1000.0, 3)
    return mhz


def _parse_umbriel_output(data: dict[str, Any]) -> Output | None:
    name = str(data.get("name") or "").strip()
    if not name:
        return None

    logical = data.get("logical_size") if isinstance(data.get("logical_size"), dict) else {}
    position = data.get("position") if isinstance(data.get("position"), dict) else {}
    modes = data.get("modes") if isinstance(data.get("modes"), list) else []

    selected_mode: dict[str, Any] | None = None
    for m in modes:
        if isinstance(m, dict) and m.get("current"):
            selected_mode = m
            break
    if selected_mode is None:
        for m in modes:
            if isinstance(m, dict) and m.get("preferred"):
                selected_mode = m
                break
    if selected_mode is None and modes and isinstance(modes[0], dict):
        selected_mode = modes[0]

    width = _as_int(logical.get("width"))
    height = _as_int(logical.get("height"))
    refresh_hz = 0.0
    if selected_mode is not None:
        if width <= 0:
            width = _as_int(selected_mode.get("width"))
        if height <= 0:
            height = _as_int(selected_mode.get("height"))
        refresh_hz = _refresh_hz_from_mhz(selected_mode.get("refresh_mhz", selected_mode.get("refresh_rate")))

    return Output(
        name=name,
        description=str(data.get("description") or ""),
        make=str(data.get("make") or ""),
        model=str(data.get("model") or ""),
        width=width,
        height=height,
        refresh_hz=refresh_hz,
        enabled=bool(data.get("enabled", True)),
        focused=bool(data.get("focused", False)),
        position_x=_as_int(position.get("x", data.get("position_x", 0))),
        position_y=_as_int(position.get("y", data.get("position_y", 0))),
    )


def parse_umbriel_outputs(text: str) -> list[Output]:
    """Parse `umbriel outputs --json` into normalized Outputs."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BackendError(f"invalid umbriel outputs JSON: {exc}") from exc

    if isinstance(payload, dict) and isinstance(payload.get("outputs"), list):
        payload = payload["outputs"]
    if not isinstance(payload, list):
        raise BackendError("unsupported umbriel outputs shape")

    outputs: list[Output] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        out = _parse_umbriel_output(item)
        if out is not None:
            outputs.append(out)

    outputs.sort(key=lambda o: o.name)
    return outputs


class UmbrielBackend:
    name = "umbriel"

    def __init__(self, run: RunFunc | None = None):
        from .base import _default_run

        self._run = run if run is not None else _default_run

    def list_outputs(self) -> list[Output]:
        text = self._run(["umbriel", "outputs", "--json"])
        return parse_umbriel_outputs(text)

    def list_windows(self) -> list[Window]:
        try:
            text = self._run(["umbriel", "windows", "--json"])
        except BackendError as exc:
            logger.warning("failed to list umbriel windows: %s", exc)
            return []
        if not text.strip():
            logger.warning("empty umbriel windows response")
            return []
        return parse_umbriel_windows(text)
