from __future__ import annotations

import shutil

import pikepdf
import pytest
from PIL import Image

from calpdf_plugin import backend


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "book.pdf"
    make_pdf(path, pages=3)
    return path


def make_pdf(path, pages: int = 3, bookmarks: bool = True) -> None:
    with pikepdf.new() as pdf:
        for _ in range(pages):
            pdf.add_blank_page(page_size=(432, 648))
        if bookmarks:
            with pdf.open_outline() as outline:
                outline.root.append(pikepdf.OutlineItem("Chapter 1", 0))
                chapter = pikepdf.OutlineItem("Chapter 2", 1)
                chapter.children.append(pikepdf.OutlineItem("Section 2.1", 2))
                outline.root.append(chapter)
        pdf.save(path)


def page_count(path) -> int:
    with pikepdf.open(path) as pdf:
        return len(pdf.pages)


def cover_image(tmp_path):
    path = tmp_path / "cover.png"
    Image.new("RGB", (600, 900), (40, 90, 160)).save(path)
    return path


def test_read_info_reports_document_properties(pdf):
    info = backend.read_info(pdf)

    assert info["pages"] == 3
    assert info["sizeBytes"] == pdf.stat().st_size
    assert info["outline"] == {"topLevel": 2, "total": 3}
    assert info["backup"] is None


def test_read_toc_keeps_titles_and_pages(pdf):
    entries = backend.read_toc(pdf)

    assert [entry["title"] for entry in entries] == ["Chapter 1", "Chapter 2"]
    assert entries[0]["pageNumber"] == 1
    assert entries[1]["children"][0]["pageNumber"] == 3


def test_write_toc_round_trips_and_keeps_a_backup(pdf):
    entries = backend.read_toc(pdf)
    entries[0]["title"] = "Introduction"

    written = backend.write_toc(pdf, entries)

    assert written == 3
    assert backend.read_toc(pdf)[0]["title"] == "Introduction"
    backup = backend.backup_for(pdf)
    assert backup.is_file()
    assert page_count(backup) == 3
    assert backend.read_info(pdf)["backup"]["size"] == backup.stat().st_size


def test_write_toc_rejects_a_page_past_the_end(pdf):
    entries = backend.read_toc(pdf)
    entries[0]["pageNumber"] = 99

    before = pdf.read_bytes()
    with pytest.raises(backend.OperationError, match="exceeds total pages"):
        backend.write_toc(pdf, entries)

    assert pdf.read_bytes() == before
    assert not backend.backup_for(pdf).exists()


def test_write_toc_rejects_a_missing_title(pdf):
    entries = backend.read_toc(pdf)
    entries[0]["title"] = "   "

    with pytest.raises(backend.OperationError, match="must not be empty"):
        backend.write_toc(pdf, entries)


def test_apply_cover_inserts_a_page_and_restore_undoes_it(pdf, tmp_path):
    original_pages = page_count(pdf)

    backend.apply_cover(
        pdf,
        cover_image(tmp_path),
        mode=backend.replace_mod.Mode.insert,
        pages=1,
        dpi=150,
        fit_mode=backend.replace_mod.FitMode.match_width,
    )

    assert page_count(pdf) == original_pages + 1
    assert backend.backup_for(pdf).is_file()

    backend.restore_backup(pdf)

    assert page_count(pdf) == original_pages
    assert not backend.backup_for(pdf).exists()


def test_restore_without_a_backup_reports_it(pdf):
    with pytest.raises(backend.OperationError, match="No backup found"):
        backend.restore_backup(pdf)


@pytest.mark.skipif(shutil.which("qpdf") is None, reason="qpdf is not installed")
def test_optimize_reports_the_size_change(pdf):
    result = backend.optimize_pdf(pdf)

    assert result["before"] > 0
    assert result["after"] > 0
    assert page_count(pdf) == 3
    assert backend.backup_for(pdf).is_file()


def test_toc_file_round_trip(pdf, tmp_path):
    entries = backend.read_toc(pdf)
    path = tmp_path / "toc.json"

    backend.write_toc_file(path, entries)
    loaded = backend.read_toc_file(path, pages=3)

    assert loaded == entries


def test_toc_file_rejects_entries_without_a_page(pdf, tmp_path):
    path = tmp_path / "toc.json"
    path.write_text('[{"title": "Loose end", "children": []}]', encoding="utf-8")

    with pytest.raises(backend.OperationError, match="missing 'pageNumber'"):
        backend.read_toc_file(path, pages=3)
