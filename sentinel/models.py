"""Domain records shared by the scrapers, the store, the agent and the report."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return ["low", "medium", "high", "critical"].index(self.value)


class SectionKind(StrEnum):
    # A rule is regulation text that can create obligations. A notice is a
    # listing entry (new guidance published) that is reported but not audited.
    RULE = "rule"
    NOTICE = "notice"


class Section(BaseModel):
    """One addressable unit of a regulation, as parsed from a source document."""

    ref: str
    title: str = ""
    text: str
    kind: SectionKind = SectionKind.RULE


class RawDocument(BaseModel):
    """A fetched source document before it is stored."""

    source: str
    key: str
    regulation: str
    url: str
    title: str
    content: bytes
    content_type: str
    retrieved_at: datetime = Field(default_factory=utcnow)


class Document(BaseModel):
    id: int
    source: str
    key: str
    regulation: str
    url: str
    title: str
    content_hash: str
    retrieved_at: datetime


class Chunk(BaseModel):
    id: int
    document_id: int
    regulation: str
    section_ref: str
    title: str
    text: str
    text_hash: str
    kind: SectionKind = SectionKind.RULE
    url: str = ""
    retrieved_at: datetime | None = None
    superseded: bool = False
    processed: bool = False


class NewChunk(BaseModel):
    regulation: str
    section_ref: str
    title: str
    text: str
    text_hash: str
    kind: SectionKind = SectionKind.RULE
    embedding: list[float]


class Obligation(BaseModel):
    id: int = 0
    chunk_id: int
    regulation: str
    section_ref: str
    title: str
    requirement: str
    regulation_quote: str
    search_patterns: list[str] = Field(default_factory=list)
    violation_indicators: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    id: int = 0
    run_id: int = 0
    obligation_id: int
    chunk_id: int
    regulation: str
    section_ref: str
    obligation_title: str
    file: str
    line_start: int
    line_end: int
    snippet: str
    severity: Severity
    confidence: float
    explanation: str
    remediation: str
    regulation_quote: str
    source_url: str = ""
    retrieved_at: datetime | None = None


class Run(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str = "running"
    target_repo: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    stats: dict = Field(default_factory=dict)
