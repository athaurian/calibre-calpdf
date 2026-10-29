"""Calls into calpdf on behalf of the dialog.

This module talks to the filesystem and to calpdf only. It does not import
Qt or Calibre, so the operations stay testable outside a running Calibre.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import calpdf.output
import pikepdf
from calpdf import extract as extract_mod
from calpdf import info as info_mod
from calpdf import optimize as optimize_mod
from calpdf import replace as replace_mod
from calpdf import restore as restore_mod
from calpdf import toc as toc_mod
from calpdf.common import AppError, message, normalize_paths
from calpdf.dlcover import download_cover, validate_book_id

# calpdf prints progress for the terminal. The dialog reports progress
# itself, so keep the library quiet. Errors still go to stderr.
calpdf.output.configure(quiet=True)


class OperationError(Exception):
    """A failure that the dialog can show to the user as-is."""


@contextmanager
def _calpdf_errors() -> Iterator[None]:
    try:
        yield
    except OperationError:
        raise
    except AppError as exc:
        raise OperationError(str(exc)) from exc
    except (pikepdf.PdfError, OSError, ValueError) as exc:
        raise OperationError(message(exc)) from exc


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_info(path: Path) -> dict[str, Any]:
    """Return the properties shown on the Info tab."""
    with _calpdf_errors():
        data = info_mod.collect_info(path)
        data["backup"] = _describe_backup(backup_for(path))
        return data


def backup_for(path: Path) -> Path:
    return normalize_paths(path)[1]


def _describe_backup(backup: Path) -> dict[str, Any] | None:
    if not backup.is_file():
        return None
    stat = backup.stat()
    return {"path": backup, "size": stat.st_size, "mtime": stat.st_mtime}


def read_toc(path: Path) -> list[dict[str, Any]]:
    with _calpdf_errors():
        return toc_mod.read_toc(path)


def read_toc_file(path: Path, pages: int) -> list[dict[str, Any]]:
    """Read and validate a ToC JSON file before loading it into the tree."""
    with _calpdf_errors():
        entries = toc_mod.read_toc_file(path)
        validate_entries(entries, pages)
        return entries


def write_toc_file(path: Path, entries: list[dict[str, Any]]) -> None:
    with _calpdf_errors():
        path.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def validate_entries(entries: list[dict[str, Any]], pages: int) -> None:
    with _calpdf_errors():
        errors = toc_mod.validate_toc(entries, pages)
        if errors:
            raise OperationError("\n".join(errors[:8]))


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def write_toc(path: Path, entries: list[dict[str, Any]]) -> int:
    """Replace the PDF outline. Returns the number of bookmarks written."""
    with _calpdf_errors():
        return toc_mod.write_toc(path, entries)


def apply_cover(
    path: Path,
    image_path: Path,
    *,
    mode: replace_mod.Mode,
    pages: int,
    dpi: int,
    fit_mode: replace_mod.FitMode,
) -> None:
    with _calpdf_errors():
        job = replace_mod.Job(
            input_pdf=path,
            image_path=image_path,
            output_pdf=None,
            mode=mode,
            pages=pages,
            dpi=dpi,
            fit_mode=fit_mode,
        )
        replace_mod.run(job)


def fetch_cover(book_id: str, directory: Path) -> Path:
    with _calpdf_errors():
        validate_book_id(book_id)
        return download_cover(book_id, directory / "cover.img")


def extract_cover(path: Path, destination: Path, page: int = 1) -> Path:
    with _calpdf_errors():
        return extract_mod.extract_cover(path, destination, page, raw=False)


def optimize_pdf(
    path: Path,
    *,
    strip_color: bool = False,
    keep_metadata: bool = False,
) -> optimize_mod.OptimizeResult:
    with _calpdf_errors():
        return optimize_mod.optimize(
            path, strip_color=strip_color, keep_metadata=keep_metadata
        )


def restore_backup(path: Path) -> None:
    with _calpdf_errors():
        restore_mod.restore_backup(path)
