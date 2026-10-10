"""Turn parsed regulation sections into chunks sized for retrieval and citation."""

from __future__ import annotations

import hashlib
import re

from sentinel.models import Section

MAX_CHUNK_CHARS = 2400


def normalize(text: str) -> str:
    """Collapse whitespace and unify quote characters, for hashing and quote matching."""
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_section(section: Section, max_chars: int = MAX_CHUNK_CHARS) -> list[Section]:
    """Split an over-long section on paragraph boundaries.

    Each part keeps the parent reference with a part suffix, so a citation
    still names the article and the quoted text sits inside one chunk.
    """
    text = section.text.strip()
    if len(text) <= max_chars:
        return [section.model_copy(update={"text": text})]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    parts: list[str] = []
    current = ""
    for paragraph in paragraphs:
        while len(paragraph) > max_chars:
            cut = paragraph.rfind(". ", 0, max_chars)
            cut = cut + 1 if cut > max_chars // 2 else max_chars
            head, paragraph = paragraph[:cut].strip(), paragraph[cut:].strip()
            if current:
                parts.append(current)
                current = ""
            parts.append(head)
        if current and len(current) + len(paragraph) + 1 > max_chars:
            parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n{paragraph}" if current else paragraph
    if current:
        parts.append(current)

    return [
        section.model_copy(update={"ref": f"{section.ref} (part {i} of {len(parts)})", "text": part})
        for i, part in enumerate(parts, start=1)
    ]


def chunk_sections(sections: list[Section]) -> list[Section]:
    chunks: list[Section] = []
    for section in sections:
        if section.text.strip():
            chunks.extend(split_section(section))
    return chunks
