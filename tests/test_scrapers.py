from sentinel.models import RawDocument, SectionKind
from sentinel.scrapers import build_adapter, demo_source, load_sources
from sentinel.scrapers.cppa import find_regulations_pdf, parse_regulations_text
from sentinel.scrapers.edpb import EdpbFeedAdapter, parse_feed
from sentinel.scrapers.eurlex import EurLexAdapter

GDPR_XHTML = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<div class="eli-subdivision" id="art_16">
  <p class="oj-ti-art">Article 16</p>
  <div class="eli-title"><p class="oj-sti-art">Right to rectification</p></div>
  <p class="oj-normal">The data subject shall have the right to rectification.</p>
</div>
<div class="eli-subdivision" id="art_17">
  <p class="oj-ti-art">Article 17</p>
  <div class="eli-title"><p class="oj-sti-art">Right to erasure</p></div>
  <div id="017.001">
    <p class="oj-normal">1.   The controller shall erase personal data where:</p>
    <table><tbody><tr>
      <td><p class="oj-normal">(a)</p></td>
      <td><p class="oj-normal">the data are no longer necessary;</p></td>
    </tr></tbody></table>
    <table><tbody><tr>
      <td><p class="oj-normal">(b)</p></td>
      <td><p class="oj-normal">the data subject withdraws consent.</p></td>
    </tr></tbody></table>
  </div>
</div>
</body></html>"""

CCPA_TEXT = """CPPA
Page 1 of 3
ARTICLE 3.  BUSINESS PRACTICES ......................... 2
§ 7022.  Requests to Delete. ........................................ 2
§ 7026.  Requests to Opt-out of Sale/Sharing. ...................... 3
CPPA
Page 2 of 3
§ 7022.  Requests to Delete.
(a) A business shall comply with a consumer's request to delete
their personal information.
Note: Authority cited: Section 1798.185, Civil Code.
Reference: Section 1798.105, Civil Code.
CPPA
Page 3 of 3
§ 7026.  Requests to Opt-out of Sale/Sharing.
(a) A business that sells personal information shall provide two
or more methods for submitting requests to opt-out.
"""


def _raw(content: bytes, content_type: str) -> RawDocument:
    return RawDocument(
        source="s", key="k", regulation="R", url="u", title="t",
        content=content, content_type=content_type,
    )  # fmt: skip


def test_eurlex_parses_articles_and_joins_lettered_points():
    adapter = EurLexAdapter("gdpr", "GDPR", "u", {"celex": "X"})
    sections = adapter.parse(_raw(GDPR_XHTML, "text/html"))

    assert [(s.ref, s.title) for s in sections] == [
        ("Article 16", "Right to rectification"),
        ("Article 17", "Right to erasure"),
    ]
    assert "(a) the data are no longer necessary;" in sections[1].text
    assert "(b) the data subject withdraws consent." in sections[1].text
    assert "Article 17" not in sections[1].text


def test_include_filter_matches_whole_references_only():
    adapter = EurLexAdapter("gdpr", "GDPR", "u", {"celex": "X", "include": ["Article 1"]})
    assert adapter.parse(_raw(GDPR_XHTML, "text/html")) == []

    adapter = EurLexAdapter("gdpr", "GDPR", "u", {"celex": "X", "include": ["Article 17"]})
    assert [s.ref for s in adapter.parse(_raw(GDPR_XHTML, "text/html"))] == ["Article 17"]


def test_cppa_text_skips_contents_page_furniture_and_authority_notes():
    sections = parse_regulations_text(CCPA_TEXT)

    assert [(number, title) for number, title, _ in sections] == [
        ("7022", "Requests to Delete."),
        ("7026", "Requests to Opt-out of Sale/Sharing."),
    ]
    delete_body = sections[0][2]
    assert delete_body.startswith("(a) A business shall comply")
    assert "Authority cited" not in delete_body
    assert "Reference:" not in delete_body
    assert "Page 3" not in delete_body and "CPPA" not in delete_body


def test_cppa_finds_the_regulations_link_by_its_text():
    html = """
      <a href="/pdf/statute.pdf">California Consumer Privacy Act</a>
      <a href="/regulations/pdf/regs.pdf">CCPA Regulations (Effective
           January 1, 2026)</a>"""
    url = find_regulations_pdf(html, "https://cppa.ca.gov/regulations/", "CCPA Regulations")
    assert url == "https://cppa.ca.gov/regulations/pdf/regs.pdf"
    assert find_regulations_pdf("<a href='/x.pdf'>Other</a>", "https://x/", "CCPA Reg") is None


def test_edpb_feed_items_become_notices():
    feed = b"""<rss><channel><lastBuildDate>today</lastBuildDate>
      <item><title>Guidelines 1/2026 adopted</title><link>https://edpb.example/g1</link>
        <description>&lt;p&gt;New   guidance&lt;/p&gt;</description>
        <pubDate>Mon, 05 Oct 2026</pubDate></item>
      <item><title></title><link>https://edpb.example/empty</link></item>
    </channel></rss>"""
    items = parse_feed(feed)
    assert items == [
        {
            "title": "Guidelines 1/2026 adopted",
            "link": "https://edpb.example/g1",
            "published": "Mon, 05 Oct 2026",
            "summary": "New guidance",
        }
    ]

    import json

    adapter = EdpbFeedAdapter("edpb", "EDPB", "u")
    sections = adapter.parse(_raw(json.dumps(items).encode(), "application/json"))
    assert sections[0].kind == SectionKind.NOTICE
    assert sections[0].title == "Guidelines 1/2026 adopted"


def test_local_adapter_reads_sections_from_markdown():
    adapter = demo_source()
    sections = adapter.parse(adapter.fetch()[0])
    assert [s.ref for s in sections] == [f"Section {n}" for n in range(1, 6)]
    assert sections[0].title == "Storage of credentials"
    assert sections[0].text.startswith("A service that stores user passwords")


def test_configured_sources_build(settings):
    adapters = load_sources(settings.sources_file)
    assert [a.name for a in adapters] == ["gdpr", "ccpa-regulations", "edpb-news"]
    assert [a.name for a in load_sources(settings.sources_file, only=["gdpr"])] == ["gdpr"]


def test_unknown_adapter_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="Unknown adapter"):
        build_adapter({"name": "x", "adapter": "ftp", "regulation": "r", "url": "u"})
