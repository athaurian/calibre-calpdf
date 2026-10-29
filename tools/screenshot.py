#!/usr/bin/env python3
"""Render the dialog offscreen so the layout can be checked without Calibre."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pikepdf  # noqa: E402
from PIL import Image  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from calpdf_plugin.dialog import Book, CalPDFDialog  # noqa: E402
from calpdf_plugin.icons import calpdf_icon  # noqa: E402

OUT = ROOT / "build" / "ui"


def sample_pdf(path: Path) -> None:
    with pikepdf.new() as pdf:
        for _ in range(4):
            pdf.add_blank_page(page_size=(432, 648))
        with pdf.open_outline() as outline:
            outline.root.append(pikepdf.OutlineItem("Preface", 0))
            chapter = pikepdf.OutlineItem("The Long Road", 1)
            chapter.children.append(pikepdf.OutlineItem("A Quiet Start", 1))
            chapter.children.append(pikepdf.OutlineItem("Crossing", 2))
            outline.root.append(chapter)
            outline.root.append(pikepdf.OutlineItem("Index", 3))
        pdf.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pdf = OUT / "sample.pdf"
    if not pdf.exists():
        sample_pdf(pdf)
    cover = OUT / "cover.png"
    if not cover.exists():
        Image.new("RGB", (600, 900), (38, 92, 158)).save(cover)

    app = QApplication([])
    book = Book(
        path=pdf,
        title="A Field Guide to Quiet Places",
        authors="Hanif Athaurrahman",
        identifiers={"isbn": "9780000000000", "amazon": "B0TEST0000"},
    )
    dialog = CalPDFDialog(book)
    dialog.cover_file_radio.setChecked(True)
    dialog.cover_file.setText(str(cover))
    dialog.show()

    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        app.processEvents()
        name = dialog.tabs.tabText(index).lower()
        dialog.grab().save(str(OUT / f"{index + 1}-{name}.png"))

    calpdf_icon().pixmap(64, 64).save(str(OUT / "icon-64.png"))
    calpdf_icon().pixmap(24, 24).save(str(OUT / "icon-24.png"))
    dialog.close()
    print(f"wrote {len(list(OUT.glob('*.png')))} images to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
