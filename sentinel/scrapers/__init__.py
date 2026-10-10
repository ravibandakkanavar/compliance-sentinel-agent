"""Source adapters and the registry that builds them from configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from sentinel.config import PACKAGE_DIR
from sentinel.scrapers.base import SourceAdapter

DEMO_SOURCE_URL = "https://github.com/ravibandakkanavar/compliance-sentinel-agent"


def _adapter_class(adapter: str) -> type[SourceAdapter]:
    # Imported on demand so the local adapter works without a browser installed.
    if adapter == "local":
        from sentinel.scrapers.local import LocalMarkdownAdapter

        return LocalMarkdownAdapter
    if adapter == "eurlex":
        from sentinel.scrapers.eurlex import EurLexAdapter

        return EurLexAdapter
    if adapter == "cppa":
        from sentinel.scrapers.cppa import CppaRegulationsAdapter

        return CppaRegulationsAdapter
    if adapter == "edpb":
        from sentinel.scrapers.edpb import EdpbFeedAdapter

        return EdpbFeedAdapter
    raise ValueError(f"Unknown adapter type: {adapter!r}")


def build_adapter(entry: dict) -> SourceAdapter:
    return _adapter_class(entry["adapter"])(
        name=entry["name"],
        regulation=entry["regulation"],
        url=entry["url"],
        options=entry.get("options"),
    )


def load_sources(sources_file: str, only: list[str] | None = None) -> list[SourceAdapter]:
    config = yaml.safe_load(Path(sources_file).read_text(encoding="utf-8"))
    entries = config.get("sources", [])
    if only:
        entries = [entry for entry in entries if entry["name"] in only]
    return [build_adapter(entry) for entry in entries]


def demo_source(amended: bool = False) -> SourceAdapter:
    """The bundled synthetic regulation; `amended` selects the revised text."""
    version = "v2" if amended else "v1"
    return build_adapter(
        {
            "name": "demo-regulation",
            "adapter": "local",
            "regulation": "Demo Data Handling Regulation",
            "url": f"{DEMO_SOURCE_URL}/blob/main/sentinel/fixtures/demo_regulation_{version}.md",
            "options": {
                "path": str(PACKAGE_DIR / "fixtures" / f"demo_regulation_{version}.md"),
                "key": "demo-regulation",
                "title": "Demo Data Handling Regulation (synthetic)",
            },
        }
    )
