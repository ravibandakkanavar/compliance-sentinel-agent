"""Slack and email alerts for findings at or above the configured severity."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

import httpx

from sentinel.config import Settings
from sentinel.models import Finding, Run, Severity

log = logging.getLogger(__name__)

MAX_LISTED = 10


def alertable(findings: list[Finding], min_severity: str) -> list[Finding]:
    threshold = Severity(min_severity).rank
    return [f for f in findings if f.severity.rank >= threshold]


def build_message(run: Run, findings: list[Finding], report_path: Path | None) -> str:
    target = Path(run.target_repo).name or run.target_repo
    lines = [
        f"Compliance Sentinel: {len(findings)} "
        f"{'violation' if len(findings) == 1 else 'violations'} need attention in {target} "
        f"(run {run.id})."
    ]
    for finding in findings[:MAX_LISTED]:
        lines.append(
            f"- [{finding.severity.value.upper()}] {finding.file}:{finding.line_start} "
            f"{finding.obligation_title} ({finding.regulation}, {finding.section_ref})"
        )
    if len(findings) > MAX_LISTED:
        lines.append(f"- and {len(findings) - MAX_LISTED} more")
    if report_path is not None:
        lines.append(f"Report: {report_path}")
    return "\n".join(lines)


def send_slack(webhook_url: str, text: str) -> None:
    response = httpx.post(webhook_url, json={"text": text}, timeout=15)
    response.raise_for_status()


def send_email(settings: Settings, subject: str, body: str, attachment: Path | None) -> None:
    message = EmailMessage()
    message["From"] = settings.alert_email_from or settings.smtp_user
    message["To"] = settings.alert_email_to
    message["Subject"] = subject
    message.set_content(body)
    if attachment is not None and attachment.exists():
        subtype = "pdf" if attachment.suffix == ".pdf" else "html"
        maintype = "application" if subtype == "pdf" else "text"
        message.add_attachment(
            attachment.read_bytes(), maintype=maintype, subtype=subtype, filename=attachment.name
        )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def send_scrape_alert(settings: Settings, run: Run, errors: list[str]) -> bool:
    """Report sources that could not be scraped, so a gap is not mistaken for 'no changes'."""
    if not settings.slack_webhook_url:
        return False
    text = f"Compliance Sentinel run {run.id}: {len(errors)} source problem(s).\n" + "\n".join(
        f"- {error}" for error in errors
    )
    try:
        send_slack(settings.slack_webhook_url, text)
    except httpx.HTTPError as error:
        log.error("Slack scrape alert failed: %s", error)
        return False
    return True


def send_alerts(
    settings: Settings, run: Run, findings: list[Finding], report_path: Path | None
) -> list[str]:
    """Send alerts on every configured channel. Returns the channels that were used.

    A channel that fails is logged and skipped: a broken webhook must not fail
    an audit whose findings are already stored.
    """
    urgent = alertable(findings, settings.alert_min_severity)
    if not urgent:
        return []
    text = build_message(run, urgent, report_path)
    sent: list[str] = []
    if settings.slack_webhook_url:
        try:
            send_slack(settings.slack_webhook_url, text)
            sent.append("slack")
        except httpx.HTTPError as error:
            log.error("Slack alert failed: %s", error)
    if settings.smtp_host and settings.alert_email_to:
        try:
            subject = f"Compliance Sentinel: {len(urgent)} violations need attention"
            send_email(settings, subject, text, report_path)
            sent.append("email")
        except (smtplib.SMTPException, OSError) as error:
            log.error("Email alert failed: %s", error)
    return sent
