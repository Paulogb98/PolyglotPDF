"""The FastAPI application: API routes, the built interface and error handling."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..errors import (
    CompanionError,
    ConfigError,
    InputError,
    PolyglotPDFError,
    ReplyFormatError,
    TranslationError,
)
from .config import AppConfig
from .i18n import msg, request_language
from .library import NotFound
from .routes import ROUTERS
from .secrets import SecretStore
from .security import SecurityMiddleware
from .state import AppState

_NOT_BUILT = """<!doctype html><html><meta charset="utf-8"><title>PolyglotPDF</title>
<body style="font-family:system-ui;max-width:40rem;margin:12vh auto;line-height:1.5">
<h1>PolyglotPDF</h1><p>The interface has not been built yet. In the project folder, run:<br>
<em>A interface ainda não foi compilada. Na pasta do projeto, rode:</em></p>
<pre>npm --prefix frontend install
npm --prefix frontend run build</pre><p>and open the app again. The API is already available at
<code>/api</code>.<br><em>e reabra o aplicativo. A API já está disponível em
<code>/api</code>.</em></p></body></html>"""


def create_app(config: AppConfig | None = None, *, secrets: SecretStore | None = None) -> FastAPI:
    config = config or AppConfig()
    state = AppState(config, secrets=secrets)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        state.close()

    app = FastAPI(
        title="PolyglotPDF Reader",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.polyglotpdf = state
    app.add_middleware(SecurityMiddleware, token=config.token, allowed_hosts=config.allowed_hosts)
    for router in ROUTERS:
        # Every route learns the interface's language before it runs.
        app.include_router(router, dependencies=[Depends(request_language)])
    _error_handlers(app)
    _interface(app, config)
    return app


def _error_handlers(app: FastAPI) -> None:
    def handler(status: int) -> object:
        async def respond(_: Request, exc: Exception) -> JSONResponse:
            detail = msg(f"reply.{exc.source}") if isinstance(exc, ReplyFormatError) else str(exc)
            body: dict[str, object] = {"detail": detail or type(exc).__name__}
            if isinstance(exc, CompanionError):
                body["retryable"] = exc.retryable
            return JSONResponse(body, status_code=status)

        return respond

    for exc_type, status in (
        (NotFound, 404),
        (FileNotFoundError, 404),
        (IndexError, 404),
        (ConfigError, 400),
        (InputError, 400),
        (CompanionError, 502),
        (TranslationError, 502),
        (PolyglotPDFError, 500),
    ):
        app.add_exception_handler(exc_type, handler(status))  # type: ignore[arg-type]


def _interface(app: FastAPI, config: AppConfig) -> None:
    index = config.static_dir / "index.html"
    for name in ("assets", "fonts"):  # built bundles and the interface's own typefaces
        folder = config.static_dir / name
        if folder.is_dir():
            app.mount(f"/{name}", StaticFiles(directory=folder), name=name)

    @app.get("/", include_in_schema=False)
    def home() -> object:
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(_NOT_BUILT)

    @app.get("/favicon.png", include_in_schema=False)
    def favicon() -> object:
        icon = config.static_dir / "favicon.png"
        if icon.is_file():
            return FileResponse(icon, media_type="image/png")
        return JSONResponse({"detail": "Not found"}, status_code=404)
