"""BullMQ queue: the daily schedule, manual triggers and the worker that runs audits."""

from __future__ import annotations

import asyncio
import logging
import signal

from bullmq import Queue, Worker

from sentinel.config import Settings

log = logging.getLogger(__name__)

SCHEDULER_ID = "daily-audit"
JOB_NAME = "audit"
JOB_OPTIONS = {
    "attempts": 2,
    "backoff": {"type": "exponential", "delay": 60_000},
    "removeOnComplete": {"count": 100},
    "removeOnFail": {"count": 500},
}


def _queue(settings: Settings) -> Queue:
    return Queue(settings.queue_name, {"connection": settings.redis_url})


async def register_schedule(settings: Settings, cron: str) -> None:
    """Create or update the repeating job. Safe to call on every start."""
    queue = _queue(settings)
    try:
        await queue.upsertJobScheduler(
            SCHEDULER_ID, {"pattern": cron}, JOB_NAME, {"trigger": "schedule"}, JOB_OPTIONS
        )
        log.info("Schedule %r registered with cron %r", SCHEDULER_ID, cron)
    finally:
        await queue.close()


async def enqueue_run(settings: Settings, data: dict) -> str:
    queue = _queue(settings)
    try:
        job = await queue.add(JOB_NAME, data, JOB_OPTIONS)
        return str(job.id)
    finally:
        await queue.close()


def _run_job(settings: Settings, data: dict) -> dict:
    # Imported here so enqueueing does not load the model, browser and store.
    from sentinel.ingest.embeddings import get_embedder
    from sentinel.llm import ClaudeLLM
    from sentinel.pipeline import run_pipeline
    from sentinel.scrapers import demo_source, load_sources
    from sentinel.store import open_store

    store = open_store(settings)
    try:
        if data.get("simulate_amendment"):
            sources = [demo_source(amended=True)]
        else:
            sources = load_sources(settings.sources_file)
        result = run_pipeline(
            settings,
            store,
            get_embedder(settings),
            ClaudeLLM(settings),
            sources,
            target_repo=data.get("repo"),
            full=bool(data.get("full")),
        )
    finally:
        store.close()
    return {
        "run_id": result.run.id,
        "findings": len(result.findings),
        "report": str(result.report.pdf or result.report.html),
        "alerts": result.alerts_sent,
    }


async def run_worker(settings: Settings, cron: str | None = None) -> None:
    """Process audit jobs until the process is told to stop."""
    if cron:
        await register_schedule(settings, cron)

    async def process(job, token):  # noqa: ARG001 - signature required by BullMQ
        log.info("Job %s started: %s", job.id, job.data)
        # The pipeline is synchronous (Playwright, psycopg), so it runs in a
        # thread and leaves the event loop free to renew the job lock.
        return await asyncio.to_thread(_run_job, settings, job.data or {})

    worker = Worker(
        settings.queue_name,
        process,
        {"connection": settings.redis_url, "concurrency": 1, "lockDuration": 120_000},
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ("SIGTERM", "SIGINT"):
        try:
            loop.add_signal_handler(getattr(signal, signame), stop.set)
        except NotImplementedError:  # Windows event loops have no signal handlers
            pass
    log.info("Worker listening on queue %r", settings.queue_name)
    try:
        await stop.wait()
    finally:
        await worker.close()
