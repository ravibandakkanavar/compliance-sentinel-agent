from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import DEMO_REPO
from fastapi.testclient import TestClient

from sentinel import alerts
from sentinel.api import app
from sentinel.config import REPO_ROOT, Settings, get_settings
from sentinel.models import Finding, Run, Severity, utcnow
from sentinel.scoring import score_findings

GROUND_TRUTH = json.loads((REPO_ROOT / "evals" / "ground_truth.json").read_text(encoding="utf-8"))


def _line_of(file: str, anchor: str) -> int:
    lines = (DEMO_REPO / file).read_text(encoding="utf-8").splitlines()
    return next(n for n, line in enumerate(lines, start=1) if anchor in line)


def _finding(file: str, line: int, title: str = "t") -> dict:
    return {"file": file, "line_start": line, "line_end": line, "obligation_title": title}


def test_every_ground_truth_anchor_exists_in_the_demo_repo():
    # Fails when the demo app is edited without updating the answer key.
    score = score_findings([], GROUND_TRUTH, DEMO_REPO)
    assert score.seeded == 12 and len(score.missed) == 12


def test_scoring_counts_detected_missed_and_unmatched():
    findings = [
        _finding("app.py", _line_of("app.py", "New signup id=%s")),
        _finding("config.py", _line_of("config.py", "RETENTION_DAYS = None") + 2),
        _finding("services/marketing.py", 1, "Unrelated import"),
    ]
    score = score_findings(findings, GROUND_TRUTH, DEMO_REPO)

    assert "pii-in-logs" in score.detected and "no-retention-limit" in score.detected
    assert "sale-ignores-opt-out" in score.missed
    assert score.unmatched_findings == ["services/marketing.py:1 Unrelated import"]
    assert score.total_findings == 3


def test_scoring_fails_loudly_on_a_stale_anchor():
    stale = {"violations": [{"id": "x", "locations": [{"file": "app.py", "anchor": "no such"}]}]}
    with pytest.raises(ValueError, match="anchor not found"):
        score_findings([], stale, DEMO_REPO)


def _model_finding(severity: str) -> Finding:
    return Finding(
        obligation_id=1, chunk_id=1, regulation="GDPR", section_ref="Article 32",
        obligation_title="Encrypt transfers", file="a.py", line_start=7, line_end=7,
        snippet="x", severity=Severity(severity), confidence=0.9, explanation="e",
        remediation="r", regulation_quote="q",
    )  # fmt: skip


def test_only_findings_at_or_above_the_threshold_alert():
    findings = [_model_finding(s) for s in ("low", "high", "critical")]
    assert [f.severity.value for f in alerts.alertable(findings, "high")] == ["high", "critical"]
    assert [f.severity.value for f in alerts.alertable(findings, "critical")] == ["critical"]


def test_alert_message_names_location_rule_and_report():
    run = Run(id=9, started_at=utcnow(), target_repo="/srv/shoplite")
    text = alerts.build_message(run, [_model_finding("critical")], Path("/data/audit-run-9.pdf"))
    assert "1 violation need" in text and "shoplite (run 9)" in text
    assert "[CRITICAL] a.py:7 Encrypt transfers (GDPR, Article 32)" in text
    assert "audit-run-9.pdf" in text


def test_no_channel_configured_sends_nothing(settings):
    run = Run(id=1, started_at=utcnow())
    assert alerts.send_alerts(settings, run, [_model_finding("critical")], None) == []


def test_slack_failure_does_not_raise(settings, monkeypatch):
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "post", boom)
    configured = settings.model_copy(update={"slack_webhook_url": "https://hooks.example/x"})
    run = Run(id=1, started_at=utcnow())
    assert alerts.send_alerts(configured, run, [_model_finding("critical")], None) == []


def test_slack_alert_posts_the_message(settings, monkeypatch):
    import httpx

    sent = {}

    def fake_post(url, json, timeout):
        sent.update(url=url, text=json["text"])
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    configured = settings.model_copy(update={"slack_webhook_url": "https://hooks.example/x"})
    run = Run(id=4, started_at=utcnow(), target_repo="repo")

    assert alerts.send_alerts(configured, run, [_model_finding("critical")], None) == ["slack"]
    assert sent["url"] == "https://hooks.example/x" and "[CRITICAL]" in sent["text"]


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_needs_no_auth(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_trigger_is_off_until_a_token_is_configured(client):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, trigger_token="")
    assert client.post("/trigger", json={}).status_code == 503


def test_trigger_rejects_a_wrong_token_and_queues_with_the_right_one(client, monkeypatch):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, trigger_token="s3cret"
    )
    queued = []

    async def fake_enqueue(settings, data):
        queued.append(data)
        return "42"

    monkeypatch.setattr("sentinel.api.enqueue_run", fake_enqueue)

    assert client.post("/trigger", json={}).status_code == 401
    wrong = client.post("/trigger", json={}, headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401 and queued == []

    ok = client.post("/trigger", json={"full": True}, headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 202 and ok.json() == {"job_id": "42"}
    assert queued == [
        {"trigger": "manual", "repo": None, "full": True, "simulate_amendment": False}
    ]
