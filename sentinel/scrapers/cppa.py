"""California Privacy Protection Agency: the CCPA regulations, published as a PDF."""

from __future__ import annotations

import io
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pypdf import PdfReader

from sentinel.models import RawDocument, Section
from sentinel.scrapers.base import SourceAdapter
from sentinel.scrapers.browser import fetch_bytes, fetch_html

_SECTION_HEADING = re.compile(r"^\s*§\s*(7\d{3})\.\s+(.+?)\s*$")
_PAGE_FURNITURE = re.compile(r"^\s*(CPPA|Page \d+ of \d+)\s*$")
_ARTICLE_HEADING = re.compile(r"^\s*A\s*RTICLE \d+\.")
_NOTE = re.compile(r"^\s*Note: Authority cited:")


def find_regulations_pdf(html: str, page_url: str, link_text: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    pattern = re.compile(link_text, re.IGNORECASE)
    for link in soup.find_all("a", href=re.compile(r"\.pdf$", re.IGNORECASE)):
        if pattern.search(re.sub(r"\s+", " ", link.get_text(" ", strip=True))):
            return urljoin(page_url, link["href"])
    return None


def parse_regulations_text(text: str) -> list[tuple[str, str, str]]:
    """Split the regulations into (section number, title, body) triples.

    The table of contents repeats every heading followed by dot leaders and a
    page number; those lines are skipped so only the body headings start a section.
    """
    sections: list[tuple[str, str, list[str]]] = []
    current: tuple[str, str, list[str]] | None = None
    in_note = False
    for line in text.splitlines():
        if _PAGE_FURNITURE.match(line):
            continue
        heading = _SECTION_HEADING.match(line)
        if heading and "...." not in line:
            current = (heading.group(1), heading.group(2), [])
            sections.append(current)
            in_note = False
            continue
        if current is None or "...." in line or _ARTICLE_HEADING.match(line):
            continue
        # The authority note closes each section and is not regulatory text.
        if _NOTE.match(line):
            in_note = True
        if not in_note and line.strip():
            current[2].append(line.strip())
    return [(number, title, "\n".join(body)) for number, title, body in sections if body]


class CppaRegulationsAdapter(SourceAdapter):
    adapter_type = "cppa"

    def fetch(self) -> list[RawDocument]:
        html = fetch_html(self.url)
        link_text = self.options.get("link_text", r"CCPA Regulations")
        pdf_url = find_regulations_pdf(html, self.url, link_text)
        if pdf_url is None:
            return []
        return [
            RawDocument(
                source=self.name,
                key=self.options.get("key", "ccpa-regulations"),
                regulation=self.regulation,
                url=pdf_url,
                title=self.options.get("title", self.regulation),
                content=fetch_bytes(pdf_url),
                content_type="application/pdf",
            )
        ]

    def parse(self, raw: RawDocument) -> list[Section]:
        reader = PdfReader(io.BytesIO(raw.content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return [
            Section(ref=f"§ {number}", title=title, text=body)
            for number, title, body in parse_regulations_text(text)
            if self._included(f"§ {number}")
        ]
