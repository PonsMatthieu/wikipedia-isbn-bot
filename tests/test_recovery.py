from dataclasses import replace
import json

import pytest

from isbn_bot.diagnostics import summarize_cases
from isbn_bot.isbn import repair_seeds, valid_isbn
from isbn_bot.matching import normalized_text, title_similarity, author_similarity
from isbn_bot.parser import extract_fields
from isbn_bot.pipeline import Pipeline
from isbn_bot.resolver import Analyzer
from isbn_bot.sources.openlibrary import OpenLibrarySource
from isbn_bot.sources.common import PartialSearchError
from conftest import FakeSource, FakeWiki


def test_unicode_alphabets_are_not_erased():
    assert normalized_text("Философский постгуманизм") == "философскии постгуманизм"
    assert title_similarity("Философский постгуманизм", "Философский постгуманизм") == 1
    assert title_similarity("Философский постгуманизм", "Кабинет некрореализма") < 0.65


@pytest.mark.parametrize("a,b", [("Vion, Robert", "Robert Vion"), ("Pierre-Jakez Hélias", "P. J. Hélias")])
def test_author_order_and_initials(a, b):
    assert author_similarity(a, b) >= 0.9
    assert author_similarity("Robert Vion", "Frédéric François") < 0.5


def test_subtitle_is_not_a_different_work(page, record):
    field = extract_fields(page.wikitext)[0]
    field = replace(field, context=replace(field.context, title="Frontières de sable, frontières de papier"))
    result = Analyzer([FakeSource([replace(record, title=field.context.title + " : histoire des territoires")])]).analyze(field)
    assert result.proposed_value == "9780306406157"


def test_other_notice_with_different_title_does_not_veto_good_evidence(page, record):
    result = Analyzer([FakeSource([record, replace(record, source="sudoc", title="Autre livre")])]).analyze(extract_fields(page.wikitext)[0])
    assert result.proposed_value == "9780306406157"
    assert "Titre différent" in result.candidates[0].warnings
    assert any(e["mismatches"] for e in result.candidates[0].evidence)


def test_real_edition_conflict_still_blocks(page, record):
    result = Analyzer([FakeSource([record, replace(record, source="sudoc", year="2021")])]).analyze(extract_fields(page.wikitext)[0])
    assert result.proposed_value is None
    assert "METADATA_MISMATCH" in result.blockers


def test_competing_editions_are_not_selected_by_sort_order(page, record):
    field = extract_fields(page.wikitext)[0]
    field = replace(field, raw_value="ISBN illisible")
    result = Analyzer([FakeSource([record, replace(record, record_id="OTHER", isbns=("9780743273565",))])]).analyze(field)
    assert result.proposed_value is None
    assert "AMBIGUOUS_EDITION" in result.blockers


def test_bibliography_without_italics():
    text = "* Association Les amis du marégraphe de Marseille : L'invitation au marégraphe de Marseille - brochure de 40 pages - {{ISBN|978-2-95935339-0-1}}, 2025"
    field = extract_fields(text)[0]
    assert field.context.title == "L'invitation au marégraphe de Marseille"
    assert field.context.authors == ("Association Les amis du marégraphe de Marseille",)
    assert field.context.year == "2025"


def test_multiple_translations_use_the_adjacent_title():
    text = "Une phrase ''des témoignages avec beaucoup de texte sur une histoire détaillée qui n'est pas un titre et ne décrit pas précisément le nom de cet ouvrage cité ici'' italienne (*Le nove* {{ISBN|9788811812216}}), néerlandaise (*De negen* {{ISBN|9789402707116}})"
    fields = extract_fields(text)
    assert [f.context.title for f in fields] == ["Le nove", "De negen"]
    assert all(not f.context.publisher for f in fields)


@pytest.mark.parametrize("value", ["97800306406157", "978030640157", "9780306406517", "9781306406157"])
def test_one_typo_generates_catalogue_seeds(value):
    assert "9780306406157" in repair_seeds(value)
    assert all(valid_isbn(s) for s in repair_seeds(value))
    assert len(repair_seeds(value)) <= 32


def test_math_variants_without_a_notice_do_not_propose(page):
    field = replace(extract_fields(page.wikitext)[0], raw_value="97800306406157")
    assert Analyzer([FakeSource([])]).analyze(field).proposed_value is None


def test_openlibrary_title_only_fallback_and_matching_edition():
    class HTTP:
        calls = []
        def json(self, url, params=None):
            self.calls.append((url, params))
            if url.endswith("search.json"):
                if params.get("author"):
                    return {"docs": []}
                return {"docs": [{"key": "/works/OL1W", "title": "Livre test", "editions": {"docs": [{"key": "/books/OL1M"}]}}]}
            if url.endswith("/books/OL1M.json"):
                return {"title": "Livre test", "isbn_13": ["9780306406157"], "publish_date": "1975"}
            if url.endswith("/works/OL1W/editions.json"):
                return {"entries": [{"key": "/books/OL2M", "title": "Livre test", "isbn_13": ["9780743273565"], "publish_date": "1982"}]}
            raise AssertionError(url)
    from isbn_bot.models import Context
    http = HTTP()
    records = OpenLibrarySource(http).search(Context(title="Livre test", authors=("Auteur test",), year="1982"), [])
    assert any(r.year == "1982" and r.isbns == ("9780743273565",) for r in records)
    assert any(p and not p.get("author") for u, p in http.calls if u.endswith("search.json"))


def test_openlibrary_keeps_good_record_after_later_failure():
    class HTTP:
        def json(self, url, params=None):
            if url.endswith("search.json"):
                return {"docs": [{"editions": {"docs": [{"key": "/books/OL1M"}, {"key": "/books/OL2M"}]}}]}
            if url.endswith("/books/OL1M.json"):
                return {"title": "Livre test", "isbn_13": ["9780306406157"]}
            raise RuntimeError("SECRET")
    from isbn_bot.models import Context
    with pytest.raises(PartialSearchError) as caught:
        OpenLibrarySource(HTTP()).search(Context(title="Livre test"), [])
    assert len(caught.value.records) == 1
    assert "SECRET" not in str(caught.value)


def test_reanalysis_archives_history_without_duplicates(settings, state, page, record):
    wiki = FakeWiki(page, [{"pageid": page.page_id, "title": page.title, "timestamp": page.timestamp}])
    pipeline = Pipeline(settings, state, wiki, Analyzer([FakeSource([])]))
    first = pipeline.run(process_existing=True)
    assert first["cases"] == 1 and first["proposals"] == 0
    pipeline.analyzer = Analyzer([FakeSource([record])])
    metrics = pipeline.reanalyze()
    assert metrics["before"]["proposals"] == 0 and metrics["proposals"] == 1
    assert len(state.findings()) == 1
    archived = state.db.execute("SELECT snapshot_json FROM finding_history").fetchall()
    assert len(archived) == 1
    assert json.loads(archived[0][0])["status"] == "NO_CANDIDATE"
    assert wiki.edits == []


@pytest.mark.parametrize("status", ["APPROVED", "REJECTED", "EDITED", "SUBMITTING", "UNKNOWN_SUBMISSION"])
def test_reanalysis_preserves_human_decisions(settings, state, page, record, status):
    wiki = FakeWiki(page, [{"pageid": page.page_id, "title": page.title, "timestamp": page.timestamp}])
    pipeline = Pipeline(settings, state, wiki, Analyzer([FakeSource([record])]))
    pipeline.run(process_existing=True)
    state.set_finding_status(1, status)
    assert pipeline.reanalyze()["analysed"] == 0
    assert state.finding(1)["status"] == status


def test_summary_does_not_count_candidates_as_replacements(settings, state, page, record):
    pipeline = Pipeline(settings, state, FakeWiki(page), Analyzer([FakeSource([replace(record, year="2021")])]))
    event = state.add_manual_event(page.page_id, page.title)
    ids = pipeline.analyze_page(page, event)
    assert pipeline.case_metrics(ids)["proposals"] == 0
    assert pipeline.case_metrics(ids)["candidate_cases"] == 1
