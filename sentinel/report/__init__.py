"""Builds the audit report: HTML through Jinja2, PDF through WeasyPrint."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sentinel.models import Chunk, Finding, Obligation, Run, SectionKind

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
SEVERITIES = ["critical", "high", "medium", "low"]
MAX_CHANGES_LISTED = 40

_STAT_LABELS = [
    ("new_rule_sections", "New or amended rule sections"),
    ("new_notices", "New regulator notices"),
    ("obligations_extracted", "Obligations extracted"),
    ("obligations_dropped_bad_quote", "Obligations discarded (quote not in source)"),
    ("obligations_audited", "Obligations audited"),
    ("files_scanned", "Source files read"),
    ("findings_proposed", "Findings proposed by the model"),
    ("findings_verified", "Findings that passed verification"),
    ("findings_dropped_bad_file", "Findings discarded (file not in repository)"),
    ("findings_dropped_bad_code_quote", "Findings discarded (code quote not found)"),
    ("findings_dropped_bad_regulation_quote", "Findings discarded (rule quote not found)"),
    ("findings_dropped_low_confidence", "Findings discarded (confidence under 50%)"),
    ("sections_refused", "Rule sections the model declined"),
    ("obligations_refused", "Obligations the model declined"),
]


@dataclass
class ReportPaths:
    html: Path
    pdf: Path | None


def finding_key(finding: Finding) -> tuple[str, str, str]:
    """Identity of a finding across runs, independent of line numbers."""
    return (finding.file, finding.regulation, finding.section_ref + "|" + finding.obligation_title)


def _summary(findings: list[Finding], obligations: int, changes: int) -> str:
    if not obligations:
        return (
            "No regulation text changed since the previous run and no re-audit was requested, "
            "so no obligations were audited."
        )
    if not findings:
        return (
            f"{obligations} obligation{'s were' if obligations != 1 else ' was'} audited "
            f"against the target codebase and no violations were found."
        )
    critical = sum(1 for f in findings if f.severity.value == "critical")
    files = len({f.file for f in findings})
    text = (
        f"{obligations} obligation{'s were' if obligations != 1 else ' was'} audited against "
        f"the target codebase. The audit found {len(findings)} "
        f"violation{'s' if len(findings) != 1 else ''} in {files} file{'s' if files != 1 else ''}"
    )
    if critical:
        text += f", of which {critical} {'are' if critical != 1 else 'is'} critical"
    return text + f". {changes} new or amended regulation sections were ingested in this run."


def render_html(
    run: Run,
    findings: list[Finding],
    obligations: list[Obligation],
    changes: list[Chunk],
    previous: Run | None = None,
    previous_findings: list[Finding] | None = None,
) -> str:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    counts = {s: sum(1 for f in findings if f.severity.value == s) for s in SEVERITIES}
    per_obligation: dict[int, int] = {}
    for finding in findings:
        per_obligation[finding.obligation_id] = per_obligation.get(finding.obligation_id, 0) + 1

    before = {finding_key(f) for f in previous_findings or []}
    new_keys = {finding_key(f) for f in findings} - before

    # Rule changes first, then notices; the list is capped to keep the report readable.
    ordered = sorted(changes, key=lambda c: (c.kind != SectionKind.RULE, c.regulation, c.id))
    stats = run.stats or {}
    run_details = [(label, stats[key]) for key, label in _STAT_LABELS if stats.get(key)]
    run_details += [
        ("Model input tokens", f"{run.input_tokens:,}"),
        ("Model output tokens", f"{run.output_tokens:,}"),
    ]
    if run.finished_at:
        seconds = int((run.finished_at - run.started_at).total_seconds())
        run_details.append(("Duration", f"{seconds // 60} min {seconds % 60} s"))

    return environment.get_template("report.html.j2").render(
        run=run,
        target_name=Path(run.target_repo).name or run.target_repo,
        summary=_summary(findings, len(obligations), len(changes)),
        severities=SEVERITIES,
        counts=counts,
        findings=findings,
        obligations=obligations,
        findings_per_obligation=per_obligation,
        changes=ordered[:MAX_CHANGES_LISTED],
        changes_omitted=max(0, len(ordered) - MAX_CHANGES_LISTED),
        previous=previous,
        new_keys=new_keys,
        finding_key=finding_key,
        run_details=run_details,
    )


def write_report(html: str, reports_dir: Path, run_id: int) -> ReportPaths:
    """Write the HTML report and, where WeasyPrint is available, the PDF."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    html_path = reports_dir / f"audit-run-{run_id}.html"
    html_path.write_text(html, encoding="utf-8")

    pdf_path: Path | None = reports_dir / f"audit-run-{run_id}.pdf"
    try:
        from weasyprint import HTML

        HTML(string=html).write_pdf(str(pdf_path))
    except (ImportError, OSError) as error:
        # WeasyPrint needs the Pango native libraries, which the Docker image
        # provides. Without them the HTML report is still produced.
        log.warning("PDF not generated (%s); the HTML report is at %s", error, html_path)
        pdf_path = None
    return ReportPaths(html=html_path, pdf=pdf_path)
