"""Scores a run's findings against the seeded violations in the demo repository."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sentinel.agent.codebase import load_repo

LINE_TOLERANCE = 6


@dataclass
class Score:
    seeded: int
    detected: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    unmatched_findings: list[str] = field(default_factory=list)
    total_findings: int = 0

    @property
    def recall(self) -> float:
        return len(self.detected) / self.seeded if self.seeded else 0.0

    @property
    def precision(self) -> float:
        matched = self.total_findings - len(self.unmatched_findings)
        return matched / self.total_findings if self.total_findings else 0.0


def _anchor_lines(repo_root: Path, ground_truth: dict) -> dict[str, list[tuple[str, int]]]:
    """Resolve each seeded violation's anchors to (file, line) in the current code."""
    files = load_repo(repo_root)
    resolved: dict[str, list[tuple[str, int]]] = {}
    for violation in ground_truth["violations"]:
        places: list[tuple[str, int]] = []
        for location in violation["locations"]:
            lines = files.get(location["file"], [])
            numbers = [n for n, line in enumerate(lines, start=1) if location["anchor"] in line]
            if not numbers:
                raise ValueError(
                    f"Ground truth anchor not found for {violation['id']}: "
                    f"{location['file']} / {location['anchor']!r}"
                )
            places.extend((location["file"], n) for n in numbers)
        resolved[violation["id"]] = places
    return resolved


def score_findings(findings: list[dict], ground_truth: dict, repo_root: Path) -> Score:
    """A finding matches a violation when it overlaps one of its anchors, give or take a few lines.

    An unmatched finding is not necessarily wrong: the model may have found a
    real problem that was not seeded. Unmatched findings are listed for review.
    """
    anchors = _anchor_lines(repo_root, ground_truth)
    score = Score(seeded=len(anchors), total_findings=len(findings))
    detected: set[str] = set()
    for finding in findings:
        hit = False
        for violation_id, places in anchors.items():
            for file, line in places:
                if finding["file"] == file and (
                    finding["line_start"] - LINE_TOLERANCE
                    <= line
                    <= finding["line_end"] + LINE_TOLERANCE
                ):
                    detected.add(violation_id)
                    hit = True
        if not hit:
            score.unmatched_findings.append(
                f"{finding['file']}:{finding['line_start']} {finding['obligation_title']}"
            )
    score.detected = sorted(detected)
    score.missed = sorted(set(anchors) - detected)
    return score


def score_file(findings_path: Path, ground_truth_path: Path, repo_root: Path) -> Score:
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    return score_findings(findings, ground_truth, repo_root)


def format_score(score: Score) -> str:
    lines = [
        f"Seeded violations detected: {len(score.detected)} of {score.seeded} "
        f"(recall {score.recall:.0%})",
        f"Findings matching a seeded violation: "
        f"{score.total_findings - len(score.unmatched_findings)} of {score.total_findings} "
        f"(precision {score.precision:.0%})",
    ]
    if score.missed:
        lines.append("Missed: " + ", ".join(score.missed))
    if score.unmatched_findings:
        lines.append("Findings with no seeded match (review by hand):")
        lines.extend(f"  - {item}" for item in score.unmatched_findings)
    return "\n".join(lines)
