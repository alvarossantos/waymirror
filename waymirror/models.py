"""Data models for waymirror."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

MirrorMode = Literal["window", "fullscreen"]


def _get(data: dict[str, Any], key: str, default: Any = None) -> Any:
    return data[key] if key in data else default


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

    def same_config(
        self,
        *,
        backend: str,
        source: str,
        mode: MirrorMode,
        target: str | None,
    ) -> bool:
        return (
            self.backend == backend
            and self.source == source
            and self.mode == mode
            and self.target == target
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "source": self.source,
            "mode": self.mode,
            "target": self.target,
            "pid": self.pid,
            "started_at": self.started_at,
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
        return cls(
            backend=str(data["backend"]),
            source=str(data["source"]),
            mode=mode,
            target=target,
            pid=int(data["pid"]),
            started_at=str(data["started_at"]),
        )
