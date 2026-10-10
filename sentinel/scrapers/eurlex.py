"""EU legislation from the Publications Office, addressed by CELEX number.

The EUR-Lex website answers automated clients with a challenge page, so this
adapter uses the Publications Office content endpoint, which is the service
the EU provides for machine access to the same documents.
"""

from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

from sentinel.models import RawDocument, Section
from sentinel.scrapers.base import SourceAdapter
from sentinel.scrapers.browser import fetch_bytes

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

ENDPOINT = "http://publications.europa.eu/resource/celex/{celex}"
_ARTICLE_ID = re.compile(r"^art_\d+$")


def _flatten_tables(article: Tag, soup: BeautifulSoup) -> None:
    """Replace layout tables (used for lettered points) with plain paragraphs."""
    # Reverse document order visits nested tables before the tables that hold them.
    for table in reversed(article.find_all("table")):
        rows = []
        for row in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td", recursive=False)]
            rows.append(" ".join(cell for cell in cells if cell))
        paragraph = soup.new_tag("p")
        paragraph["class"] = "oj-normal"
        paragraph.string = "\n".join(rows)
        table.replace_with(paragraph)


class EurLexAdapter(SourceAdapter):
    adapter_type = "eurlex"

    def fetch(self) -> list[RawDocument]:
        celex = self.options["celex"]
        content = fetch_bytes(
            ENDPOINT.format(celex=celex),
            headers={"Accept": "application/xhtml+xml", "Accept-Language": "eng"},
        )
        return [
            RawDocument(
                source=self.name,
                key=celex,
                regulation=self.regulation,
                url=self.url,
                title=self.options.get("title", self.regulation),
                content=content,
                content_type="text/html",
            )
        ]

    def parse(self, raw: RawDocument) -> list[Section]:
        soup = BeautifulSoup(raw.content, "lxml")
        sections: list[Section] = []
        for article in soup.find_all("div", id=_ARTICLE_ID):
            heading = article.find("p", class_="oj-ti-art")
            if heading is None:
                continue
            ref = re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
            if not self._included(ref):
                continue
            subtitle = article.find("p", class_="oj-sti-art")
            title = subtitle.get_text(" ", strip=True) if subtitle else ""
            _flatten_tables(article, soup)
            paragraphs = [
                p.get_text(" ", strip=True) for p in article.find_all("p", class_="oj-normal")
            ]
            text = "\n".join(p for p in paragraphs if p)
            if text:
                sections.append(Section(ref=ref, title=title, text=text))
        return sections
