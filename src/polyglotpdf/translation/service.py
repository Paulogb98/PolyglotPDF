"""Batching, caching, concurrency and validation around a :class:`Translator`.

Workflow:

1. identical source texts are translated once (running heads, repeated labels);
2. cached translations are reused;
3. the rest is packed into batches in reading order (neighbouring segments give
   the model context) and sent concurrently;
4. every answer is validated: placeholders must survive and the length must be
   plausible. Invalid or missing items are retried one by one in "strict" mode;
   if they still fail, the segment keeps its original text in the output.

When the engine keeps failing (service down, quota exhausted), a circuit breaker
stops sending requests instead of retrying every remaining batch. A cancel event
stops the work between requests.
"""

from __future__ import annotations

import logging
import random
import threading
from collections.abc import Sequence
from concurrent.futures import FIRST_EXCEPTION, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from ..errors import BatchTooLargeError, Cancelled, RefusalError, TransientTranslationError
from ..progress import NullProgress, ProgressReporter
from ..segmentation.markup import repair
from ..segmentation.segmenter import Segment, SegmentStatus
from .base import TranslationContext, TranslationRequest, Translator
from .cache import TranslationCache, cache_key

log = logging.getLogger(__name__)

_INVALID = "placeholders lost or invalid translation"


@dataclass(slots=True)
class TranslationStats:
    segments: int = 0
    unique: int = 0
    cache_hits: int = 0
    translated: int = 0
    failed: int = 0
    retried: int = 0
    requests: int = 0


@dataclass(slots=True)
class _Job:
    key: str
    text: str
    role: str
    expected: set[int]
    segments: list[Segment] = field(default_factory=list)


def plausible(source: str, translation: str) -> bool:
    """Reject answers that cannot be a translation of the source (error pages, loops...)."""
    return len(translation) <= 4 * len(source) + 80


class TranslationService:
    def __init__(
        self,
        translator: Translator,
        context: TranslationContext,
        *,
        cache: TranslationCache | None = None,
        concurrency: int = 4,
        max_attempts: int = 3,
        circuit_limit: int = 3,
        progress: ProgressReporter | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        self.translator = translator
        self.context = context
        self.cache = cache
        limit = translator.max_concurrency or concurrency
        self.concurrency = max(1, min(concurrency, limit))
        self.max_attempts = max(1, max_attempts)
        self.circuit_limit = max(1, circuit_limit)
        self.progress = progress or NullProgress()
        self.cancel = cancel or threading.Event()
        self.stats = TranslationStats()
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._open_reason: str | None = None  # set when the circuit breaker trips
        self._reasons: dict[str, str] = {}  # job key -> why it could not be translated

    def run(self, segments: Sequence[Segment]) -> TranslationStats:
        jobs = self._group(segments)
        self.stats.segments = len(segments)
        self.stats.unique = len(jobs)
        self.progress.start("translate", len(jobs))

        pending: list[_Job] = []
        for job in jobs:
            cached = self.cache.get(job.key) if self.cache else None
            fixed = repair(cached, job.expected) if cached is not None else None
            if fixed is not None:
                self._assign(job, fixed)
                self.stats.cache_hits += len(job.segments)
                self.progress.advance("translate")
            else:
                pending.append(job)

        failed = self._run(self._batches(pending), self.context)
        if failed and self._open_reason is None:
            self.stats.retried = len(failed)
            log.info("Retrying %d segment(s) individually", len(failed))
            failed = self._run([[job] for job in failed], self.context.as_strict())
        for job in failed:
            reason = self._open_reason or self._reasons.get(job.key, _INVALID)
            for segment in job.segments:
                segment.status = SegmentStatus.FAILED
                segment.note = f"{reason}; original kept"
            self.stats.failed += len(job.segments)
            self.progress.advance("translate")
        self.progress.finish("translate")
        return self.stats

    def _group(self, segments: Sequence[Segment]) -> list[_Job]:
        fingerprint = self.translator.fingerprint()
        glossary = self.context.glossary.fingerprint()
        jobs: dict[str, _Job] = {}
        for segment in segments:
            role = segment.role.value
            key = cache_key(
                fingerprint,
                self.context.source_lang,
                self.context.target_lang,
                glossary,
                role,
                segment.source,
            )
            job = jobs.get(key)
            if job is None:
                job = jobs[key] = _Job(key, segment.source, role, set(segment.placeholders))
            job.segments.append(segment)
        return list(jobs.values())

    def _batches(self, jobs: Sequence[_Job]) -> list[list[_Job]]:
        limit_items = self.translator.max_batch_items
        limit_chars = self.translator.max_batch_chars
        batches: list[list[_Job]] = []
        current: list[_Job] = []
        size = 0
        for job in jobs:
            if current and (len(current) >= limit_items or size + len(job.text) > limit_chars):
                batches.append(current)
                current, size = [], 0
            current.append(job)
            size += len(job.text)
        if current:
            batches.append(current)
        return batches

    def _run(self, batches: list[list[_Job]], context: TranslationContext) -> list[_Job]:
        """Translate batches concurrently; return the jobs that still need work."""
        failed: list[_Job] = []
        if not batches:
            return failed
        workers = min(self.concurrency, len(batches))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="translate") as pool:
            futures: dict[Future[list[str | None]], list[_Job]] = {
                pool.submit(self._translate, batch, context): batch for batch in batches
            }
            remaining = set(futures)
            while remaining:
                done, remaining = wait(remaining, return_when=FIRST_EXCEPTION)
                for future in done:
                    error = future.exception()
                    if error is not None:  # fatal error or cancellation: abort the run
                        for other in remaining:
                            other.cancel()
                        raise error
                    for job, text in zip(futures[future], future.result(), strict=True):
                        fixed = repair(text, job.expected) if text is not None else None
                        if fixed is None or not plausible(job.text, fixed):
                            failed.append(job)
                            continue
                        self._assign(job, fixed)
                        self.stats.translated += len(job.segments)
                        if self.cache is not None:
                            self.cache.put(job.key, self.translator.name, job.text, fixed)
                        self.progress.advance("translate")
        return failed

    def _translate(self, batch: list[_Job], context: TranslationContext) -> list[str | None]:
        requests = [TranslationRequest(str(i), job.text, job.role) for i, job in enumerate(batch)]
        for attempt in range(1, self.max_attempts + 1):
            if self.cancel.is_set():
                raise Cancelled("Translation cancelled")
            if self._open_reason is not None:
                return [None] * len(batch)
            with self._lock:
                self.stats.requests += 1
            try:
                results = self.translator.translate_batch(requests, context)
                if len(results) != len(batch):
                    raise TransientTranslationError("engine returned a wrong number of results")
            except (BatchTooLargeError, RefusalError) as exc:
                if len(batch) == 1:
                    log.warning("Segment not translated (%s)", exc)
                    self._reasons[batch[0].key] = str(exc)
                    return [None]
                middle = len(batch) // 2
                return self._translate(batch[:middle], context) + self._translate(
                    batch[middle:], context
                )
            except TransientTranslationError as exc:
                if attempt == self.max_attempts:
                    self._record_failure(batch, str(exc))
                    return [None] * len(batch)
                delay = min(30.0, 2.0**attempt + random.random())
                log.info("Transient error (%s); retrying in %.1fs", exc, delay)
                if self.cancel.wait(delay):  # sleeps, but wakes up at once on cancel
                    raise Cancelled("Translation cancelled") from exc
            else:
                with self._lock:
                    self._consecutive_failures = 0
                return results
        return [None] * len(batch)

    def _record_failure(self, batch: list[_Job], reason: str) -> None:
        log.warning("Batch of %d segment(s) failed: %s", len(batch), reason)
        with self._lock:
            for job in batch:
                self._reasons[job.key] = reason
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.circuit_limit and self._open_reason is None:
                self._open_reason = f"{reason} (stopped after repeated failures)"
                log.error("Translation engine keeps failing; remaining segments stay untranslated")

    @staticmethod
    def _assign(job: _Job, text: str) -> None:
        for segment in job.segments:
            segment.translation = text
            segment.status = SegmentStatus.TRANSLATED
