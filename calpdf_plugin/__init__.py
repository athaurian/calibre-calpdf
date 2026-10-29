"""CalPDF, a Calibre interface plugin for the calpdf toolkit."""

try:
    from calibre.customize import InterfaceActionBase
except ImportError:  # outside Calibre, for the tests and the layout renderer
    InterfaceActionBase = object


class CalPDFPlugin(InterfaceActionBase):
    name = "CalPDF"
    description = (
        "Modify PDFs in Calibre: replace covers, edit bookmarks, shrink files "
        "when possible, and restore backups. This plugin is an interface for "
        "my calpdf tool."
    )
    supported_platforms = ["windows", "osx", "linux"]
    author = "Athaurian"
    version = (0, 1, 0)
    minimum_calibre_version = (6, 0, 0)
    actual_plugin = "calibre_plugins.calpdf.action:CalPDFAction"

    def is_customizable(self):
        return False
