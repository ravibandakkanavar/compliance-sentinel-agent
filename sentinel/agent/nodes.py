"""The six nodes of the audit graph.

State values are plain JSON-compatible data so the graph can be checkpointed
and resumed. The store, model and settings reach the nodes through `Deps`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from sentinel.agent import codebase
from sentinel.agent.prompts import (
    EVALUATE_SYSTEM,
    EXTRACT_SYSTEM,
    FindingBatch,
    ObligationBatch,
    render_obligation,
    render_sections,
)
from sentinel.config import Settings
from sentinel.ingest.chunking import normalize
from sentinel.llm import LLM, LLMRefusal
from sentinel.models import Finding, Obligation, SectionKind, Severity
from sentinel.store.base import Store

log = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.5
MAX_SNIPPET_LINES = 12


class AuditState(TypedDict, total=False):
    run_id: int
    repo_path: str
    full: bool
    pending_chunks: list[dict]
    obligations: list[dict]
    scans: dict[str, dict]
    raw_findings: list[dict]
    findings: list[dict]
    stats: dict


@dataclass
class Deps:
    store: Store
    llm: LLM
    settings: Settings


def _bump(state: AuditState, **counts: int) -> dict:
    stats = dict(state.get("stats", {}))
    for key, value in counts.items():
        stats[key] = stats.get(key, 0) + value
    return stats


def load_new_rules(state: AuditState, deps: Deps) -> dict:
    """Pick up regulation sections that have not been turned into obligations yet."""
    pending = deps.store.pending_chunks(deps.settings.max_chunks_per_run)
    rules = [c for c in pending if c.kind == SectionKind.RULE]
    notices = [c for c in pending if c.kind == SectionKind.NOTICE]
    # Notices are reported in the change log only, so they need no further work.
    deps.store.mark_processed([c.id for c in notices])
    return {
        "pending_chunks": [c.model_dump(mode="json") for c in rules],
        "stats": _bump(state, new_rule_sections=len(rules), new_notices=len(notices)),
    }


def route_after_load(state: AuditState) -> str:
    if state.get("pending_chunks"):
        return "extract_obligations"
    if state.get("full"):
        return "scan_codebase"
    return "compile_report"


def extract_obligations(state: AuditState, deps: Deps) -> dict:
    """Turn new regulation sections into structured, code-checkable obligations."""
    chunks = state["pending_chunks"]
    by_id = {c["id"]: c for c in chunks}
    size = deps.settings.obligation_batch_size
    accepted: list[Obligation] = []
    dropped = 0
    refused = 0

    for start in range(0, len(chunks), size):
        batch = chunks[start : start + size]
        try:
            result = deps.llm.parse(
                system=EXTRACT_SYSTEM,
                context="",
                task=render_sections(batch),
                schema=ObligationBatch,
            )
        except LLMRefusal as error:
            # Left unprocessed so the next run retries these sections.
            log.warning("Obligation extraction declined for %d sections: %s", len(batch), error)
            refused += len(batch)
            continue

        batch_ids = {c["id"] for c in batch}
        for item in result.obligations:
            chunk = by_id.get(item.chunk_id)
            quote = normalize(item.regulation_quote)
            if (
                chunk is None
                or item.chunk_id not in batch_ids
                or not quote
                or quote not in normalize(chunk["text"])
            ):
                dropped += 1
                continue
            patterns = [p.pattern for p in codebase.compile_patterns(item.search_patterns)]
            accepted.append(
                Obligation(
                    chunk_id=chunk["id"],
                    regulation=chunk["regulation"],
                    section_ref=chunk["section_ref"],
                    title=item.title,
                    requirement=item.requirement,
                    regulation_quote=item.regulation_quote.strip(),
                    search_patterns=patterns,
                    violation_indicators=item.violation_indicators,
                )
            )
        deps.store.mark_processed(sorted(batch_ids))

    saved = deps.store.add_obligations(accepted)
    return {
        "obligations": [o.model_dump(mode="json") for o in saved],
        "stats": _bump(
            state,
            obligations_extracted=len(saved),
            obligations_dropped_bad_quote=dropped,
            sections_refused=refused,
        ),
    }


def scan_codebase(state: AuditState, deps: Deps) -> dict:
    """Select, for each obligation, the code the model should read."""
    obligations = state.get("obligations", [])
    if state.get("full"):
        known = {o["id"] for o in obligations}
        obligations = obligations + [
            o.model_dump(mode="json") for o in deps.store.active_obligations() if o.id not in known
        ]

    files = codebase.load_repo(Path(state["repo_path"]))
    whole_repo = codebase.total_chars(files) <= deps.settings.whole_repo_char_budget
    scans: dict[str, dict] = {}
    for obligation in obligations:
        if whole_repo:
            # A small repository is shown in full to every obligation: the text
            # is identical across calls, so it is read from the prompt cache,
            # and missing safeguards are visible where a search would find nothing.
            scans[str(obligation["id"])] = {"mode": "whole"}
            continue
        hits = codebase.grep(files, obligation["search_patterns"])
        scans[str(obligation["id"])] = {
            "mode": "snippets",
            "text": codebase.render_snippets(
                files, hits, char_budget=deps.settings.snippet_char_budget
            ),
        }

    return {
        "obligations": obligations,
        "scans": scans,
        "stats": _bump(state, files_scanned=len(files), obligations_audited=len(obligations)),
    }


def evaluate_findings(state: AuditState, deps: Deps) -> dict:
    """Ask the model, one obligation at a time, whether the selected code breaks it."""
    files = codebase.load_repo(Path(state["repo_path"]))
    whole_repo_text = codebase.render_repo(files)
    raw: list[dict] = []
    refused = 0

    for obligation in state.get("obligations", []):
        scan = state["scans"][str(obligation["id"])]
        context = whole_repo_text if scan["mode"] == "whole" else scan["text"]
        if not context:
            continue
        chunk = deps.store.get_chunk(obligation["chunk_id"])
        if chunk is None:
            continue
        try:
            result = deps.llm.parse(
                system=EVALUATE_SYSTEM,
                context=f"<source_files>\n{context}\n</source_files>",
                task=render_obligation(obligation, chunk.model_dump(mode="json")),
                schema=FindingBatch,
            )
        except LLMRefusal as error:
            log.warning("Evaluation declined for obligation %s: %s", obligation["id"], error)
            refused += 1
            continue
        for item in result.findings:
            raw.append({**item.model_dump(), "obligation_id": obligation["id"]})

    return {
        "raw_findings": raw,
        "stats": _bump(state, findings_proposed=len(raw), obligations_refused=refused),
    }


def verify(state: AuditState, deps: Deps) -> dict:
    """Keep only findings whose code location and regulation quote both check out.

    Nothing here calls the model. A finding survives when its quoted code is
    found in the named file and its quoted regulation text is found in the
    section it cites; line numbers are corrected to where the code really is.
    """
    files = codebase.load_repo(Path(state["repo_path"]))
    obligations = {o["id"]: o for o in state.get("obligations", [])}
    kept: list[Finding] = []
    seen: set[tuple[int, str, int]] = set()
    dropped = {"bad_file": 0, "bad_code_quote": 0, "bad_regulation_quote": 0, "low_confidence": 0}

    for raw in state.get("raw_findings", []):
        obligation = obligations[raw["obligation_id"]]
        chunk = deps.store.get_chunk(obligation["chunk_id"])
        path = raw["file"].replace("\\", "/").removeprefix("./")
        lines = files.get(path)
        if lines is None or chunk is None:
            dropped["bad_file"] += 1
            continue
        location = codebase.locate_quote(lines, raw["code_quote"], raw["line_start"])
        if location is None:
            dropped["bad_code_quote"] += 1
            continue
        quote = normalize(raw["regulation_quote"])
        if not quote or quote not in normalize(chunk.text):
            dropped["bad_regulation_quote"] += 1
            continue
        confidence = max(0.0, min(1.0, float(raw["confidence"])))
        if confidence < MIN_CONFIDENCE:
            dropped["low_confidence"] += 1
            continue

        start, end = location
        key = (obligation["id"], path, start)
        if key in seen:
            continue
        seen.add(key)
        end = min(end, start + MAX_SNIPPET_LINES - 1)
        kept.append(
            Finding(
                obligation_id=obligation["id"],
                chunk_id=chunk.id,
                regulation=chunk.regulation,
                section_ref=chunk.section_ref,
                obligation_title=obligation["title"],
                file=path,
                line_start=start,
                line_end=end,
                snippet="\n".join(lines[start - 1 : end]),
                severity=Severity(raw["severity"]),
                confidence=round(confidence, 2),
                explanation=raw["explanation"].strip(),
                remediation=raw["remediation"].strip(),
                regulation_quote=raw["regulation_quote"].strip(),
                source_url=chunk.url,
                retrieved_at=chunk.retrieved_at,
            )
        )

    kept.sort(key=lambda f: (-f.severity.rank, f.file, f.line_start))
    stats = _bump(
        state,
        findings_verified=len(kept),
        **{f"findings_dropped_{reason}": count for reason, count in dropped.items()},
    )
    return {"findings": [f.model_dump(mode="json") for f in kept], "stats": stats}


def compile_report(state: AuditState, deps: Deps) -> dict:
    """Persist the verified findings; rendering happens from the stored run."""
    findings = [Finding(**f) for f in state.get("findings", [])]
    saved = deps.store.add_findings(state["run_id"], findings)
    return {"findings": [f.model_dump(mode="json") for f in saved]}
