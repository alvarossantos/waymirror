"""Runtime state persistence for waymirror."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import MirrorSession


class StateStore:
    """Load/save/clear a single mirror session state file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> MirrorSession | None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        try:
            return MirrorSession.from_dict(data)
        except (KeyError, TypeError, ValueError):
            return None

    def save(self, session: MirrorSession) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(session.to_dict(), sort_keys=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(data, encoding="utf-8")
            os.replace(tmp, self.path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def clear(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass

    def load_valid(self) -> MirrorSession | None:
        session = self._load_for_validation()
        if session is None:
            # _load_for_validation clears corrupt/unreadable/invalid state when present.
            return None
        if not _pid_alive(session.pid):
            self.clear()
            return None
        return session

    def _load_for_validation(self) -> MirrorSession | None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            self.clear()
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self.clear()
            return None
        if not isinstance(data, dict):
            self.clear()
            return None
        try:
            return MirrorSession.from_dict(data)
        except (KeyError, TypeError, ValueError):
            self.clear()
            return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
