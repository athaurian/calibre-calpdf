# calibre-calpdf

A Calibre interface plugin for [calpdf](https://github.com/athaurian/calpdf).
It works on the PDF of the selected book without leaving the library.

- **Info**: pages, page size, file size, PDF version, and bookmark counts.
- **Cover**: download one by ASIN or ISBN, or pick an image, then replace the
  first page or prepend a new one.
- **Contents**: edit the PDF outline as a tree, and import or export it as JSON.
- **Optimize**: run qpdf with optional color-profile stripping.
- **Backup**: inspect and restore the `.bak` copy that calpdf keeps.

Every change goes through calpdf, so the in-place safety behavior is the same
as the command line. The first write saves `<book>.pdf.bak` next to the PDF.

## Requirements

- Calibre 6 or newer.
- [calpdf](https://github.com/athaurian/calpdf) importable by Calibre's Python.
- `qpdf` on `PATH` for the Optimize tab.

## Install

```bash
make build
calibre-customize -a dist/calpdf.zip
```

Then restart Calibre and add the **CalPDF** button from
*Preferences → Interface → Toolbars & menus*. A shortcut can be assigned under
*Preferences → Shortcuts*.

To remove it:

```bash
make uninstall
```

## Development

```bash
make venv     # uses the system calpdf and pikepdf
make test
make lint
make ui       # renders build/ui/*.png offscreen
```

`build.py` zips `calpdf_plugin/` with `plugin-import-name-calpdf.txt` at the
root, which is what makes Calibre load it as `calibre_plugins.calpdf`.

## License

MIT
