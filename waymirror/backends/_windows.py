"""Shared parsing for compositor window item payloads."""

from __future__ import annotations

import logging
from typing import Any

from waymirror.models import Window

logger = logging.getLogger(__name__)


def _as_int(value: Any, default: int | None = 0) -> int | None:
    try:
        return int(value)
    except Exception:  # noqa: BLE001 - defensive parse
        return default


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

