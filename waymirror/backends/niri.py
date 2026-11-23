"""Niri output backend."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from waymirror.models import Output

from .base import BackendError

RunFunc = Callable[[list[str]], str]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001 - defensive parse
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001 - defensive parse
        return default


def _refresh_hz_from_mhz(refresh_rate: Any) -> float:
    mhz = _as_float(refresh_rate, 0.0)
    if mhz <= 0:
        return 0.0
    # niri reports mHz (e.g. 60000).
    if mhz > 1000:
        return round(mhz / 1000.0, 3)
    return mhz


def _mode_size(mode: dict[str, Any]) -> tuple[int, int, float]:
    width = _as_int(mode.get("width"))
    height = _as_int(mode.get("height"))
    refresh = _refresh_hz_from_mhz(mode.get("refresh_rate", mode.get("refresh_mhz")))
    return width, height, refresh


def _parse_niri_output(name: str, data: dict[str, Any]) -> Output | None:
    out_name = str(data.get("name") or name or "").strip()
    if not out_name:
        return None

    logical = data.get("logical") if isinstance(data.get("logical"), dict) else {}
    modes = data.get("modes") if isinstance(data.get("modes"), list) else []

    current_mode = data.get("current_mode")
    selected_mode: dict[str, Any] | None = None
    if isinstance(current_mode, int) and 0 <= current_mode < len(modes) and isinstance(modes[current_mode], dict):
        selected_mode = modes[current_mode]
    if selected_mode is None:
        for m in modes:
            if isinstance(m, dict) and m.get("is_current"):
                selected_mode = m
                break
    if selected_mode is None:
        for m in modes:
            if isinstance(m, dict) and m.get("is_preferred"):
                selected_mode = m
                break
    if selected_mode is None and modes and isinstance(modes[0], dict):
        selected_mode = modes[0]

    width = _as_int(logical.get("width"))
    height = _as_int(logical.get("height"))
    refresh_hz = 0.0
    if selected_mode is not None:
        mw, mh, mr = _mode_size(selected_mode)
        if width <= 0:
            width = mw
        if height <= 0:
            height = mh
        refresh_hz = mr

    return Output(
        name=out_name,
        description=str(data.get("description") or ""),
        make=str(data.get("make") or ""),
        model=str(data.get("model") or ""),
        width=width,
        height=height,
        refresh_hz=refresh_hz,
        enabled=bool(data.get("enabled", True)),
        focused=bool(data.get("focused", False)),
        position_x=_as_int(logical.get("x", data.get("position_x", 0))),
        position_y=_as_int(logical.get("y", data.get("position_y", 0))),
    )


def parse_niri_outputs(text: str) -> list[Output]:
    """Parse `niri msg --json outputs` into normalized Outputs.

    Niri may return a dict keyed by output name or a list; parse defensively.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BackendError(f"invalid niri outputs JSON: {exc}") from exc

    items: list[tuple[str, Any]] = []
    if isinstance(payload, dict):
        # Current shape: { "eDP-1": {...}, ... }
        # Be defensive in case there is an "outputs" wrapper.
        if "outputs" in payload and isinstance(payload["outputs"], (dict, list)):
            payload = payload["outputs"]
        if isinstance(payload, dict):
            items = list(payload.items())
        elif isinstance(payload, list):
            items = [(str(i.get("name", "")), i) for i in payload if isinstance(i, dict)]
    elif isinstance(payload, list):
        items = [(str(i.get("name", "")), i) for i in payload if isinstance(i, dict)]
    else:
        raise BackendError("unsupported niri outputs shape")

    outputs: list[Output] = []
    for key, value in items:
        if not isinstance(value, dict):
            continue
        out = _parse_niri_output(str(key), value)
        if out is not None:
            outputs.append(out)

    outputs.sort(key=lambda o: o.name)
    return outputs


class NiriBackend:
    name = "niri"

    def __init__(self, run: RunFunc | None = None):
        from .base import _default_run

        self._run = run if run is not None else _default_run

    def list_outputs(self) -> list[Output]:
        text = self._run(["niri", "msg", "--json", "outputs"])
        return parse_niri_outputs(text)
