#!/usr/bin/env python3
"""Build the installable plugin zip.

Calibre derives the plugin module name from a root-level
plugin-import-name-*.txt file, so the zip is content-addressed by
plugin-import-name-calpdf.txt rather than by the file name.
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "calpdf_plugin"
DEFAULT_OUTPUT = ROOT / "dist" / "calpdf.zip"


def build(output: Path) -> Path:
    if not (SOURCE / "__init__.py").is_file():
        raise SystemExit(f"Missing {SOURCE / '__init__.py'}")
    if not (SOURCE / "plugin-import-name-calpdf.txt").is_file():
        raise SystemExit("Missing the plugin-import-name file")

    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(
        path
        for path in SOURCE.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(SOURCE).as_posix())
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    target = build(args.output)
    print(f"{target.relative_to(ROOT)}  {target.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
