import threading
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from polyglotpdf.errors import (
    BatchTooLargeError,
    Cancelled,
    FatalTranslationError,
    TransientTranslationError,
)
from polyglotpdf.model import BBox, Block, BlockRole, TextStyle
from polyglotpdf.segmentation import Placeholder, Segment, SegmentStatus
from polyglotpdf.translation import (
    TranslationCache,
    TranslationContext,
    TranslationRequest,
    TranslationService,
    Translator,
)


class FakeTranslator(Translator):
    name = "fake"
    max_batch_items = 2
    max_batch_chars = 10_000

    def __init__(self, fn: Callable[[str, TranslationContext], str | None]) -> None:
        self.fn = fn
        self.calls: list[tuple[list[str], bool]] = []

    def fingerprint(self) -> str:
        return "fake/1"

    def translate_batch(
        self, requests: Sequence[TranslationRequest], context: TranslationContext
    ) -> list[str | None]:
        self.calls.append(([r.text for r in requests], context.strict))
        return [self.fn(r.text, context) for r in requests]


def segment(uid: str, source: str, keys: Sequence[int] = ()) -> Segment:
    block = Block(uid=uid, page=0, bbox=BBox(0, 0, 10, 10), lines=[], role=BlockRole.PARAGRAPH)
    placeholders = {k: Placeholder(k, "x", 0, BBox(0, 0, 1, 1), 0.0) for k in keys}
    return Segment(uid, [block], source, placeholders, TextStyle(), 10.0, 0)


CONTEXT = TranslationContext("en", "pt-BR")


def upper(text: str, _context: TranslationContext) -> str:
    return text.upper().replace("{V", "{v")


def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: self.is_set())


def test_identical_sources_are_translated_once() -> None:
    translator = FakeTranslator(upper)
    segments = [segment("a", "hello"), segment("b", "hello"), segment("c", "world")]
    stats = TranslationService(translator, CONTEXT).run(segments)
    assert [s.translation for s in segments] == ["HELLO", "HELLO", "WORLD"]
    assert stats.unique == 2 and stats.translated == 3
    assert sum(len(texts) for texts, _ in translator.calls) == 2


def test_batches_respect_the_item_limit() -> None:
    translator = FakeTranslator(upper)
    TranslationService(translator, CONTEXT, concurrency=1).run(
        [segment(str(i), f"text {i}") for i in range(5)]
    )
    assert [len(texts) for texts, _ in translator.calls] == [2, 2, 1]


def test_lost_placeholders_are_retried_in_strict_mode() -> None:
    def flaky(text: str, context: TranslationContext) -> str:
        return upper(text, context) if context.strict else "LOST"

    translator = FakeTranslator(flaky)
    item = segment("a", "value {v1} here", keys=[1])
    stats = TranslationService(translator, CONTEXT).run([item])
    assert item.status is SegmentStatus.TRANSLATED and item.translation == "VALUE {v1} HERE"
    assert stats.retried == 1 and translator.calls[-1][1] is True


def test_persistent_failure_keeps_the_original() -> None:
    item = segment("a", "value {v1} here", keys=[1])
    stats = TranslationService(FakeTranslator(lambda t, c: None), CONTEXT).run([item])
    assert item.status is SegmentStatus.FAILED and item.translation is None
    assert stats.failed == 1


def test_cache_makes_reruns_free(tmp_path: Path) -> None:
    with TranslationCache(tmp_path / "cache.sqlite3") as cache:
        TranslationService(FakeTranslator(upper), CONTEXT, cache=cache).run([segment("a", "hi")])

        def forbidden(text: str, context: TranslationContext) -> str:
            raise AssertionError("should come from the cache")

        again = segment("b", "hi")
        stats = TranslationService(FakeTranslator(forbidden), CONTEXT, cache=cache).run([again])
    assert again.translation == "HI" and stats.cache_hits == 1


def test_oversized_batches_are_split() -> None:
    class Splitting(FakeTranslator):
        def translate_batch(self, requests, context):  # type: ignore[no-untyped-def]
            if len(requests) > 1:
                raise BatchTooLargeError("too long")
            return super().translate_batch(requests, context)

    items = [segment("a", "one"), segment("b", "two")]
    TranslationService(Splitting(upper), CONTEXT).run(items)
    assert [s.translation for s in items] == ["ONE", "TWO"]


def test_transient_errors_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    no_sleep(monkeypatch)
    attempts = {"n": 0}

    def unstable(text: str, context: TranslationContext) -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TransientTranslationError("network")
        return upper(text, context)

    item = segment("a", "ok")
    TranslationService(FakeTranslator(unstable), CONTEXT).run([item])
    assert item.translation == "OK"


def test_implausible_answers_are_rejected() -> None:
    item = segment("a", "short text")
    stats = TranslationService(FakeTranslator(lambda t, c: "garbage " * 200), CONTEXT).run([item])
    assert item.status is SegmentStatus.FAILED and stats.failed == 1


def test_circuit_breaker_stops_a_failing_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    no_sleep(monkeypatch)

    def down(text: str, context: TranslationContext) -> str:
        raise TransientTranslationError("service down")

    translator = FakeTranslator(down)
    items = [segment(str(i), f"text {i}") for i in range(10)]  # 5 batches of 2
    stats = TranslationService(translator, CONTEXT, concurrency=1, circuit_limit=2).run(items)
    assert len(translator.calls) == 2 * 3  # two batches x three attempts, then it stops
    assert stats.failed == 10 and stats.retried == 0
    assert all("service down" in item.note and "stopped" in item.note for item in items)


def test_engine_concurrency_limit_is_respected() -> None:
    class Sequential(FakeTranslator):
        max_concurrency = 1

    service = TranslationService(Sequential(upper), CONTEXT, concurrency=8)
    assert service.concurrency == 1


def test_cancellation_stops_the_run() -> None:
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        TranslationService(FakeTranslator(upper), CONTEXT, cancel=cancel).run([segment("a", "x")])


def test_fatal_errors_abort_the_run() -> None:
    def fatal(text: str, context: TranslationContext) -> str:
        raise FatalTranslationError("bad credentials")

    with pytest.raises(FatalTranslationError):
        TranslationService(FakeTranslator(fatal), CONTEXT).run([segment("a", "x")])
