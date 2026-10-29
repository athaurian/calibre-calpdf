"""Calls into calpdf on behalf of the dialog.

This module talks to the filesystem and to calpdf only. It does not import
Qt or Calibre, so the operations stay testable outside a running Calibre.
"""

from __future__ import annotations

import json
import shutil
import tempfile
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
from calpdf import toc as toc_mod
from calpdf.common import (
    AppError,
    ensure_backup,
    message,
    normalize_paths,
    validate_input_file,
)
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
        backup = backup_for(path)
        data["backup"] = _describe_backup(backup)
        return data


def backup_for(path: Path) -> Path:
    return normalize_paths(path)[1]


def _describe_backup(backup: Path) -> dict[str, Any] | None:
    if not backup.is_file():
        return None
    stat = backup.stat()
    return {"path": backup, "size": stat.st_size, "mtime": stat.st_mtime}


def read_toc(path: Path) -> list[dict[str, Any]]:
    """Return the PDF outline as calpdf's JSON structure."""
    with _calpdf_errors():
        validate_input_file(path, label="PDF")
        with pikepdf.open(path) as pdf:
            page_map = {page.obj.objgen: i for i, page in enumerate(pdf.pages)}
            with pdf.open_outline() as outline:
                return toc_mod.extract_outline(outline.root, pdf, page_map)


def read_toc_file(path: Path, pages: int) -> list[dict[str, Any]]:
    """Read and validate a ToC JSON file before loading it into the tree."""
    with _calpdf_errors():
        validate_input_file(path, label="ToC file")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OperationError(f"{path.name} is not valid JSON.\n{exc}") from exc
        errors = toc_mod.validate_toc(data, pages)
        if errors:
            raise OperationError("\n".join(errors[:8]))
        return data


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
        validate_input_file(path, label="PDF")
        with pikepdf.open(path) as pdf:
            pages = len(pdf.pages)
        if pages == 0:
            raise OperationError("The PDF has no pages.")
        validate_entries(entries, pages)

        output_file, backup_file = normalize_paths(path)
        ensure_backup(output_file, backup_file)
        with tempfile.TemporaryDirectory(dir=str(output_file.parent)) as tmp:
            temp_output = Path(tmp) / output_file.name
            with pikepdf.open(backup_file) as pdf:
                # After the first write the backup is the source of truth.
                validate_entries(entries, len(pdf.pages))
                with pdf.open_outline() as outline:
                    outline.root.clear()
                    for item in toc_mod.build_outline_items(pdf, entries):
                        outline.root.append(item)
                pdf.save(temp_output)
            temp_output.replace(output_file)
        return toc_mod.count_toc_entries(entries)


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
    force: bool = False,
) -> dict[str, Any]:
    """Optimize in place and report the size change and qpdf warnings."""
    with _calpdf_errors():
        validate_input_file(path, label="PDF")
        before = path.stat().st_size
        output_file, backup_file = normalize_paths(path)
        ensure_backup(output_file, backup_file)
        qpdf_bin = optimize_mod.find_binary("qpdf")
        warnings = ""

        with tempfile.TemporaryDirectory(dir=str(output_file.parent)) as tmp:
            workdir = Path(tmp)
            source = backup_file
            if strip_color:
                stripped = workdir / "pre_optimize.pdf"
                optimize_mod.strip_color_profiles(source, stripped)
                source = stripped

            temp_output = workdir / output_file.name
            result = optimize_mod.qpdf_optimize(
                qpdf_bin, source, temp_output, keep_metadata=keep_metadata
            )

            if result.returncode not in (0, 3) and not force:
                detail = result.stderr.strip()
                raise OperationError(
                    f"qpdf failed with exit code {result.returncode}."
                    + (f"\n{detail}" if detail else "")
                )
            if result.returncode == 3:
                warnings = result.stderr.strip()
            if not temp_output.is_file() or temp_output.stat().st_size == 0:
                raise OperationError(
                    f"qpdf produced no output (exit code {result.returncode})."
                )

            temp_output.replace(output_file)

        return {
            "before": before,
            "after": output_file.stat().st_size,
            "warnings": warnings,
        }


def restore_backup(path: Path) -> None:
    """Put the backup back and drop it, matching `calpdf restore`."""
    with _calpdf_errors():
        output_file, backup_file = normalize_paths(path)
        if not backup_file.is_file():
            raise OperationError(f"No backup found at {backup_file.name}.")
        shutil.copy2(backup_file, output_file)
        backup_file.unlink()
