"""Common interface for regulatory source adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sentinel.models import RawDocument, Section


class SourceAdapter(ABC):
    """Fetches one regulatory source and parses it into sections.

    `fetch` returns the canonical content of each document: the regulation
    text itself, stripped of page chrome, so that byte-level hashing only
    reports a change when the regulation changed.
    """

    adapter_type: str = ""

    def __init__(self, name: str, regulation: str, url: str, options: dict | None = None) -> None:
        self.name = name
        self.regulation = regulation
        self.url = url
        self.options = options or {}

    @abstractmethod
    def fetch(self) -> list[RawDocument]: ...

    @abstractmethod
    def parse(self, raw: RawDocument) -> list[Section]: ...

    def _included(self, ref: str) -> bool:
        """Apply the optional `include` list of section-reference prefixes."""
        include = self.options.get("include")
        if not include:
            return True
        return any(ref == item or ref.startswith(f"{item} ") for item in include)
