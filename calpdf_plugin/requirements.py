"""The calpdf version this plugin needs, and how to report a mismatch."""

from __future__ import annotations

import importlib
from importlib.metadata import PackageNotFoundError, version

MINIMUM_CALPDF = (0, 2, 0)


def calpdf_problem() -> str | None:
    """Explain why calpdf cannot be used, or return None when it can."""
    try:
        importlib.import_module("calpdf")
    except Exception as exc:
        return (
            "This Calibre build cannot import the calpdf package.\n\n"
            f"{exc.__class__.__name__}: {exc}"
        )

    try:
        installed = version("calpdf")
    except PackageNotFoundError:
        return "calpdf is importable, but it has no installed package metadata."

    if version_tuple(installed) < MINIMUM_CALPDF:
        wanted = ".".join(str(part) for part in MINIMUM_CALPDF)
        return (
            f"CalPDF needs calpdf {wanted} or newer, but {installed} is installed."
            "\n\nUpdate calpdf, then restart Calibre."
        )
    return None


def version_tuple(text: str) -> tuple[int, ...]:
    """Turn a version string into three integers, ignoring any suffix."""
    parts: list[int] = []
    for piece in text.split(".")[:3]:
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)
