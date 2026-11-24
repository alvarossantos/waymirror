"""Data models for waymirror."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

MirrorMode = Literal["window", "fullscreen"]
SourceKind = Literal["output", "window"]


def _get(data: dict[str, Any], key: str, default: Any = None) -> Any:
    return data[key] if key in data else default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.casefold()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return default


@dataclass
class Window:
    """A compositor window and its current global geometry."""

    id: str
    app_id: str = ""
    title: str = ""
    output: str = ""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    visible: bool = True
    minimized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "app_id": self.app_id,
            "title": self.title,
            "output": self.output,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "visible": self.visible,
            "minimized": self.minimized,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Window":
        return cls(
            id=str(data["id"]),
            app_id=str(_get(data, "app_id", "")),
            title=str(_get(data, "title", "")),
            output=str(_get(data, "output", "")),
            x=int(_get(data, "x", 0)),
            y=int(_get(data, "y", 0)),
            w=int(_get(data, "w", 0)),
            h=int(_get(data, "h", 0)),
            visible=_as_bool(_get(data, "visible", True), True),
            minimized=_as_bool(_get(data, "minimized", False), False),
        )

    def wl_mirror_region(self) -> str:
        return f"{self.x},{self.y} {self.w}x{self.h} {self.output}"

    def grim_region(self) -> str:
        return f"{self.x},{self.y} {self.w}x{self.h}"

    def is_capturable(self) -> bool:
        return self.visible and not self.minimized and self.w > 0 and self.h > 0


@dataclass
class Output:
    """A compositor output, identified canonically by connector name."""

    name: str
    description: str = ""
    make: str = ""
    model: str = ""
    width: int = 0
    height: int = 0
    refresh_hz: float = 0.0
    enabled: bool = True
    focused: bool = False
    position_x: int = 0
    position_y: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "make": self.make,
            "model": self.model,
            "width": self.width,
            "height": self.height,
            "refresh_hz": self.refresh_hz,
            "enabled": self.enabled,
            "focused": self.focused,
            "position_x": self.position_x,
            "position_y": self.position_y,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Output":
        # Ignore unknown fields for forward safety.
        return cls(
            name=str(data["name"]),
            description=str(_get(data, "description", "")),
            make=str(_get(data, "make", "")),
            model=str(_get(data, "model", "")),
            width=int(_get(data, "width", 0)),
            height=int(_get(data, "height", 0)),
            refresh_hz=float(_get(data, "refresh_hz", 0.0)),
            enabled=bool(_get(data, "enabled", True)),
            focused=bool(_get(data, "focused", False)),
            position_x=int(_get(data, "position_x", 0)),
            position_y=int(_get(data, "position_y", 0)),
        )


@dataclass
class MirrorSession:
    """An active or persisted mirror session."""

    backend: str
    source: str
    mode: MirrorMode
    target: str | None
    pid: int
    started_at: str
    source_kind: SourceKind = "output"
    region: str | None = None

    def same_config(
        self,
        *,
        backend: str,
        source: str,
        mode: MirrorMode,
        target: str | None,
        source_kind: SourceKind = "output",
        region: str | None = None,
    ) -> bool:
        return (
            self.backend == backend
            and self.source == source
            and self.mode == mode
            and self.target == target
            and self.source_kind == source_kind
            and not (
                self.source_kind == "window"
                and self.region is not None
                and region is not None
                and self.region != region
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "source": self.source,
            "mode": self.mode,
            "target": self.target,
            "pid": self.pid,
            "started_at": self.started_at,
            "source_kind": self.source_kind,
            "region": self.region,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MirrorSession":
        # Ignore unknown fields for forward safety.
        mode = data["mode"]
        if mode not in ("window", "fullscreen"):
            raise ValueError(f"invalid mode: {mode!r}")
        target = data.get("target")
        if target is not None:
            target = str(target)
        source_kind = _get(data, "source_kind", "output")
        if source_kind not in ("output", "window"):
            raise ValueError(f"invalid source_kind: {source_kind!r}")
        region = _get(data, "region", None)
        if region is not None:
            region = str(region)
        return cls(
            backend=str(data["backend"]),
            source=str(data["source"]),
            mode=mode,
            target=target,
            pid=int(data["pid"]),
            started_at=str(data["started_at"]),
            source_kind=source_kind,
            region=region,
        )
