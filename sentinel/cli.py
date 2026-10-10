"""Command line entry point: `sentinel <command>`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sentinel.config import REPO_ROOT, get_settings


def _cmd_migrate(args: argparse.Namespace) -> int:
    from sentinel.store.postgres import migrate

    settings = get_settings()
    if not settings.database_url:
        print("SENTINEL_DATABASE_URL is not set; nothing to migrate.")
        return 1
    applied = migrate(settings.database_url)
    print("Applied: " + ", ".join(applied) if applied else "Database is up to date.")
    return 0


def _sources(args: argparse.Namespace, settings):
    from sentinel.scrapers import demo_source, load_sources

    if args.simulate_amendment:
        return [demo_source(amended=True)]
    if args.demo:
        return [demo_source()]
    return load_sources(settings.sources_file, only=args.source or None)


def _cmd_scrape(args: argparse.Namespace) -> int:
    from sentinel.ingest.embeddings import get_embedder
    from sentinel.pipeline import scrape_all
    from sentinel.store import open_store

    settings = get_settings()
    store = open_store(settings)
    try:
        results, errors = scrape_all(
            _sources(args, settings), store, get_embedder(settings), settings
        )
    finally:
        store.close()
    for name, stats in results.items():
        print(
            f"{name}: {stats.documents_changed} of {stats.documents_fetched} documents changed, "
            f"{stats.chunks_added} sections added, {stats.chunks_superseded} superseded"
        )
    for error in errors:
        print(f"PROBLEM {error}")
    return 1 if errors else 0


def _cmd_search(args: argparse.Namespace) -> int:
    from sentinel.ingest.embeddings import get_embedder
    from sentinel.rag import format_citation, retrieve
    from sentinel.store import open_store

    settings = get_settings()
    if not settings.database_url:
        print("Search needs a database: set SENTINEL_DATABASE_URL and run `sentinel scrape`.")
        return 1
    store = open_store(settings)
    try:
        hits = retrieve(store, get_embedder(settings), args.query, k=args.k)
    finally:
        store.close()
    for chunk in hits:
        print(f"\n{format_citation(chunk)}\n{chunk.title}\n{chunk.text[:400]}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from sentinel.ingest.embeddings import get_embedder
    from sentinel.llm import ClaudeLLM
    from sentinel.pipeline import run_pipeline
    from sentinel.store import open_store

    settings = get_settings()
    store = open_store(settings)
    try:
        result = run_pipeline(
            settings,
            store,
            get_embedder(settings),
            ClaudeLLM(settings),
            _sources(args, settings),
            target_repo=args.repo,
            full=args.full,
        )
    finally:
        store.close()
    print(f"Run {result.run.id}: {len(result.findings)} findings")
    print(f"Report: {result.report.pdf or result.report.html}")
    if result.alerts_sent:
        print("Alerts sent: " + ", ".join(result.alerts_sent))
    for error in result.scrape_errors:
        print(f"PROBLEM {error}")
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    from sentinel.scoring import format_score, score_file

    score = score_file(Path(args.findings), Path(args.ground_truth), Path(args.repo))
    print(format_score(score))
    return 0


def _cmd_worker(args: argparse.Namespace) -> int:
    from sentinel.queueing import run_worker

    asyncio.run(run_worker(get_settings(), cron=args.cron))
    return 0


def _cmd_enqueue(args: argparse.Namespace) -> int:
    from sentinel.queueing import enqueue_run

    data = {
        "trigger": "cli",
        "repo": args.repo,
        "full": args.full,
        "simulate_amendment": args.simulate_amendment,
    }
    print("Queued job " + asyncio.run(enqueue_run(get_settings(), data)))
    return 0


def _add_source_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", action="append", help="Scrape only this source (repeatable)")
    parser.add_argument(
        "--demo", action="store_true", help="Use the bundled synthetic regulation, no network"
    )
    parser.add_argument(
        "--simulate-amendment",
        action="store_true",
        help="Ingest the amended version of the synthetic regulation",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate", help="Apply database migrations").set_defaults(func=_cmd_migrate)

    scrape = commands.add_parser("scrape", help="Scrape sources and store what changed")
    _add_source_flags(scrape)
    scrape.set_defaults(func=_cmd_scrape)

    search = commands.add_parser("search", help="Search the stored regulation text")
    search.add_argument("query")
    search.add_argument("-k", type=int, default=5)
    search.set_defaults(func=_cmd_search)

    run = commands.add_parser("run", help="Scrape, audit and write the report")
    _add_source_flags(run)
    run.add_argument("--repo", help="Path or git URL of the codebase to audit")
    run.add_argument(
        "--full", action="store_true", help="Re-audit every stored obligation, not only new ones"
    )
    run.set_defaults(func=_cmd_run)

    score = commands.add_parser("score", help="Score a findings file against the seeded violations")
    score.add_argument("findings", help="Path to an audit-run-N.json file")
    score.add_argument("--ground-truth", default=str(REPO_ROOT / "evals" / "ground_truth.json"))
    score.add_argument("--repo", default=str(REPO_ROOT / "demo_repo"))
    score.set_defaults(func=_cmd_score)

    worker = commands.add_parser("worker", help="Process queued audit jobs")
    worker.add_argument("--cron", help="Also register the daily schedule, e.g. '0 6 * * *'")
    worker.set_defaults(func=_cmd_worker)

    enqueue = commands.add_parser("enqueue", help="Queue an audit for the worker")
    enqueue.add_argument("--repo")
    enqueue.add_argument("--full", action="store_true")
    enqueue.add_argument("--simulate-amendment", action="store_true")
    enqueue.set_defaults(func=_cmd_enqueue)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
