"""End-to-end runs over the demo regulation and demo repository with a stubbed model."""

from __future__ import annotations

import json

from conftest import DEMO_REPO, FakeLLM, finding, first_sentence_obligations

from sentinel.agent.prompts import ExtractedObligation, FindingBatch, ObligationBatch
from sentinel.pipeline import run_pipeline
from sentinel.scrapers import demo_source

LOG_QUOTE = "A service shall not write government identifiers"
PASSWORD_QUOTE = "A service shall not store, compare or transmit a user password in plain text."


def evaluate(context: str, task: str) -> FindingBatch:
    """Canned model output: correct findings mixed with the errors verification must catch."""
    if "Duty: Personal data in logs" in task:
        return FindingBatch(
            findings=[
                # Correct, but with the wrong line numbers.
                finding(
                    file="app.py",
                    line_start=3,
                    line_end=4,
                    code_quote='"New signup id=%s email=%s ssn=%s dob=%s",',
                    regulation_quote=LOG_QUOTE,
                    severity="critical",
                ),
                # Quoted code that does not exist in the file.
                finding(
                    file="app.py",
                    code_quote="logger.debug(user.password)",
                    regulation_quote=LOG_QUOTE,
                ),
                # A rule quote that is not in the cited section.
                finding(
                    file="app.py",
                    code_quote='log = logging.getLogger("shoplite")',
                    regulation_quote="Logs shall be encrypted at rest.",
                ),
                # A file that is not in the repository.
                finding(file="server.py", code_quote="x", regulation_quote=LOG_QUOTE),
                # Real code, real quote, but the model itself is unsure.
                finding(
                    file="app.py",
                    code_quote="db.record_access(user_id, request.remote_addr, request.path)",
                    regulation_quote=LOG_QUOTE,
                    confidence=0.3,
                ),
            ]
        )
    if "Duty: Storage of credentials" in task:
        return FindingBatch(
            findings=[
                finding(
                    file="db.py",
                    line_start=90,
                    line_end=90,
                    code_quote='return user is not None and user["password"] == password',
                    regulation_quote=PASSWORD_QUOTE,
                    severity="critical",
                ),
                finding(
                    file="./config.py",
                    line_start=1,
                    line_end=1,
                    code_quote='SMTP_PASSWORD = "Sh0pl1te!Mail2023"',
                    regulation_quote="shall not be embedded in source code",
                    severity="high",
                ),
            ]
        )
    return FindingBatch(findings=[])


def extract_with_one_fabricated_quote(task: str) -> ObligationBatch:
    batch = first_sentence_obligations(task)
    batch.obligations.append(
        ExtractedObligation(
            chunk_id=batch.obligations[0].chunk_id,
            title="Invented duty",
            requirement="Not in the text.",
            regulation_quote="A service shall appoint a chief logging officer.",
            search_patterns=[],
            violation_indicators=[],
        )
    )
    return batch


def test_first_run_reports_only_verified_findings(settings, store, embedder):
    llm = FakeLLM(extract=extract_with_one_fabricated_quote, evaluate=evaluate)

    result = run_pipeline(settings, store, embedder, llm, [demo_source()])

    stats = result.run.stats
    assert result.run.status == "completed"
    assert stats["new_rule_sections"] == 5
    assert stats["obligations_extracted"] == 5
    assert stats["obligations_dropped_bad_quote"] == 1
    assert stats["findings_proposed"] == 7
    assert stats["findings_verified"] == 3
    assert stats["findings_dropped_bad_code_quote"] == 1
    assert stats["findings_dropped_bad_regulation_quote"] == 1
    assert stats["findings_dropped_bad_file"] == 1
    assert stats["findings_dropped_low_confidence"] == 1

    by_file = {f.file: f for f in result.findings}
    assert set(by_file) == {"app.py", "db.py", "config.py"}

    # Line numbers come from where the quoted code is, not from what the model claimed.
    log_finding = by_file["app.py"]
    app_lines = (DEMO_REPO / "app.py").read_text(encoding="utf-8").splitlines()
    assert "New signup id=%s" in app_lines[log_finding.line_start - 1]
    assert log_finding.snippet.strip() == '"New signup id=%s email=%s ssn=%s dob=%s",'
    assert log_finding.section_ref == "Section 2"
    assert log_finding.source_url.endswith("demo_regulation_v1.md")
    assert log_finding.retrieved_at is not None

    # Critical findings sort first.
    assert [f.severity.value for f in result.findings] == ["critical", "critical", "high"]


def test_report_and_findings_file_are_written(settings, store, embedder):
    result = run_pipeline(settings, store, embedder, FakeLLM(evaluate=evaluate), [demo_source()])

    html = result.report.html.read_text(encoding="utf-8")
    assert "Compliance audit report" in html
    assert "app.py" in html and "Section 2" in html
    # Code and quotes are escaped, not injected as markup.
    assert "&#34;New signup id=%s" in html or "&quot;New signup id=%s" in html
    assert LOG_QUOTE in html
    assert "Findings discarded (code quote not found)" in html

    saved = json.loads(
        (settings.reports_dir / f"audit-run-{result.run.id}.json").read_text(encoding="utf-8")
    )
    assert len(saved) == 3 and {"file", "line_start", "regulation_quote"} <= set(saved[0])


def test_unchanged_regulation_means_no_model_calls_on_the_next_run(settings, store, embedder):
    llm = FakeLLM(evaluate=evaluate)
    run_pipeline(settings, store, embedder, llm, [demo_source()])
    calls_after_first = llm.usage.calls

    second = run_pipeline(settings, store, embedder, llm, [demo_source()])

    assert llm.usage.calls == calls_after_first
    assert second.findings == []
    assert second.run.stats.get("new_rule_sections", 0) == 0
    assert "No new or amended regulation text" in second.report.html.read_text(encoding="utf-8")


def test_amendment_audits_only_the_new_and_changed_sections(settings, store, embedder):
    llm = FakeLLM(evaluate=evaluate)
    run_pipeline(settings, store, embedder, llm, [demo_source()])
    llm.calls.clear()

    result = run_pipeline(settings, store, embedder, llm, [demo_source(amended=True)])

    assert result.run.stats["new_rule_sections"] == 3
    assert result.run.stats["obligations_audited"] == 3
    evaluated = [task for schema, task in llm.calls if schema == "FindingBatch"]
    assert len(evaluated) == 3
    assert all("Section 1" not in task.split("</obligation>")[0] for task in evaluated)
    html = result.report.html.read_text(encoding="utf-8")
    assert "Retention of access records" in html
    assert "Compared with run" in html


def test_full_run_re_audits_stored_obligations_without_new_rules(settings, store, embedder):
    llm = FakeLLM(evaluate=evaluate)
    run_pipeline(settings, store, embedder, llm, [demo_source()])

    result = run_pipeline(settings, store, embedder, llm, [demo_source()], full=True)

    assert result.run.stats["obligations_audited"] == 5
    assert len(result.findings) == 3


def test_a_failing_source_is_reported_and_does_not_stop_the_run(settings, store, embedder):
    class Broken(type(demo_source())):
        def fetch(self):
            raise RuntimeError("portal unreachable")

    broken = Broken("broken", "X", "u", {})
    result = run_pipeline(
        settings, store, embedder, FakeLLM(evaluate=evaluate), [broken, demo_source()]
    )

    assert result.run.status == "completed"
    assert result.scrape_errors == ["broken: RuntimeError: portal unreachable"]
    assert len(result.findings) == 3
