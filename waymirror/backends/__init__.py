"""Compositor output backends."""

from .base import Backend, BackendError, NoBackendError, detect_backend
from .niri import NiriBackend, parse_niri_outputs
from .umbriel import UmbrielBackend, parse_umbriel_outputs

__all__ = [
    "Backend",
    "BackendError",
    "NoBackendError",
    "NiriBackend",
    "UmbrielBackend",
    "detect_backend",
    "parse_niri_outputs",
    "parse_umbriel_outputs",
]
