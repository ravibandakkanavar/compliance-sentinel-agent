"""European Data Protection Board news feed.

Feed items are notices: they tell the reader that guidance was published and
appear in the report's change log, but they are not audited as rules.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET

from sentinel.models import RawDocument, Section, SectionKind
from sentinel.scrapers.base import SourceAdapter
from sentinel.scrapers.browser import fetch_bytes

_TAGS = re.compile(r"<[^>]+>")


def parse_feed(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        description = _TAGS.sub(" ", item.findtext("description") or "")
        items.append(
            {
                "title": title,
                "link": link,
                "published": (item.findtext("pubDate") or "").strip(),
                "summary": re.sub(r"\s+", " ", description).strip()[:600],
            }
        )
    return items


class EdpbFeedAdapter(SourceAdapter):
    adapter_type = "edpb"

    def fetch(self) -> list[RawDocument]:
        items = parse_feed(fetch_bytes(self.url))
        if not items:
            return []
        # The canonical content is the item list, so feed metadata such as the
        # build timestamp does not register as a change.
        content = json.dumps(items, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return [
            RawDocument(
                source=self.name,
                key="feed",
                regulation=self.regulation,
                url=self.url,
                title=self.options.get("title", self.regulation),
                content=content,
                content_type="application/json",
            )
        ]

    def parse(self, raw: RawDocument) -> list[Section]:
        sections = []
        for item in json.loads(raw.content):
            ref = hashlib.sha1(item["link"].encode()).hexdigest()[:12]
            text = f"{item['summary']}\nPublished: {item['published']}\nLink: {item['link']}"
            sections.append(
                Section(ref=ref, title=item["title"], text=text.strip(), kind=SectionKind.NOTICE)
            )
        return sections
