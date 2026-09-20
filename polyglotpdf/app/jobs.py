"""Background jobs (translations and estimates) with progress and cancellation."""

from __future__ import annotations

import logging
import multiprocessing
import queue
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .db import now
from .worker import run_job

log = logging.getLogger(__name__)

#: Share of the overall progress taken by each stage of a translation.
_WEIGHTS = {"analyze": 0.15, "translate": 0.7, "render": 0.15}
_CANCEL_GRACE = 15.0  # seconds a cancelled process gets before it is terminated
_KEEP_FINISHED = 50


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class Job:
    id: str
    kind: str  # "translate" or "estimate"
    document_id: str
    params: dict[str, Any]  # public parameters (engine, languages, pages...)
    status: JobStatus = JobStatus.QUEUED
    stages: dict[str, tuple[int, int]] = field(default_factory=dict)
    stage: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    version_id: str | None = None
    created_at: str = field(default_factory=now)
    finished_at: str | None = None

    @property
    def finished(self) -> bool:
        return self.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)

    @property
    def progress(self) -> float:
        if self.status is JobStatus.DONE:
            return 1.0
        if self.kind == "estimate":
            done, total = self.stages.get("analyze", (0, 0))
            return done / total if total else 0.0
        value = 0.0
        for stage, weight in _WEIGHTS.items():
            done, total = self.stages.get(stage, (0, 0))
            value += weight * (done / total if total else 0.0)
        return round(value, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "document_id": self.document_id,
            "params": self.params,
            "status": self.status.value,
            "stage": self.stage,
            "stages": {k: {"done": d, "total": t} for k, (d, t) in self.stages.items()},
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "version_id": self.version_id,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


OnDone = Callable[[Job], None]


class JobManager:
    """Runs translations one at a time and estimates alongside, each in a child process."""

    def __init__(self, *, isolation: str = "process") -> None:
        self.isolation = isolation
        self._jobs: dict[str, Job] = {}
        self._cancels: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._context = multiprocessing.get_context("spawn")
        self._pools = {
            "translate": ThreadPoolExecutor(1, thread_name_prefix="polyglotpdf-translate"),
            "estimate": ThreadPoolExecutor(1, thread_name_prefix="polyglotpdf-estimate"),
        }

    # ------------------------------------------------------------------ public API
    def submit(
        self,
        kind: str,
        document_id: str,
        params: dict[str, Any],
        payload: dict[str, Any],
        on_done: OnDone | None = None,
    ) -> Job:
        if kind not in self._pools:
            raise ValueError(f"Unknown job kind {kind!r}")
        job = Job(id=uuid.uuid4().hex, kind=kind, document_id=document_id, params=params)
        cancel = self._context.Event() if self.isolation == "process" else threading.Event()
        with self._lock:
            self._jobs[job.id] = job
            self._cancels[job.id] = cancel
            self._prune()
        self._pools[kind].submit(self._run, job, payload, cancel, on_done)
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            return self._jobs[job_id]

    def list(self, document_id: str | None = None) -> list[Job]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if document_id in (None, j.document_id)]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            cancel = self._cancels.get(job_id)
            if job.status is JobStatus.QUEUED:
                self._finish(job, JobStatus.CANCELLED)
        if cancel is not None:
            cancel.set()
        return job

    def cancel_document(self, document_id: str) -> None:
        for job in self.list(document_id):
            if not job.finished:
                self.cancel(job.id)

    def shutdown(self) -> None:
        for job in self.list():
            if not job.finished:
                self.cancel(job.id)
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ execution
    def _run(self, job: Job, payload: dict[str, Any], cancel: Any, on_done: OnDone | None) -> None:
        with self._lock:
            if job.finished:
                return
            job.status = JobStatus.RUNNING
        try:
            if self.isolation == "process":
                outcome = self._run_process(job, payload, cancel)
            else:
                outcome = self._run_inline(job, payload, cancel)
        except Exception as exc:  # the supervisor itself failed
            log.exception("Job %s failed", job.id)
            outcome = ("error", {"message": repr(exc)})
        kind, data = outcome
        if kind == "done":
            job.result = data
            try:
                if on_done is not None:
                    on_done(job)
            except Exception as exc:
                log.exception("Could not store the result of job %s", job.id)
                job.error = str(exc)
                self._finish(job, JobStatus.FAILED)
                return
            self._finish(job, JobStatus.DONE)
        elif kind == "cancelled":
            self._finish(job, JobStatus.CANCELLED)
        else:
            job.error = str((data or {}).get("message") or "unknown error")
            self._finish(job, JobStatus.FAILED)

    def _run_process(self, job: Job, payload: dict[str, Any], cancel: Any) -> tuple[str, Any]:
        events = self._context.Queue()
        process = self._context.Process(
            target=run_job, args=(job.kind, payload, events, cancel), daemon=True
        )
        process.start()
        cancelled_at: float | None = None
        try:
            while True:
                try:
                    kind, data = events.get(timeout=0.25)
                except queue.Empty:
                    if cancel.is_set():
                        cancelled_at = cancelled_at or time.monotonic()
                        if time.monotonic() - cancelled_at > _CANCEL_GRACE:
                            process.terminate()
                            return "cancelled", None
                    if not process.is_alive():
                        try:
                            kind, data = events.get(timeout=1.0)
                        except queue.Empty:
                            code = process.exitcode
                            return "error", {"message": f"job process ended (exit code {code})"}
                    else:
                        continue
                if kind == "progress":
                    self._progress(job, data)
                    continue
                return kind, data
        finally:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
            events.close()

    def _run_inline(self, job: Job, payload: dict[str, Any], cancel: Any) -> tuple[str, Any]:
        outcome: list[tuple[str, Any]] = []

        class Sink:
            def put(sink, item: tuple[str, Any]) -> None:
                kind, data = item
                if kind == "progress":
                    self._progress(job, data)
                else:
                    outcome.append(item)

        run_job(job.kind, payload, Sink(), cancel)
        return outcome[-1] if outcome else ("error", {"message": "job ended without a result"})

    def _progress(self, job: Job, data: dict[str, Any]) -> None:
        with self._lock:
            job.stage = str(data["stage"])
            job.stages[job.stage] = (int(data["done"]), int(data["total"]))

    def _finish(self, job: Job, status: JobStatus) -> None:
        job.status = status
        job.finished_at = now()
        self._cancels.pop(job.id, None)

    def _prune(self) -> None:
        finished = sorted(
            (j for j in self._jobs.values() if j.finished), key=lambda j: j.created_at
        )
        for job in finished[: max(0, len(finished) - _KEEP_FINISHED)]:
            self._jobs.pop(job.id, None)
