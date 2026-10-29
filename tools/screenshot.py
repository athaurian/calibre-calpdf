#!/usr/bin/env python3
"""Render the dialog offscreen for the README and the calpdf documentation."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "2")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pikepdf  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from calpdf_plugin.dialog import Book, CalPDFDialog  # noqa: E402
from calpdf_plugin.icons import calpdf_icon  # noqa: E402

SCRATCH = ROOT / "build" / "ui"
OUT = ROOT / "docs" / "screenshots"

PAGES = 120
COVER_SIZE = (600, 900)

# Keep the backup timestamp stable so reruns produce the same images.
DEMO_MTIME = 1_789_000_000

DEMO_NAME = "the-brothers-karamazov.pdf"
DEMO_PATH = Path("/home/user/Books") / DEMO_NAME
DEMO_BACKUP = f"{DEMO_PATH}.bak"

FONTS = {
    False: (
        "/usr/share/fonts/adobe-source-sans/SourceSans3-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    ),
    True: (
        "/usr/share/fonts/adobe-source-sans/SourceSans3-Bold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    ),
}


def _font(size: int, *, bold: bool = False):
    for candidate in FONTS[bold]:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _fill_gradient(draw: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    width, height = size
    top = (24, 48, 82)
    bottom = (78, 124, 146)
    for y in range(height):
        ratio = y / (height - 1)
        color = tuple(
            round(start + (end - start) * ratio)
            for start, end in zip(top, bottom, strict=False)
        )
        draw.line([(0, y), (width, y)], fill=color)


def sample_cover(path: Path) -> None:
    image = Image.new("RGB", COVER_SIZE)
    draw = ImageDraw.Draw(image)
    _fill_gradient(draw, COVER_SIZE)
    width, height = COVER_SIZE

    draw.rectangle((30, 30, width - 30, height - 30), outline=(238, 242, 246), width=2)
    draw.text(
        (width / 2, 86),
        "A  N O V E L",
        font=_font(18),
        fill=(226, 234, 241),
        anchor="ma",
    )

    title_font = _font(64, bold=True)
    for y, line in ((200, "The"), (278, "Brothers"), (356, "Karamazov")):
        draw.text(
            (width / 2, y),
            line,
            font=title_font,
            fill=(250, 250, 250),
            anchor="ma",
        )

    draw.line((80, 548, width - 80, 548), fill=(226, 234, 241), width=1)
    draw.text(
        (width / 2, 576),
        "Fyodor Dostoevsky",
        font=_font(26),
        fill=(226, 234, 241),
        anchor="ma",
    )
    image.save(path)


def _page_content(number: int) -> bytes:
    bars = []
    for row in range(16):
        y = 574 - row * 32
        if row == 0:
            width, value, height = 210, "0.55", 12
        else:
            width = 150 + (number * 37 + row * 61) % 140
            value, height = "0.80", 7
        bars.append(f"{value} g 54 {y} {width} {height} re f")
    return "\n".join(bars).encode()


def sample_pdf(path: Path) -> None:
    with pikepdf.new() as pdf:
        for number in range(1, PAGES + 1):
            page = pdf.add_blank_page(page_size=(432, 648))
            page.Contents = pdf.make_stream(_page_content(number))

        with pdf.open_outline() as outline:
            outline.root.append(pikepdf.OutlineItem("Preface", 0))

            part = pikepdf.OutlineItem("Part One: The Long Road", 2)
            for title, page in (
                ("A Quiet Start", 4),
                ("Crossing the Valley", 13),
                ("The Last Mile", 26),
            ):
                part.children.append(pikepdf.OutlineItem(title, page))
            outline.root.append(part)

            part = pikepdf.OutlineItem("Part Two: Maps and Margins", 34)
            for title, page in (
                ("What the River Keeps", 41),
                ("A Season of Rain", 58),
                ("Notes from the Edge", 77),
            ):
                part.children.append(pikepdf.OutlineItem(title, page))
            outline.root.append(part)

            outline.root.append(pikepdf.OutlineItem("Afterword", 104))
            outline.root.append(pikepdf.OutlineItem("Index", 114))

        pdf.save(path)


def main() -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    pdf = SCRATCH / DEMO_NAME
    cover = SCRATCH / "cover.png"
    sample_pdf(pdf)
    sample_cover(cover)
    backup = pdf.with_suffix(".pdf.bak")
    shutil.copyfile(pdf, backup)
    os.utime(backup, (DEMO_MTIME, DEMO_MTIME))

    # The cover field looks like a real selection without clipping a long
    # repository path: keep the file name relative to the scratch directory.
    os.chdir(SCRATCH)

    app = QApplication([])
    book = Book(
        path=pdf,
        title="The Brothers Karamazov",
        authors="Fyodor Dostoevsky",
        identifiers={"isbn": "9780000000000", "amazon": "B0TEST0000"},
    )
    dialog = CalPDFDialog(book)
    dialog.cover_file_radio.setChecked(True)
    dialog.cover_file.setText(cover.name)

    # The dialog has read the real file by now. Show an anonymous location in
    # the screenshots instead of this checkout's home directory.
    dialog.subtitle_label.setText(str(DEMO_PATH))
    dialog._info_rows["file"].setText(str(DEMO_PATH))
    dialog.backup_path.setText(DEMO_BACKUP)
    dialog.show()

    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        app.processEvents()
        app.processEvents()
        name = dialog.tabs.tabText(index).lower()
        dialog.grab().save(str(OUT / f"{name}.png"))

    calpdf_icon().pixmap(128, 128).save(str(OUT / "icon.png"))
    dialog.close()
    print(f"wrote {len(list(OUT.glob('*.png')))} images to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
