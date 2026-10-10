"""One end-to-end run: scrape, ingest, audit, report, alert."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field

from langgraph.checkpoint.memory import MemorySaver

from sentinel import alerts, report
from sentinel.agent import Deps, build_graph
from sentinel.agent.codebase import resolve_repo
from sentinel.config import Settings
from sentinel.ingest import IngestStats, ingest_source
from sentinel.ingest.embeddings import Embedder
from sentinel.llm import LLM
from sentinel.models import Finding, Obligation, Run
from sentinel.scrapers.base import SourceAdapter
from sentinel.store.base import Store

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    run: Run
    findings: list[Finding]
    report: report.ReportPaths
    alerts_sent: list[str] = field(default_factory=list)
    scrape_errors: list[str] = field(default_factory=list)


@contextmanager
def _checkpointer(settings: Settings):
    """Postgres-backed checkpoints when a database is configured, so an
    interrupted audit resumes from its last completed node."""
    if not settings.database_url:
        yield MemorySaver()
        return
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(settings.database_url) as saver:
        saver.setup()
        yield saver


def scrape_all(
    sources: list[SourceAdapter], store: Store, embedder: Embedder, settings: Settings
) -> tuple[dict[str, IngestStats], list[str]]:
    """Ingest every source. One failing source does not stop the others."""
    results: dict[str, IngestStats] = {}
    errors: list[str] = []
    for adapter in sources:
        try:
            stats = ingest_source(adapter, store, embedder, settings.snapshots_dir)
        except Exception as error:  # noqa: BLE001 - a scraper can fail in many ways
            log.exception("Scrape failed for %s", adapter.name)
            errors.append(f"{adapter.name}: {type(error).__name__}: {error}")
            continue
        results[adapter.name] = stats
        errors.extend(stats.errors)
    return results, errors


def run_pipeline(
    settings: Settings,
    store: Store,
    embedder: Embedder,
    llm: LLM,
    sources: list[SourceAdapter],
    target_repo: str | None = None,
    full: bool = False,
) -> RunResult:
    repo_path = resolve_repo(target_repo or settings.target_repo)
    run = store.create_run(str(repo_path))
    log.info("Run %s started against %s", run.id, repo_path)

    try:
        ingest_stats, scrape_errors = scrape_all(sources, store, embedder, settings)

        with _checkpointer(settings) as checkpointer:
            graph = build_graph(Deps(store=store, llm=llm, settings=settings), checkpointer)
            final = graph.invoke(
                {"run_id": run.id, "repo_path": str(repo_path), "full": full, "stats": {}},
                config={"configurable": {"thread_id": f"run-{run.id}"}},
            )

        stats = dict(final.get("stats", {}))
        stats["sources"] = {
            name: {"added": s.chunks_added, "superseded": s.chunks_superseded}
            for name, s in ingest_stats.items()
        }
        stats["scrape_errors"] = scrape_errors
        run = store.finish_run(
            run.id, "completed", llm.usage.input_tokens, llm.usage.output_tokens, stats
        )
    except Exception:
        store.finish_run(run.id, "failed", llm.usage.input_tokens, llm.usage.output_tokens, {})
        raise

    findings = store.findings_for_run(run.id)
    obligations = [Obligation(**o) for o in final.get("obligations", [])]
    previous = store.previous_run(run.id)
    # Measured from the end of the previous run, so sections that run ingested
    # itself are not reported as changes a second time.
    changes = store.chunks_created_since(previous.finished_at if previous else None)
    html = report.render_html(
        run,
        findings,
        obligations,
        changes,
        previous=previous,
        previous_findings=store.findings_for_run(previous.id) if previous else None,
    )
    paths = report.write_report(html, settings.reports_dir, run.id)
    findings_json = json.dumps([f.model_dump(mode="json") for f in findings], indent=2)
    (settings.reports_dir / f"audit-run-{run.id}.json").write_text(findings_json, encoding="utf-8")

    sent = alerts.send_alerts(settings, run, findings, paths.pdf or paths.html)
    if scrape_errors:
        log.warning("Scrape problems: %s", "; ".join(scrape_errors))
        if alerts.send_scrape_alert(settings, run, scrape_errors):
            sent.append("slack-scrape-errors")
    log.info("Run %s finished: %d findings, report at %s", run.id, len(findings), paths.html)
    return RunResult(
        run=run, findings=findings, report=paths, alerts_sent=sent, scrape_errors=scrape_errors
    )
