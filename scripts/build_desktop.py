"""Build the desktop app as a folder with its own executable (PyInstaller, one-dir).

    uv run --extra app python scripts/build_desktop.py [--skip-frontend]

Compiles the interface (npm --prefix frontend run build) unless told not to, then
freezes ``polyglotpdf.app.desktop:main`` with the interface and the icon inside it.
The result is ``dist/PolyglotPDF/PolyglotPDF.exe`` on Windows (``PolyglotPDF.app`` on
macOS); the whole folder is what gets shipped. One-dir starts faster than one-file,
which would unpack itself to a temporary folder on every launch.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "polyglotpdf" / "app"
BUILD = ROOT / "build" / "desktop"
DIST = ROOT / "dist"
NAME = "PolyglotPDF"

ENTRY = """\
from polyglotpdf.app.desktop import main

raise SystemExit(main())
"""


def build_frontend() -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm not found: install Node.js or use --skip-frontend.")
    subprocess.run([npm, "--prefix", str(ROOT / "frontend"), "run", "build"], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip-frontend", action="store_true", help="use the interface already compiled"
    )
    args = parser.parse_args()

    if not args.skip_frontend:
        build_frontend()
    static = APP / "static"
    if not (static / "index.html").is_file():
        raise SystemExit("The interface is not built: run without --skip-frontend.")

    from PyInstaller.__main__ import run as pyinstaller  # type: ignore[import-untyped]

    BUILD.mkdir(parents=True, exist_ok=True)
    entry = BUILD / "polyglotpdf_desktop.py"
    entry.write_text(ENTRY, encoding="utf-8")
    icon = APP / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.png")
    sep = ";" if sys.platform == "win32" else ":"

    pyinstaller(
        [
            str(entry),
            "--name",
            NAME,
            "--windowed",
            "--noconfirm",
            "--clean",
            "--icon",
            str(icon),
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / "work"),
            "--specpath",
            str(BUILD),
            "--add-data",
            f"{static}{sep}polyglotpdf/app/static",
            "--add-data",
            f"{APP / 'assets'}{sep}polyglotpdf/app/assets",
            # Engines, routes and uvicorn's protocol and loop choices are imported by name.
            "--collect-submodules",
            "polyglotpdf",
            "--collect-submodules",
            "uvicorn",
            "--copy-metadata",
            "polyglotpdf",
        ]
    )
    print(f"\nDone: {DIST / NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
