"""API routes of the reader application."""

from . import companion, dictionary, engines, jobs, library, reader, sessions, study

ROUTERS = (
    library.router,
    reader.router,
    engines.router,
    jobs.router,
    companion.router,
    study.router,
    sessions.router,
    dictionary.router,
)

__all__ = ["ROUTERS"]
