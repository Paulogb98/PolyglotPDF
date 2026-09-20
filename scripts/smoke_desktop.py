"""Open the real desktop window, check the page and the native bridge, then close it.

    uv run python scripts/smoke_desktop.py [--keep-open]

Uses a throwaway library, so it never touches yours. Exits 0 when the window loaded the
interface, the fonts, the page's JavaScript API and the bridge to Python; prints what it
saw either way. ``--keep-open`` leaves the window up (to look at it) and only reports.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from polyglotpdf.app.config import AppConfig, new_token
from polyglotpdf.app.launcher import run

CHECK = """
(async () => {
  for (let i = 0; i < 100 && !(window.pywebview && window.pywebview.api
       && window.pywebview.api.platform); i += 1) {
    await new Promise((r) => setTimeout(r, 100));
  }
  await document.fonts.ready;
  const platform = window.pywebview ? await window.pywebview.api.platform() : null;
  return JSON.stringify({
    title: document.title,
    screen: document.querySelector('.screen') ? document.querySelector('.screen').className : null,
    heading: (document.querySelector('h1') || {}).textContent || null,
    caprasimo: document.fonts.check('16px Caprasimo'),
    bridge: platform,
  });
})()
"""


def main() -> int:
    keep_open = "--keep-open" in sys.argv
    report: dict[str, Any] = {}

    def inspect(window: Any) -> None:
        window.events.loaded.wait(30)
        time.sleep(1.5)  # the interface asks the API for the library first
        done = threading.Event()

        def resolved(value: Any) -> None:
            report.update(json.loads(value) if isinstance(value, str) else value or {})
            done.set()

        try:
            # A promise only reaches Python through the callback.
            window.evaluate_js(CHECK, callback=resolved)
            if not done.wait(20):
                report["error"] = "the page did not answer"
        except Exception as exc:  # reported, not raised: the window must still close
            report["error"] = repr(exc)
        if not keep_open:
            window.destroy()

    # WebView2 keeps a lock on its profile for a moment after the window closes.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        config = AppConfig(data_dir=Path(folder), token=new_token())
        code = run(config, on_ready=inspect)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = (
        code == 0
        and report.get("caprasimo") is True
        and (report.get("bridge") or {}).get("desktop") is True
        and bool(report.get("screen"))
    )
    print("OK" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
