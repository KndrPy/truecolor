from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class LayoutBackendResult:
    backend: str
    version: str
    payload: Mapping[str, Any] | None
    state: str
    diagnostic: str


class LayoutBackend:
    """Optional enhanced-layout adapter with deterministic PyMuPDF fallback.

    The adapter never makes pymupdf_layout a mandatory dependency. Package API
    differences are isolated here and cannot silently change the evidence model.
    """

    def analyze(self, page: Any) -> LayoutBackendResult:
        try:
            module = importlib.import_module("pymupdf_layout")
        except ImportError:
            return LayoutBackendResult("PYMUPDF_NATIVE", "", None, "FALLBACK", "pymupdf_layout unavailable")
        version = str(getattr(module, "__version__", "unknown"))
        candidates = (
            ("analyze_page", (page,)),
            ("get_layout", (page,)),
            ("analyze", (page,)),
        )
        for name, args in candidates:
            operation = getattr(module, name, None)
            if not callable(operation):
                continue
            try:
                value = operation(*args)
            except Exception as error:
                return LayoutBackendResult("PYMUPDF_LAYOUT", version, None, "FAILED_FALLBACK", f"{name}:{type(error).__name__}:{error}")
            if isinstance(value, Mapping):
                return LayoutBackendResult("PYMUPDF_LAYOUT", version, dict(value), "USED", name)
            if hasattr(value, "to_dict"):
                converted = value.to_dict()
                if isinstance(converted, Mapping):
                    return LayoutBackendResult("PYMUPDF_LAYOUT", version, dict(converted), "USED", name)
            return LayoutBackendResult("PYMUPDF_LAYOUT", version, {"repr": repr(value)}, "USED_UNSTRUCTURED", name)
        return LayoutBackendResult("PYMUPDF_NATIVE", version, None, "FALLBACK", "supported pymupdf_layout entrypoint not found")
