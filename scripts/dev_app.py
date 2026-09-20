"""Start the application's server without the window, for developing the interface.

    python scripts/dev_app.py [--port 8765] [--data-dir .devdata]

The desktop app picks a random port and token; here both are fixed (token ``dev``, or
``POLYGLOTPDF_APP_TOKEN`` when set), so a browser can open http://127.0.0.1:8765/?token=dev
and the Vite dev server's proxy (see frontend/vite.config.ts) can send the same token.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("POLYGLOTPDF_APP_TOKEN", "dev")

from polyglotpdf.cli import main  # imported after the environment is set

if __name__ == "__main__":
    arguments = sys.argv[1:] or ["--port", "8765", "--data-dir", ".devdata"]
    raise SystemExit(main(["app", "--headless", *arguments]))
