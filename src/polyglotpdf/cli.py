"""Command-line interface: translate, inspect, estimate, engines, models."""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from . import __version__
from .analysis.classifier import translatable_roles
from .config import EFFORT_LEVELS, Settings, with_overrides
from .errors import Cancelled, PolyglotPDFError
from .pipeline import PdfTranslator, TranslationReport
from .progress import NullProgress, ProgressReporter
from .translation.engines import EngineKind, engine_names, list_engines
from .translation.registry import list_models

err = Console(stderr=True)
out = Console()
DEFAULT_CONFIG = Path("polyglotpdf.toml")
_STAGES = {"analyze": "Analysing layout", "translate": "Translating", "render": "Rendering"}
_KINDS = {EngineKind.STANDARD: "standard", EngineKind.AI: "AI", EngineKind.OFFLINE: "test"}


class _RichProgress:
    def __init__(self, progress: Progress) -> None:
        self._progress = progress
        self._tasks: dict[str, tuple[TaskID, int]] = {}

    def start(self, stage: str, total: int) -> None:
        task = self._progress.add_task(_STAGES.get(stage, stage), total=max(total, 1))
        self._tasks[stage] = (task, max(total, 1))
        if total == 0:
            self._progress.update(task, completed=1)

    def advance(self, stage: str, amount: int = 1) -> None:
        if stage in self._tasks:
            self._progress.advance(self._tasks[stage][0], amount)

    def finish(self, stage: str) -> None:
        if stage in self._tasks:
            task, total = self._tasks[stage]
            self._progress.update(task, completed=total)


@contextmanager
def _progress(enabled: bool) -> Iterator[ProgressReporter]:
    if not enabled:
        yield NullProgress()
        return
    columns = (
        SpinnerColumn(),
        TextColumn("{task.description:<20}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )
    with Progress(*columns, console=err) as progress:
        yield _RichProgress(progress)


def _configure_logging(verbosity: int, quiet: bool) -> None:
    levels = (logging.WARNING, logging.INFO, logging.DEBUG)
    level = logging.ERROR if quiet else levels[min(verbosity, 2)]
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=err, show_path=False, show_time=False)],
        force=True,
    )
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "anthropic", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))


def _load_settings(config: Path | None) -> Settings:
    if config is not None:
        return Settings.from_toml(config)
    if DEFAULT_CONFIG.is_file():
        return Settings.from_toml(DEFAULT_CONFIG)
    return Settings()


# ---------------------------------------------------------------------- commands
def _cmd_translate(args: argparse.Namespace) -> int:
    settings = _load_settings(args.config)
    layout: dict[str, object] = {
        "min_font_scale": args.min_scale,
        "hyphenate": False if args.no_hyphenation else None,
    }
    if args.min_scale is not None:
        layout["hard_min_font_scale"] = min(settings.layout.hard_min_font_scale, args.min_scale)
    settings = with_overrides(
        settings,
        translation={
            "engine": args.engine,
            "source_lang": args.source_lang,
            "target_lang": args.target_lang,
            "model": args.model,
            "api_key": args.api_key,
            "base_url": args.base_url,
            "temperature": args.temperature,
            "effort": args.effort,
            "concurrency": args.concurrency,
            "glossary_path": args.glossary,
            "use_cache": False if args.no_cache else None,
        },
        content={"translate_code": args.translate_code},
        layout=layout,
        output={"bilingual": args.bilingual},
        root={"pages": args.pages},
    )
    with _progress(not args.quiet) as progress:
        report = PdfTranslator(settings, progress=progress).translate(args.input, args.output)
    _print_report(report)
    if args.report:
        args.report.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    settings = with_overrides(_load_settings(args.config), root={"pages": args.pages})
    with _progress(not args.quiet) as progress:
        layout, path = PdfTranslator(settings, progress=progress).inspect(args.input, args.output)
    translatable = translatable_roles(settings.content)
    counts = Counter(block.role for block in layout.blocks())
    table = Table(title="Detected blocks")
    table.add_column("Role")
    table.add_column("Count", justify="right")
    table.add_column("Treatment")
    for role, count in counts.most_common():
        table.add_row(role.value, str(count), "translated" if role in translatable else "kept")
    out.print(table)
    stats = layout.stats
    out.print(
        f"Body font: [bold]{stats.body_font or '?'}[/] {stats.body_size:g} pt"
        f"{' (TeX)' if stats.tex_body else ''}"
    )
    if layout.title:
        out.print(f"Title: [bold]{layout.title}[/]")
    if args.verbose:
        for block in layout.blocks():
            preview = " ".join(block.text.split())[:70]
            out.print(
                f"[dim]{block.uid:>10}[/] {block.role.value:<13} {block.reason:<34} {preview}"
            )
    out.print(f"Annotated PDF: [bold]{path}[/]")
    return 0


def _cmd_estimate(args: argparse.Namespace) -> int:
    settings = with_overrides(_load_settings(args.config), root={"pages": args.pages})
    with _progress(not args.quiet) as progress:
        estimate = PdfTranslator(settings, progress=progress).estimate(args.input)
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold")
    table.add_column(justify="right")
    table.add_row("Pages", str(estimate.pages))
    table.add_row("Segments to translate", str(estimate.segments))
    table.add_row("Paragraphs joined across columns/pages", str(estimate.merged_paragraphs))
    table.add_row("Words", f"{estimate.words:,}")
    table.add_row("Characters", f"{estimate.characters:,}")
    table.add_row("Inline formulas preserved", str(estimate.formulas))
    out.print(table)
    return 0


def _cmd_engines(args: argparse.Namespace) -> int:
    table = Table(title="Translation engines")
    for column in ("Engine", "Name", "Kind", "API key", "Default model"):
        table.add_column(column)
    for engine in list_engines():
        if not engine.requires_key:
            key = "not needed"
        elif engine.has_key:
            key = "[green]set[/]"
        else:
            key = f"[yellow]set {engine.key_env[0]}[/]"
        table.add_row(
            engine.name, engine.label, _KINDS[engine.kind], key, engine.default_model or "-"
        )
    out.print(table)
    return 0


def _cmd_models(args: argparse.Namespace) -> int:
    for model in list_models(args.engine, args.api_key, args.base_url):
        out.print(model)
    return 0


def _print_report(report: TranslationReport) -> None:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Translated file", report.output_path or "-")
    if report.bilingual_path:
        table.add_row("Bilingual version", report.bilingual_path)
    table.add_row("Engine", report.engine)
    table.add_row("Target language", report.target_lang)
    table.add_row("Pages", str(report.pages))
    table.add_row("Segments translated", f"{report.translated} of {report.segments}")
    if report.merged_paragraphs:
        table.add_row("Paragraphs joined across columns", str(report.merged_paragraphs))
    table.add_row("Reused from cache", str(report.cache_hits))
    table.add_row("Requests to the translator", str(report.requests))
    if report.shrunk:
        table.add_row(
            "Blocks with a smaller font", f"{report.shrunk} (smallest scale {report.min_scale:.0%})"
        )
    if report.overflowed:
        table.add_row("[yellow]Blocks that overflowed their area", str(report.overflowed))
    if report.failed:
        table.add_row("[yellow]Kept in the original", str(report.failed))
        reasons = Counter(item.split(": ", 1)[-1] for item in report.failures)
        table.add_row("[yellow]Main reason", reasons.most_common(1)[0][0])
    for warning in report.warnings:
        table.add_row("[yellow]Warning", warning)
    table.add_row("Time", f"{report.elapsed_seconds:.1f} s")
    out.print(table)


# ---------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    logs = argparse.ArgumentParser(add_help=False)
    logs.add_argument("-v", "--verbose", action="count", default=0, help="more detail (-vv: debug)")
    logs.add_argument("-q", "--quiet", action="store_true", help="no progress bar")
    common = argparse.ArgumentParser(add_help=False, parents=[logs])
    common.add_argument("-c", "--config", type=Path, help="TOML configuration file")
    common.add_argument(
        "-p", "--pages", help="pages, e.g. 1-3,7 (the output holds only those pages)"
    )

    parser = argparse.ArgumentParser(
        prog="polyglotpdf",
        description="Translate PDFs (papers and e-books) keeping the layout and the formulas.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    translate = commands.add_parser("translate", parents=[common], help="translate a document")
    translate.add_argument("input", type=Path, help="PDF (or EPUB/XPS/FB2/MOBI/CBZ)")
    translate.add_argument(
        "-o", "--output", type=Path, help="output PDF (default: <name>.<language>.pdf)"
    )
    translate.add_argument(
        "-t", "--target", dest="target_lang", help="target language (default: pt-BR)"
    )
    translate.add_argument(
        "-s", "--source", dest="source_lang", help="source language (default: auto)"
    )
    translate.add_argument(
        "-e",
        "--engine",
        choices=engine_names(),
        metavar="ENGINE",
        help="google (default), deepl, anthropic, openai, deepseek, gemini, mistral, xai, qwen, "
        "openrouter, ollama, openai-compatible, pseudo, echo",
    )
    translate.add_argument(
        "-m", "--model", help="model for the AI engine (default: the engine's own)"
    )
    translate.add_argument(
        "-k", "--api-key", help="API key (or the provider's environment variable)"
    )
    translate.add_argument("--base-url", help="provider endpoint (for your own servers)")
    translate.add_argument("--temperature", type=float, help="model temperature (0-2)")
    translate.add_argument(
        "--effort", choices=EFFORT_LEVELS, help="Claude reasoning effort (default: medium)"
    )
    translate.add_argument("-g", "--glossary", type=Path, help="TOML/JSON glossary (AI engines)")
    translate.add_argument("--concurrency", type=int, help="simultaneous requests (default: 4)")
    translate.add_argument(
        "--bilingual",
        action="store_true",
        default=None,
        help="also write a side-by-side PDF (original | translation)",
    )
    translate.add_argument(
        "--translate-code",
        action="store_true",
        default=None,
        help="also translate code listings",
    )
    translate.add_argument("--min-scale", type=float, help="preferred minimum font scale (0.2-1)")
    translate.add_argument("--no-hyphenation", action="store_true", help="turn hyphenation off")
    translate.add_argument("--no-cache", action="store_true", help="ignore the translation cache")
    translate.add_argument("--report", type=Path, help="write a JSON report")
    translate.set_defaults(handler=_cmd_translate)

    inspect = commands.add_parser(
        "inspect", parents=[common], help="write an annotated PDF showing what would be translated"
    )
    inspect.add_argument("input", type=Path)
    inspect.add_argument(
        "-o", "--output", type=Path, help="annotated PDF (default: <name>.inspect.pdf)"
    )
    inspect.set_defaults(handler=_cmd_inspect)

    estimate = commands.add_parser(
        "estimate",
        parents=[common],
        help="count segments, words and characters without translating",
    )
    estimate.add_argument("input", type=Path)
    estimate.set_defaults(handler=_cmd_estimate)

    engines = commands.add_parser("engines", parents=[logs], help="list the translation engines")
    engines.set_defaults(handler=_cmd_engines)

    models = commands.add_parser(
        "models", parents=[logs], help="list the models an AI provider offers today"
    )
    models.add_argument("-e", "--engine", required=True, choices=engine_names(), metavar="ENGINE")
    models.add_argument("-k", "--api-key", help="API key (or the environment variable)")
    models.add_argument("--base-url", help="provider endpoint")
    models.set_defaults(handler=_cmd_models)

    app = commands.add_parser(
        "app",
        parents=[logs],
        help="open the app: library, reading, translation, companion and tutor",
    )
    app.add_argument("--data-dir", type=Path, help="library folder (default: the user data folder)")
    app.add_argument(
        "--headless",
        action="store_true",
        help="development: the internal server only, no window (prints the address)",
    )
    app.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    app.add_argument(
        "--port",
        type=int,
        default=0,
        help="port for the internal server (default: a free one)",
    )
    app.set_defaults(handler=_cmd_app)
    return parser


_APP_MODULES = {
    "fastapi",
    "starlette",
    "uvicorn",
    "multipart",
    "python_multipart",
    "keyring",
    "webview",
}


def _cmd_app(args: argparse.Namespace) -> int:
    import os

    from .app.config import AppConfig, default_data_dir, new_token
    from .errors import ConfigError

    token = os.environ.get("POLYGLOTPDF_APP_TOKEN") or new_token()
    config = AppConfig(data_dir=args.data_dir or default_data_dir(), token=token)
    try:
        from .app.launcher import run

        return run(config, host=args.host, port=args.port, headless=args.headless)
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] in _APP_MODULES:
            raise ConfigError(
                "The app needs the 'app' extra: "
                "uv sync --extra app (or pip install 'polyglotpdf[app]')"
            ) from exc
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose, args.quiet)
    try:
        return int(args.handler(args))
    except Cancelled:
        err.print("[yellow]Cancelled.[/] Whatever was translated stays in the cache.")
        return 130
    except PolyglotPDFError as exc:
        err.print(f"[bold red]Error:[/] {exc}")
        return 1
    except KeyboardInterrupt:
        err.print("[yellow]Interrupted.[/] Whatever was translated stays in the cache.")
        return 130
    except Exception as exc:  # unexpected: short message; the traceback is logged with -vv
        logging.getLogger(__name__).debug("Unexpected error", exc_info=True)
        err.print(f"[bold red]Unexpected error:[/] {exc!r} (use -vv for the traceback)")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
