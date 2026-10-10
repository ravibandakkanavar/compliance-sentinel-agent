from sentinel.ingest import ingest_source
from sentinel.ingest.chunking import normalize, split_section, text_hash
from sentinel.models import Section
from sentinel.scrapers import demo_source


def test_normalize_collapses_whitespace_and_typographic_quotes():
    assert normalize("the  ‘right\nto be forgotten’ ") == "the 'right to be forgotten'"


def test_text_hash_ignores_layout_differences():
    assert text_hash("shall erase\npersonal data") == text_hash("shall  erase personal data")
    assert text_hash("shall erase personal data") != text_hash("may erase personal data")


def test_short_section_is_one_chunk():
    section = Section(ref="Article 1", title="Scope", text="A short rule.")
    assert [s.ref for s in split_section(section)] == ["Article 1"]


def test_long_section_splits_on_paragraphs_and_keeps_all_text():
    paragraphs = [f"({i}) " + "obligation text " * 30 for i in range(10)]
    section = Section(ref="§ 7002", title="Limits", text="\n".join(paragraphs))
    parts = split_section(section, max_chars=1200)

    assert len(parts) > 1
    assert parts[0].ref == f"§ 7002 (part 1 of {len(parts)})"
    assert all(len(p.text) <= 1200 for p in parts)
    assert normalize(" ".join(p.text for p in parts)) == normalize(section.text)


def test_single_overlong_paragraph_is_split_without_losing_text():
    text = "A sentence that repeats. " * 200
    parts = split_section(Section(ref="X", text=text), max_chars=1000)
    assert all(len(p.text) <= 1000 for p in parts)
    assert normalize(" ".join(p.text for p in parts)) == normalize(text)


def test_second_scrape_of_unchanged_source_ingests_nothing(store, embedder, settings):
    first = ingest_source(demo_source(), store, embedder, settings.snapshots_dir)
    second = ingest_source(demo_source(), store, embedder, settings.snapshots_dir)

    assert (first.documents_changed, first.chunks_added) == (1, 5)
    assert (second.documents_changed, second.chunks_added, second.chunks_superseded) == (0, 0, 0)
    assert len(store.documents) == 1


def test_amendment_supersedes_only_the_changed_section(store, embedder, settings):
    ingest_source(demo_source(), store, embedder, settings.snapshots_dir)
    store.mark_processed([c.id for c in store.pending_chunks(100)])

    stats = ingest_source(demo_source(amended=True), store, embedder, settings.snapshots_dir)

    # Section 2 was reworded, sections 6 and 7 are new, the other four are untouched.
    assert (stats.chunks_added, stats.chunks_superseded, stats.chunks_unchanged) == (3, 1, 4)
    pending = {c.section_ref for c in store.pending_chunks(100)}
    assert pending == {"Section 2", "Section 6", "Section 7"}
    active = [c for c in store.chunks.values() if not c.superseded]
    assert len(active) == 7


def test_search_excludes_superseded_text(store, embedder, settings):
    ingest_source(demo_source(), store, embedder, settings.snapshots_dir)
    ingest_source(demo_source(amended=True), store, embedder, settings.snapshots_dir)

    query = "email addresses in application logs"
    hits = store.search_chunks(embedder.embed([query])[0], query, k=3)

    assert hits[0].section_ref == "Section 2"
    assert "internal account identifier" in hits[0].text
    assert all(not hit.superseded for hit in hits)
