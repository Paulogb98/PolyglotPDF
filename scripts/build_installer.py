"""Build the Windows installer (Inno Setup) around the frozen desktop app.

    uv run --extra app python scripts/build_installer.py [--skip-build] [--skip-frontend]

Runs ``scripts/build_desktop.py`` to produce ``dist/PolyglotPDF/`` and then compiles
``installer/polyglotpdf.iss`` with ISCC, leaving a single file to hand out:
``dist/PolyglotPDF-<version>-Setup.exe``. It installs per user (no administrator
needed), offers a Start-menu and an optional desktop shortcut and registers an
uninstaller; a new version installs over the previous one.

Inno Setup is the only extra requirement:

    winget install --id JRSoftware.InnoSetup

``--skip-build`` reuses the ``dist/PolyglotPDF/`` already there; ``--skip-frontend``
is passed through to the desktop build (the interface must already be compiled).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP_DIR = DIST / "PolyglotPDF"
SCRIPT = ROOT / "installer" / "polyglotpdf.iss"

#: Where Inno Setup lands with winget or with its own installer.
ISCC_GUESSES = (
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Inno Setup 6"
    / "ISCC.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
)


def app_version() -> str:
    try:
        return version("polyglotpdf")
    except PackageNotFoundError:  # not installed: read it from pyproject.toml
        import tomllib

        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data["project"]["version"])


def find_iscc() -> Path:
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return Path(found)
    for guess in ISCC_GUESSES:
        if guess.is_file():
            return guess
    raise SystemExit(
        "ISCC (Inno Setup) not found. Install it with "
        "'winget install --id JRSoftware.InnoSetup' or from https://jrsoftware.org/isdl.php, "
        "then run this script again."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip-build", action="store_true", help="use the dist/PolyglotPDF already built"
    )
    parser.add_argument("--skip-frontend", action="store_true", help="do not rebuild the interface")
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit(
            "The installer is Windows-only for now; on macOS and Linux ship the folder "
            "from scripts/build_desktop.py."
        )

    iscc = find_iscc()  # fail before the long build if it is missing
    if not args.skip_build:
        build = [sys.executable, str(ROOT / "scripts" / "build_desktop.py")]
        if args.skip_frontend:
            build.append("--skip-frontend")
        subprocess.run(build, check=True, cwd=ROOT)
    if not (APP_DIR / "PolyglotPDF.exe").is_file():
        raise SystemExit(f"{APP_DIR} is not built: run without --skip-build.")

    release = app_version()
    subprocess.run(
        [
            str(iscc),
            f"/DAppVersion={release}",
            f"/DSourceDir={APP_DIR}",
            f"/DOutputDir={DIST}",
            str(SCRIPT),
        ],
        check=True,
        cwd=SCRIPT.parent,
    )
    print(f"\nDone: {DIST / f'PolyglotPDF-{release}-Setup.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
