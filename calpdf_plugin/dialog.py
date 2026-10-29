"""The CalPDF dialog.

The widget layer knows nothing about Calibre. It receives a :class:`Book`
and a callback, which keeps it renderable from a plain QApplication for
layout checks.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from calpdf.output import format_size, format_size_change
from calpdf.replace import FitMode, Mode
from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStyledItemDelegate,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import backend
from .icons import calpdf_icon

PREVIEW_WIDTH = 138
PREVIEW_HEIGHT = 184


@dataclass
class Book:
    path: Path
    title: str = ""
    authors: str = ""
    identifiers: dict[str, str] = field(default_factory=dict)


class _Worker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, task: Callable[[], Any], parent: QWidget | None = None):
        super().__init__(parent)
        self._task = task

    def run(self) -> None:
        try:
            self.done.emit(self._task())
        except backend.OperationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # keep a crash out of the GUI thread
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")


class _PageDelegate(QStyledItemDelegate):
    """Spin box editor for the page column."""

    def __init__(self, pages: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.pages = max(1, pages)

    def createEditor(self, parent, option, index):  # noqa: N802
        editor = QSpinBox(parent)
        editor.setRange(1, self.pages)
        editor.setFrame(False)
        return editor

    def setEditorData(self, editor, index):  # noqa: N802
        value = index.data(Qt.ItemDataRole.UserRole)
        editor.setValue(value if isinstance(value, int) else 1)

    def setModelData(self, editor, model, index):  # noqa: N802
        value = int(editor.value())
        model.setData(index, value, Qt.ItemDataRole.UserRole)
        model.setData(index, str(value), Qt.ItemDataRole.DisplayRole)


def _hint(text: str, parent: QWidget | None = None) -> QLabel:
    label = QLabel(text, parent)
    label.setWordWrap(True)
    label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    return label


class CalPDFDialog(QDialog):
    def __init__(
        self,
        book: Book,
        on_changed: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.book = book
        self.on_changed = on_changed
        self._worker: _Worker | None = None
        self._cover_dir = Path(tempfile.mkdtemp(prefix="calpdf-cover-"))
        self._downloaded: Path | None = None
        self._downloaded_id = ""
        self._pages = 0
        self._info: dict[str, Any] = {}

        self.setWindowTitle(f"CalPDF — {book.title or book.path.name}")
        self.setWindowIcon(calpdf_icon())
        self.resize(820, 640)
        self.setMinimumSize(700, 540)

        self._build()
        self.reload()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(12)

        outer.addLayout(self._build_header())

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_info_tab(), "Info")
        self.tabs.addTab(self._build_cover_tab(), "Cover")
        self.tabs.addTab(self._build_contents_tab(), "Contents")
        self.tabs.addTab(self._build_optimize_tab(), "Optimize")
        self.tabs.addTab(self._build_backup_tab(), "Backup")
        outer.addWidget(self.tabs, 1)

        outer.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.header_icon = QLabel(self)
        self.header_icon.setPixmap(calpdf_icon().pixmap(44, 44))
        row.addWidget(self.header_icon, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(2)
        self.title_label = QLabel(self.book.title or "Untitled", self)
        font = QFont(self.title_label.font())
        font.setPointSizeF(font.pointSizeF() + 2.5)
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        text.addWidget(self.title_label)

        self.subtitle_label = QLabel(self)
        self.subtitle_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.subtitle_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        text.addWidget(self.subtitle_label)
        row.addLayout(text, 1)

        self.summary_label = QLabel(self)
        self.summary_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )
        self.summary_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        row.addWidget(self.summary_label, 0)
        return row

    def _build_info_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        document = QGroupBox("Document", page)
        form = QFormLayout(document)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        # Some styles size fields to their hint, which wraps the file path
        # early and clips the rest. The values should use the whole width.
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._info_rows: dict[str, QLabel] = {}
        for key, label in (
            ("file", "File"),
            ("pages", "Pages"),
            ("size", "Size"),
            ("version", "PDF version"),
            ("bookmarks", "Bookmarks"),
            ("backup", "Backup"),
        ):
            value = QLabel("—", document)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            self._info_rows[key] = value
            form.addRow(label, value)
        layout.addWidget(document)

        layout.addWidget(
            _hint(
                "calpdf keeps a .bak copy the first time it changes a PDF. "
                "The Backup tab restores it."
            )
        )
        layout.addStretch(1)
        return page

    def _build_cover_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(12)

        source = QGroupBox("Source", page)
        source_layout = QVBoxLayout(source)
        source_layout.setSpacing(6)

        download_row = QHBoxLayout()
        self.cover_download_radio = QRadioButton("Download by identifier", source)
        self.cover_id = QLineEdit(source)
        self.cover_id.setPlaceholderText("ASIN or ISBN")
        self.cover_preview_button = QPushButton("Preview", source)
        download_row.addWidget(self.cover_download_radio)
        download_row.addWidget(self.cover_id, 1)
        download_row.addWidget(self.cover_preview_button)
        source_layout.addLayout(download_row)

        self.cover_identifier_hint = _hint("", source)
        source_layout.addWidget(self.cover_identifier_hint)

        file_row = QHBoxLayout()
        self.cover_file_radio = QRadioButton("Use an image file", source)
        self.cover_file = QLineEdit(source)
        self.cover_file.setPlaceholderText("PNG or JPEG")
        self.cover_browse_button = QPushButton("Browse…", source)
        file_row.addWidget(self.cover_file_radio)
        file_row.addWidget(self.cover_file, 1)
        file_row.addWidget(self.cover_browse_button)
        source_layout.addLayout(file_row)
        left.addWidget(source)

        placement = QGroupBox("Placement", page)
        form = QFormLayout(placement)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.cover_mode = QComboBox(placement)
        self.cover_mode.addItem("Replace the first page(s)", Mode.replace)
        self.cover_mode.addItem("Prepend before the first page", Mode.insert)
        self.cover_pages = QSpinBox(placement)
        self.cover_pages.setRange(1, 50)
        self.cover_fit = QComboBox(placement)
        self.cover_fit.addItem("Match the page width", FitMode.match_width)
        self.cover_fit.addItem("Fill the page, cropping", FitMode.fill)
        self.cover_fit.addItem("Fit inside the page", FitMode.fit)
        self.cover_dpi = QSpinBox(placement)
        self.cover_dpi.setRange(72, 1200)
        self.cover_dpi.setValue(300)
        self.cover_dpi.setSuffix(" dpi")
        form.addRow("Mode", self.cover_mode)
        form.addRow("Pages", self.cover_pages)
        form.addRow("Fit", self.cover_fit)
        form.addRow("Resolution", self.cover_dpi)
        left.addWidget(placement)
        left.addStretch(1)

        self.cover_apply_button = QPushButton("Apply cover", page)
        self.cover_apply_button.setDefault(False)
        left.addWidget(self.cover_apply_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(left, 1)

        preview_column = QVBoxLayout()
        preview_column.setSpacing(6)
        self.cover_preview = QLabel("No preview", page)
        self.cover_preview.setFixedSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self.cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_preview.setFrameShape(QLabel.Shape.StyledPanel)
        self.cover_preview.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        preview_column.addWidget(self.cover_preview)
        preview_column.addStretch(1)
        layout.addLayout(preview_column, 0)

        self.cover_download_radio.setChecked(True)
        self.cover_download_radio.toggled.connect(self._sync_cover_source)
        self.cover_file.textChanged.connect(self._sync_cover_source)
        self.cover_browse_button.clicked.connect(self._browse_cover_file)
        self.cover_preview_button.clicked.connect(self._preview_cover)
        self.cover_apply_button.clicked.connect(self._apply_cover)
        self._sync_cover_source()
        return page

    def _build_contents_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.tree = QTreeWidget(page)
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Bookmark", "Page"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 72)
        self._page_delegate = _PageDelegate(1, self.tree)
        self.tree.setItemDelegateForColumn(1, self._page_delegate)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.toc_add_button = QPushButton("Add", page)
        self.toc_child_button = QPushButton("Add child", page)
        self.toc_remove_button = QPushButton("Remove", page)
        self.toc_up_button = QPushButton("Move up", page)
        self.toc_down_button = QPushButton("Move down", page)
        self.toc_import_button = QPushButton("Import…", page)
        self.toc_export_button = QPushButton("Export…", page)
        self.toc_revert_button = QPushButton("Revert", page)
        for button in (
            self.toc_add_button,
            self.toc_child_button,
            self.toc_remove_button,
        ):
            buttons.addWidget(button)
        buttons.addSpacing(10)
        buttons.addWidget(self.toc_up_button)
        buttons.addWidget(self.toc_down_button)
        buttons.addStretch(1)
        for button in (
            self.toc_import_button,
            self.toc_export_button,
            self.toc_revert_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        footer = QHBoxLayout()
        footer.addWidget(
            _hint("Double-click a title or page to edit it. Apply saves a .bak first."),
            1,
        )
        self.toc_apply_button = QPushButton("Apply bookmarks", page)
        footer.addWidget(self.toc_apply_button)
        layout.addLayout(footer)

        self.toc_add_button.clicked.connect(self._add_bookmark)
        self.toc_child_button.clicked.connect(self._add_child_bookmark)
        self.toc_remove_button.clicked.connect(self._remove_bookmark)
        self.toc_up_button.clicked.connect(lambda: self._move_bookmark(-1))
        self.toc_down_button.clicked.connect(lambda: self._move_bookmark(1))
        self.toc_import_button.clicked.connect(self._import_toc)
        self.toc_export_button.clicked.connect(self._export_toc)
        self.toc_revert_button.clicked.connect(self._load_toc)
        self.toc_apply_button.clicked.connect(self._apply_toc)
        return page

    def _build_optimize_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        group = QGroupBox("qpdf settings", page)
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)
        group_layout.addWidget(
            _hint(
                "Linearizes the file and recompresses its streams. "
                "Images are optimized losslessly. The first run keeps a .bak."
            )
        )
        self.optimize_strip = QCheckBox("Strip ICC color profiles", group)
        self.optimize_keep_metadata = QCheckBox(
            "Keep the document metadata (title, author)", group
        )
        group_layout.addWidget(self.optimize_strip)
        group_layout.addWidget(self.optimize_keep_metadata)
        layout.addWidget(group)

        self.optimize_result = QLabel("", page)
        self.optimize_result.setWordWrap(True)
        self.optimize_result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.optimize_result)
        layout.addStretch(1)

        self.optimize_apply_button = QPushButton("Optimize PDF", page)
        self.optimize_apply_button.clicked.connect(self._optimize)
        layout.addWidget(self.optimize_apply_button, 0, Qt.AlignmentFlag.AlignRight)
        return page

    def _build_backup_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        group = QGroupBox("Backup", page)
        form = QFormLayout(group)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.backup_path = QLabel("—", group)
        self.backup_path.setWordWrap(True)
        self.backup_size = QLabel("—", group)
        self.backup_time = QLabel("—", group)
        form.addRow("File", self.backup_path)
        form.addRow("Size", self.backup_size)
        form.addRow("Created", self.backup_time)
        layout.addWidget(group)

        layout.addWidget(
            _hint(
                "Restoring copies the backup over the PDF and deletes the "
                "backup, exactly like running calpdf restore."
            )
        )
        layout.addStretch(1)
        self.restore_button = QPushButton("Restore from backup", page)
        self.restore_button.clicked.connect(self._restore)
        layout.addWidget(self.restore_button, 0, Qt.AlignmentFlag.AlignRight)
        return page

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.status_label = QLabel("Ready", self)
        self.status_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        row.addWidget(self.status_label, 1)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(120)
        self.progress.setTextVisible(False)
        self.progress.hide()
        row.addWidget(self.progress)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.accept)
        row.addWidget(self.close_button)
        return row

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def reload(self) -> None:
        try:
            info = backend.read_info(self.book.path)
        except backend.OperationError as exc:
            self.status_label.setText("Could not read the PDF.")
            self._show_error(str(exc))
            return

        self._info = info
        self._pages = int(info["pages"])
        size = format_size(info["sizeBytes"])
        self.summary_label.setText(f"{self._pages} pages · {size}")
        self.subtitle_label.setText(str(self.book.path))

        self._info_rows["file"].setText(str(self.book.path))
        self._info_rows["pages"].setText(self._page_description(info))
        self._info_rows["size"].setText(size)
        self._info_rows["version"].setText(str(info["version"]))
        outline = info["outline"]
        self._info_rows["bookmarks"].setText(
            f"{outline['total']} total, {outline['topLevel']} top-level"
        )

        backup = info.get("backup")
        if backup:
            self._info_rows["backup"].setText(
                f"{backup['path'].name} · {format_size(backup['size'])}"
            )
            self.backup_path.setText(str(backup["path"]))
            self.backup_size.setText(format_size(backup["size"]))
            self.backup_time.setText(
                datetime.fromtimestamp(backup["mtime"]).strftime("%Y-%m-%d %H:%M")
            )
            self.restore_button.setEnabled(True)
        else:
            self._info_rows["backup"].setText("No backup yet")
            self.backup_path.setText("No backup yet")
            self.backup_size.setText("—")
            self.backup_time.setText("—")
            self.restore_button.setEnabled(False)

        self._fill_identifiers()
        self._page_delegate.pages = max(1, self._pages)
        self._load_toc()

    def _page_description(self, info: dict[str, Any]) -> str:
        parts = [str(info["pages"])]
        detail = info.get("pagesDetail") or []
        if detail:
            first = detail[0]
            width = first["width"] / 72
            height = first["height"] / 72
            parts.append(f"{width:.1f} × {height:.1f} in")
            sizes = {
                (round(entry["width"]), round(entry["height"])) for entry in detail
            }
            if len(sizes) > 1:
                parts.append("mixed page sizes")
        return " · ".join(parts)

    def _fill_identifiers(self) -> None:
        identifiers = self.book.identifiers or {}
        preferred = identifiers.get("amazon") or identifiers.get("isbn") or ""
        self.cover_id.setText(preferred)
        if identifiers:
            shown = ", ".join(f"{key} {value}" for key, value in identifiers.items())
            self.cover_identifier_hint.setText(f"From this book: {shown}")
        else:
            self.cover_identifier_hint.setText(
                "This book has no identifiers. Enter an ASIN or ISBN."
            )

    def _load_toc(self) -> None:
        try:
            entries = backend.read_toc(self.book.path)
        except backend.OperationError as exc:
            self._show_error(str(exc))
            return
        self._populate_tree(entries)
        self.status_label.setText("Ready")

    def _populate_tree(self, entries: list[dict[str, Any]]) -> None:
        self.tree.clear()

        def add(parent, entry):
            item = QTreeWidgetItem(parent)
            item.setText(0, str(entry.get("title", "")))
            page = entry.get("pageNumber")
            self._set_page(item, page)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )
            for child in entry.get("children", []):
                add(item, child)

        for entry in entries:
            add(self.tree.invisibleRootItem(), entry)
        self.tree.expandAll()

    @staticmethod
    def _set_page(item: QTreeWidgetItem, page: Any) -> None:
        if isinstance(page, int):
            item.setData(1, Qt.ItemDataRole.UserRole, page)
            item.setText(1, str(page))
        else:
            item.setData(1, Qt.ItemDataRole.UserRole, None)
            item.setText(1, "—")
            item.setToolTip(1, "No page target. Double-click to set one.")

    # ------------------------------------------------------------------
    # Contents editing
    # ------------------------------------------------------------------

    def _new_bookmark(self, page: int = 1) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setText(0, "New bookmark")
        self._set_page(item, page)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )
        return item

    def _add_bookmark(self) -> None:
        current = self.tree.currentItem()
        if current is None:
            self.tree.addTopLevelItem(self._new_bookmark())
            self.tree.setCurrentItem(
                self.tree.topLevelItem(self.tree.topLevelItemCount() - 1)
            )
        else:
            parent = current.parent() or self.tree.invisibleRootItem()
            index = parent.indexOfChild(current) + 1
            parent.insertChild(index, self._new_bookmark())
            self.tree.setCurrentItem(parent.child(index))

    def _add_child_bookmark(self) -> None:
        current = self.tree.currentItem()
        if current is None:
            self._add_bookmark()
            return
        item = self._new_bookmark()
        current.addChild(item)
        current.setExpanded(True)
        self.tree.setCurrentItem(item)

    def _remove_bookmark(self) -> None:
        current = self.tree.currentItem()
        if current is None:
            return
        parent = current.parent() or self.tree.invisibleRootItem()
        parent.removeChild(current)

    def _move_bookmark(self, delta: int) -> None:
        current = self.tree.currentItem()
        if current is None:
            return
        parent = current.parent() or self.tree.invisibleRootItem()
        index = parent.indexOfChild(current)
        target = index + delta
        if target < 0 or target >= parent.childCount():
            return
        parent.takeChild(index)
        parent.insertChild(target, current)
        self.tree.setCurrentItem(current)

    def _import_toc(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import bookmarks", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            entries = backend.read_toc_file(Path(path), self._pages)
        except backend.OperationError as exc:
            self._show_error(str(exc))
            return
        self._populate_tree(entries)
        self.status_label.setText(f"Loaded {Path(path).name}")

    def _export_toc(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export bookmarks", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            entries = self._collect_entries()
            backend.write_toc_file(Path(path), entries)
        except backend.OperationError as exc:
            self._show_error(str(exc))
            return
        self.status_label.setText(f"Exported to {Path(path).name}")

    def _collect_entries(self) -> list[dict[str, Any]]:
        def collect(parent) -> list[dict[str, Any]]:
            entries = []
            for index in range(parent.childCount()):
                item = parent.child(index)
                title = item.text(0).strip()
                if not title:
                    raise backend.OperationError("Every bookmark needs a title.")
                page = item.data(1, Qt.ItemDataRole.UserRole)
                if not isinstance(page, int):
                    raise backend.OperationError(
                        f"The bookmark “{title}” has no page. Set one before applying."
                    )
                entries.append(
                    {
                        "title": title,
                        "pageNumber": page,
                        "children": collect(item),
                    }
                )
            return entries

        entries = collect(self.tree.invisibleRootItem())
        backend.validate_entries(entries, self._pages)
        return entries

    def _apply_toc(self) -> None:
        try:
            entries = self._collect_entries()
        except backend.OperationError as exc:
            self._show_error(str(exc))
            return

        self._run(
            "Writing bookmarks…",
            lambda: backend.write_toc(self.book.path, entries),
            lambda count: self._after_change(f"{count} bookmarks written."),
        )

    # ------------------------------------------------------------------
    # Cover
    # ------------------------------------------------------------------

    def _sync_cover_source(self) -> None:
        download = self.cover_download_radio.isChecked()
        self.cover_id.setEnabled(download)
        self.cover_preview_button.setEnabled(download)
        self.cover_file.setEnabled(not download)
        self.cover_browse_button.setEnabled(not download)
        if not download and self.cover_file.text().strip():
            self._show_preview(Path(self.cover_file.text().strip()))
        elif not download:
            self._clear_preview("Choose an image")

    def _browse_cover_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a cover image", "", "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            self.cover_file.setText(path)
            self.cover_file.setCursorPosition(0)

    def _show_preview(self, path: Path) -> None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._clear_preview("No preview")
            return
        self.cover_preview.setPixmap(
            pixmap.scaled(
                QSize(PREVIEW_WIDTH - 8, PREVIEW_HEIGHT - 8),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.cover_preview.setToolTip(str(path))

    def _clear_preview(self, text: str) -> None:
        self.cover_preview.setPixmap(QPixmap())
        self.cover_preview.setText(text)
        self.cover_preview.setToolTip("")

    def _preview_cover(self) -> None:
        book_id = self.cover_id.text().strip()
        if not book_id:
            self._show_error("Enter an ASIN or ISBN first.")
            return

        def task():
            image = backend.fetch_cover(book_id, self._cover_dir)
            return book_id, image

        self._run("Downloading cover…", task, self._preview_done)

    def _preview_done(self, result) -> None:
        book_id, image = result
        self._downloaded = image
        self._downloaded_id = book_id
        self._show_preview(image)
        self.status_label.setText("Cover downloaded. Apply it to use it.")

    def _apply_cover(self) -> None:
        download = self.cover_download_radio.isChecked()
        book_id = self.cover_id.text().strip()
        image_file = self.cover_file.text().strip()

        if download and not book_id:
            self._show_error("Enter an ASIN or ISBN first.")
            return
        if not download and not image_file:
            self._show_error("Choose an image file first.")
            return

        mode = self.cover_mode.currentData()
        fit = self.cover_fit.currentData()
        pages = self.cover_pages.value()
        dpi = self.cover_dpi.value()
        path = self.book.path

        def task():
            if download:
                if self._downloaded and self._downloaded_id == book_id:
                    image = self._downloaded
                else:
                    image = backend.fetch_cover(book_id, self._cover_dir)
            else:
                image = Path(image_file)
            backend.apply_cover(
                path, image, mode=mode, pages=pages, dpi=dpi, fit_mode=fit
            )
            return image, book_id

        self._run("Applying cover…", task, self._cover_applied)

    def _cover_applied(self, result) -> None:
        image, book_id = result
        self._downloaded = image
        self._downloaded_id = book_id
        self._show_preview(image)
        self._after_change("Cover applied.")

    # ------------------------------------------------------------------
    # Optimize and restore
    # ------------------------------------------------------------------

    def _optimize(self) -> None:
        strip = self.optimize_strip.isChecked()
        keep = self.optimize_keep_metadata.isChecked()
        path = self.book.path

        def task():
            return backend.optimize_pdf(path, strip_color=strip, keep_metadata=keep)

        self._run("Optimizing with qpdf…", task, self._optimized)

    def _optimized(self, result) -> None:
        self.optimize_result.setText(format_size_change(result.before, result.after))
        message = "Optimized."
        if result.stderr:
            message = "Optimized, with qpdf warnings. See the details below."
            self.optimize_result.setToolTip(result.stderr)
        self._after_change(message)

    def _restore(self) -> None:
        answer = QMessageBox.question(
            self,
            "Restore backup",
            "Replace the PDF with its .bak copy and delete the backup?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run(
            "Restoring backup…",
            lambda: backend.restore_backup(self.book.path),
            lambda _: self._after_change("Backup restored."),
        )

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def _run(
        self,
        label: str,
        task: Callable[[], Any],
        on_done: Callable[[Any], None],
    ) -> None:
        if self._worker is not None:
            return
        self._set_busy(True, label)
        worker = _Worker(task, self)
        worker.done.connect(lambda result: self._job_done(on_done, result))
        worker.failed.connect(self._job_failed)
        worker.finished.connect(self._job_finished)
        self._worker = worker
        worker.start()

    def _job_done(self, on_done: Callable[[Any], None], result: Any) -> None:
        self._set_busy(False, "")
        try:
            on_done(result)
        except Exception as exc:
            self._show_error(str(exc))

    def _job_failed(self, message: str) -> None:
        self._set_busy(False, "The operation failed.")
        self._show_error(message)

    def _job_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()

    def _set_busy(self, busy: bool, label: str) -> None:
        self.tabs.setEnabled(not busy)
        self.close_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        if label:
            self.status_label.setText(label)

    def _after_change(self, message: str) -> None:
        self.reload()
        self.status_label.setText(message)
        if self.on_changed is not None:
            self.on_changed()

    def _show_error(self, message: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("CalPDF")
        lines = message.strip().splitlines()
        box.setText(lines[0] if lines else "Something went wrong.")
        if len(lines) > 1:
            box.setInformativeText("\n".join(lines[1:]))
        box.exec()

    # ------------------------------------------------------------------
    # Window
    # ------------------------------------------------------------------

    def closeEvent(self, event):  # noqa: N802
        if self._worker is not None:
            self.status_label.setText("Wait for the current operation to finish.")
            event.ignore()
            return
        shutil.rmtree(self._cover_dir, ignore_errors=True)
        super().closeEvent(event)
