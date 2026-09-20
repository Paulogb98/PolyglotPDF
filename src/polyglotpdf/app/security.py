"""Access control of the local server.

* **Host check** — only the configured host names are served, which defeats DNS
  rebinding (a web page resolving its own domain to 127.0.0.1).
* **Access token** — like Jupyter, the launcher opens ``/?token=...``; the server
  answers with an ``HttpOnly``, ``SameSite=Strict`` cookie, so other sites cannot
  call the API from the user's browser (no CSRF) and cannot read the token.
* **Security headers** — a strict Content-Security-Policy (scripts only from the
  application itself), no framing, no referrer, no MIME sniffing.
"""

from __future__ import annotations

import hmac

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

COOKIE = "polyglotpdf_token"
HEADER = "x-polyglotpdf-token"
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
_HEADERS = [
    (b"content-security-policy", _CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
]
_LOCKED = """<!doctype html><html><meta charset="utf-8">
<title>PolyglotPDF</title><body style="font-family:system-ui;max-width:36rem;margin:15vh auto">
<h1>PolyglotPDF</h1><p>Open the full address shown when the app starts (it contains
<code>?token=...</code>). The token protects your library and your API keys.</p>
<p><em>Abra o endereço completo exibido ao iniciar o aplicativo (ele contém
<code>?token=...</code>). O token protege a sua biblioteca e as suas chaves de API.</em></p>
</body></html>"""


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, *, token: str, allowed_hosts: frozenset[str]) -> None:
        self.app = app
        self.token = token
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if _hostname(headers.get("host", "")) not in self.allowed_hosts:
            await PlainTextResponse("Host not allowed", status_code=400)(scope, receive, send)
            return
        request = Request(scope)
        path = scope["path"]
        if path == "/" and "token" in request.query_params:
            if not self._valid(request.query_params["token"]):
                await HTMLResponse(_LOCKED, status_code=403)(scope, receive, send)
                return
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(COOKIE, self.token, httponly=True, samesite="strict", path="/")
            await response(scope, receive, send)
            return
        authorised = self._valid(request.cookies.get(COOKIE)) or self._valid(headers.get(HEADER))
        if not authorised and path.startswith("/api/"):
            detail = "Unauthorised: open the address with the token shown by the launcher"
            await JSONResponse({"detail": detail}, status_code=401)(scope, receive, send)
            return
        if not authorised and path == "/":
            await HTMLResponse(_LOCKED, status_code=401)(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], *_HEADERS]
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _valid(self, candidate: str | None) -> bool:
        return bool(candidate) and hmac.compare_digest(str(candidate), self.token)


def _hostname(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):  # [::1]:8765
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host
