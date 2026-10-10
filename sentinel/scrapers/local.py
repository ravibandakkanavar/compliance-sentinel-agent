"""Adapter for a regulation kept as a local Markdown file.

Used for the bundled demo regulation, for tests, and for simulating an
amendment without waiting for a regulator to publish one.
"""

from __future__ import annotations

import re
from pathlib import Path

from sentinel.models import RawDocument, Section
from sentinel.scrapers.base import SourceAdapter

_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


class LocalMarkdownAdapter(SourceAdapter):
    adapter_type = "local"

    def fetch(self) -> list[RawDocument]:
        path = Path(self.options["path"])
        return [
            RawDocument(
                source=self.name,
                key=self.options.get("key", path.stem),
                regulation=self.regulation,
                url=self.url,
                title=self.options.get("title", self.regulation),
                content=path.read_bytes(),
                content_type="text/markdown",
            )
        ]

    def parse(self, raw: RawDocument) -> list[Section]:
        text = raw.content.decode("utf-8")
        matches = list(_HEADING.finditer(text))
        sections: list[Section] = []
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            heading = match.group(1)
            ref, _, title = heading.partition(" - ")
            body = text[match.end() : end].strip()
            if body and self._included(ref.strip()):
                sections.append(Section(ref=ref.strip(), title=title.strip(), text=body))
        return sections
