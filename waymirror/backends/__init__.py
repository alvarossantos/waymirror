"""Compositor output backends."""

from .base import Backend, BackendError, NoBackendError, detect_backend
from waymirror.models import Window

from .niri import NiriBackend, parse_niri_outputs, parse_niri_windows
from .umbriel import UmbrielBackend, parse_umbriel_outputs, parse_umbriel_windows

__all__ = [
    "Backend",
    "BackendError",
    "NoBackendError",
    "NiriBackend",
    "UmbrielBackend",
    "Window",
    "detect_backend",
    "parse_niri_outputs",
    "parse_niri_windows",
    "parse_umbriel_outputs",
    "parse_umbriel_windows",
]
