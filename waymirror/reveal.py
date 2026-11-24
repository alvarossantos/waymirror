"""Revela a janela do wl-mirror no workspace alvo via IPC do compositor."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

RunFunc = Callable[[list[str]], str]
SleepFunc = Callable[[float], None]

MIRROR_APP_ID = "at.yrlf.wl_mirror"
logger = logging.getLogger(__name__)


def _window_list(cmd: list[str], run: RunFunc) -> list[dict[str, Any]]:
    text = run(cmd)
    payload = json.loads(text)
    if isinstance(payload, dict) and isinstance(payload.get("windows"), list):
        payload = payload["windows"]
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _window_cmd(backend: str) -> list[str]:
    if backend == "umbriel":
        return ["umbriel", "windows", "--json"]
    return ["niri", "msg", "--json", "windows"]


def _workspaces_cmd(backend: str) -> list[str]:
    if backend == "umbriel":
        return ["umbriel", "workspaces", "--json"]
    return ["niri", "msg", "--json", "workspaces"]


def _load_workspaces(backend: str, run: RunFunc) -> list[dict[str, Any]]:
    try:
        payload = json.loads(run(_workspaces_cmd(backend)))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("failed to list %s workspaces: %s", backend, exc)
        return []
    items = payload if isinstance(payload, list) else (
        payload.get("workspaces", []) if isinstance(payload, dict) else []
    )
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _workspace_ref(backend: str, workspace: str, workspaces: list[dict[str, Any]]) -> str:
    """Referência aceita pelo IPC: nome, ou índice no niri."""
    for item in workspaces:
        if str(item.get("id", "")) != workspace:
            continue
        if item.get("name"):
            return str(item["name"])
        return str(item.get("idx") or workspace) if backend == "niri" else workspace
    return workspace


def _is_mirror_window(item: dict[str, Any]) -> bool:
    return str(item.get("app_id", item.get("app-id", ""))) == MIRROR_APP_ID


def find_mirror_window(backend: str, pid: int, run: RunFunc) -> dict[str, Any] | None:
    """Localiza a janela do mirror pelo PID, com fallback por app_id."""
    try:
        items = _window_list(_window_cmd(backend), run)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("failed to list %s windows: %s", backend, exc)
        return None

    mirrors = [item for item in items if _is_mirror_window(item)]
    item = next((candidate for candidate in mirrors if candidate.get("pid") == pid), None)
    if item is None and len(mirrors) == 1:
        item = mirrors[0]
    if item is None:
        return None

    output = str(item.get("output") or "")
    workspace = str(item.get("workspace") or "")
    if backend == "niri":
        # niri Window tem workspace_id, não output/workspace; deriva da tabela.
        workspaces = _load_workspaces(backend, run)
        ws_id = str(item.get("workspace_id", ""))
        match = next((w for w in workspaces if str(w.get("id", "")) == ws_id), None)
        if match is not None:
            output = output or str(match.get("output") or "")
            workspace = _workspace_ref(backend, ws_id, workspaces)

    return {"id": str(item.get("id", "")), "output": output, "workspace": workspace}


def _active_workspace(backend: str, target: str, workspaces: list[dict[str, Any]]) -> str:
    for item in workspaces:
        if item.get("output") != target or not (item.get("active") or item.get("is_active")):
            continue
        return _workspace_ref(backend, str(item.get("id", "")), workspaces)
    return ""


def _commands(backend: str, window_id: str, workspace: str, target: str) -> list[list[str]]:
    if backend == "umbriel":
        return [
            ["umbriel", "msg", "window-focus", window_id],
            ["umbriel", "msg", "window-move-to-workspace", workspace, "--output", target],
            ["umbriel", "msg", "workspace-switch", workspace, "--output", target],
        ]
    return [
        ["niri", "msg", "action", "focus-window", "--id", window_id],
        ["niri", "msg", "action", "move-column-to-monitor", target],
        ["niri", "msg", "action", "focus-workspace", workspace],
    ]


def reveal_mirror_window(
    backend: str,
    pid: int,
    target: str,
    run: RunFunc | None = None,
    sleep: SleepFunc | None = None,
    attempts: int = 10,
) -> str | None:
    """Traz a janela do mirror para o alvo e ativa seu workspace.

    Devolve ``None`` no sucesso; qualquer falha vira aviso não-fatal.
    """
    import time as _time

    runner = run if run is not None else _default_run
    sleeper = sleep if sleep is not None else _time.sleep

    window: dict[str, Any] | None = None
    for attempt in range(max(1, attempts)):
        window = find_mirror_window(backend, pid, runner)
        if window is not None:
            break
        if attempt + 1 < attempts:
            sleeper(0.1)
    if window is None:
        return f"warn: mirror window not found for pid {pid}"

    workspaces = _load_workspaces(backend, runner)
    if not workspaces:
        return f"warn: no workspace data from {backend}"
    same_output = window.get("output") == target
    if same_output:
        workspace = window.get("workspace") or _active_workspace(backend, target, workspaces)
        workspace = _workspace_ref(backend, workspace, workspaces)
    else:
        workspace = _active_workspace(backend, target, workspaces) or window.get("workspace") or ""
    if not workspace:
        return f"warn: no workspace available on {target}"

    commands = _commands(backend, window["id"], workspace, target)
    if same_output:
        commands = commands[2:]

    warnings: list[str] = []
    for cmd in commands:
        try:
            runner(cmd)
        except Exception as exc:  # noqa: BLE001 - falha de IPC nunca aborta o start
            warnings.append(f"warn: {' '.join(cmd[:3])} failed: {exc}")
    return "; ".join(warnings) or None


def _default_run(cmd: list[str]) -> str:
    import subprocess

    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise OSError(proc.stderr.strip() or f"exit {proc.returncode}")
    return proc.stdout
