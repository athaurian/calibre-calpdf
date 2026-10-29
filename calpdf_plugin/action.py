"""The Calibre action that opens the CalPDF dialog for the selected book."""

from __future__ import annotations

from pathlib import Path

from calibre.gui2 import error_dialog, gprefs
from calibre.gui2.actions import InterfaceAction
from calibre.utils.logging import default_log

from .dialog import Book, CalPDFDialog
from .icons import calpdf_icon

PLUGIN_TITLE = "CalPDF"


class CalPDFAction(InterfaceAction):
    name = PLUGIN_TITLE
    action_spec = (PLUGIN_TITLE, None, "Work on this book's PDF with calpdf", ())
    action_type = "current"
    action_add_menu = False

    def genesis(self) -> None:
        self.qaction.setIcon(calpdf_icon())
        self.qaction.triggered.connect(lambda *_: self.show_dialog())

    def initialization_complete(self) -> None:
        if not self._is_placed():
            self.gui.status_bar.show_message(
                "CalPDF is installed. Add its button from Preferences → "
                "Toolbars & menus, or set a shortcut for it.",
                12,
            )

    def _is_placed(self) -> bool:
        text = self.qaction.text()
        return any(
            text in (gprefs[key] or ())
            for key in gprefs.defaults
            if key.startswith("action-layout-")
        )

    # ------------------------------------------------------------------

    def show_dialog(self) -> None:
        book_id = self._selected_book_id()
        if book_id is None:
            return

        db = self.gui.current_db.new_api
        path = db.format_abspath(book_id, "PDF")
        if not path:
            error_dialog(
                self.gui,
                "No PDF",
                "The selected book has no PDF format.",
                show=True,
            )
            return

        authors = db.field_for("authors", book_id) or ()
        identifiers = db.field_for("identifiers", book_id) or {}
        book = Book(
            path=Path(path),
            title=db.field_for("title", book_id) or "",
            authors=" & ".join(authors),
            identifiers=dict(identifiers),
        )

        dialog = CalPDFDialog(
            book,
            on_changed=lambda: self._refresh(book_id),
            parent=self.gui,
        )
        dialog.exec()

    def _selected_book_id(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            error_dialog(
                self.gui,
                "No book selected",
                "Select a book with a PDF format first.",
                show=True,
            )
            return None
        return self.gui.library_view.model().id(rows[0])

    def _refresh(self, book_id) -> None:
        db = self.gui.current_db.new_api
        try:
            db.format_metadata(book_id, "PDF", update_db=True)
        except Exception:
            default_log.exception("Could not refresh the PDF metadata for the book")
        self.gui.library_view.model().refresh_ids([book_id])
