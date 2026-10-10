from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from sentinel.agent.prompts import (
    ExtractedObligation,
    FindingBatch,
    ObligationBatch,
    RawFinding,
)
from sentinel.config import REPO_ROOT, Settings
from sentinel.ingest.embeddings import HashEmbedder
from sentinel.llm import Usage
from sentinel.store import MemoryStore

DEMO_REPO = REPO_ROOT / "demo_repo"

# Importing sentinel.config loads the developer's .env into the environment.
# Tests must not depend on it, so every SENTINEL_ variable is removed again.
for _name in [name for name in os.environ if name.startswith("SENTINEL_")]:
    del os.environ[_name]

_SECTION = re.compile(
    r'<section chunk_id="(\d+)" regulation="[^"]*" ref="([^"]*)">\n(.*?)\n(.*?)\n</section>',
    re.DOTALL,
)


class FakeLLM:
    """Stands in for Claude. Handlers receive the prompt parts and return schema objects."""

    def __init__(
        self,
        extract: Callable[[str], ObligationBatch] | None = None,
        evaluate: Callable[[str, str], FindingBatch] | None = None,
    ) -> None:
        self.usage = Usage()
        self.calls: list[tuple[str, str]] = []
        self._extract = extract or first_sentence_obligations
        self._evaluate = evaluate or (lambda context, task: FindingBatch(findings=[]))

    def parse(self, system, context, task, schema):
        self.usage.calls += 1
        self.usage.input_tokens += len(context) + len(task)
        self.calls.append((schema.__name__, task))
        if schema is ObligationBatch:
            return self._extract(task)
        return self._evaluate(context, task)


def first_sentence_obligations(task: str) -> ObligationBatch:
    """One obligation per section, quoting the section's first sentence verbatim."""
    obligations = []
    for chunk_id, ref, title, text in _SECTION.findall(task):
        first_sentence = text.split(". ")[0].strip()
        obligations.append(
            ExtractedObligation(
                chunk_id=int(chunk_id),
                title=title or ref,
                requirement=f"Comply with {ref}.",
                regulation_quote=first_sentence,
                search_patterns=["password", "log\\.info", "(unclosed"],
                violation_indicators=["breach"],
            )
        )
    return ObligationBatch(obligations=obligations)


def finding(**overrides) -> RawFinding:
    values = {
        "file": "app.py",
        "line_start": 1,
        "line_end": 1,
        "code_quote": "",
        "regulation_quote": "",
        "severity": "high",
        "confidence": 0.9,
        "explanation": "The code breaks the rule.",
        "remediation": "Change the code.",
    }
    values.update(overrides)
    return RawFinding(**values)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="",
        embedder="hash",
        data_dir=str(tmp_path / "data"),
        target_repo=str(DEMO_REPO),
        slack_webhook_url="",
        smtp_host="",
    )


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def embedder(settings: Settings) -> HashEmbedder:
    return HashEmbedder(settings.embedding_dim)
