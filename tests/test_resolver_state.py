from dataclasses import replace

import pytest

from isbn_bot.editor import approve_finding, validate_choice
from isbn_bot.parser import extract_fields
from isbn_bot.pipeline import Pipeline
from isbn_bot.resolver import Analyzer
from isbn_bot.state import run_lock
from conftest import FakeSource, FakeWiki


def test_checksum_guess_without_a_record_is_rejected(page):
    result = Analyzer([FakeSource([])]).analyze(extract_fields(page.wikitext)[0])
    assert result.candidates == []
    assert result.proposed_value is None
    assert result.status == "NO_CANDIDATE"


def test_same_work_different_year_requires_manual_intervention(page, record):
    result = Analyzer([FakeSource([replace(record, year="2021")])]).analyze(extract_fields(page.wikitext)[0])
    assert result.proposed_value is None
    assert "Année différente" in result.candidates[0].mismatches
    with pytest.raises(ValueError):
        validate_choice(result.to_dict(), "9780306406157")


def test_missing_title_prevents_high_score(record):
    field = extract_fields("{{ISBN|9780306406158}}")[0]
    result = Analyzer([FakeSource([record])]).analyze(field)
    assert result.candidates[0].score <= 0.35
    assert result.proposed_value is None


def test_conflicting_catalogue_metadata_is_not_ignored(page, record):
    result = Analyzer([FakeSource([record, replace(record, source="sudoc", year="2021")])]).analyze(extract_fields(page.wikitext)[0])
    assert result.proposed_value is None
    assert "Année différente" in result.candidates[0].mismatches


def test_wrong_language_is_excluded(page, record):
    field = extract_fields(page.wikitext)[0]
    field = replace(field, context=replace(field.context, language="fr"))
    result = Analyzer([FakeSource([replace(record, language="eng")])]).analyze(field)
    assert result.proposed_value is None


def test_published_invalid_identifier_is_preserved(page, record):
    field = extract_fields(page.wikitext)[0]
    result = Analyzer([FakeSource([replace(record, invalid_isbns=("9780306406158",))])]).analyze(field)
    assert result.error_type == "PUBLISHED_BAD_ISBN"
    assert result.proposed_value is None


def test_isbn10_and_13_same_edition_group_together(page, record):
    result = Analyzer([FakeSource([replace(record, isbns=("0306406152", "9780306406157"))])]).analyze(extract_fields(page.wikitext)[0])
    assert len(result.candidates) == 1


def test_source_failure_does_not_invent_an_isbn(page):
    class Broken:
        name = "bnf"
        def search(self, *args):
            raise RuntimeError("secret-key-never-print")
    result = Analyzer([Broken()]).analyze(extract_fields(page.wikitext)[0])
    assert result.candidates == []
    assert result.source_errors == ["bnf: RuntimeError"]
    assert "secret-key" not in str(result.to_dict())


def test_first_run_baselines_existing_articles(settings, state, page, record):
    wiki = FakeWiki(page, [{"pageid": 123, "title": page.title, "timestamp": "2026-10-01T00:00:00Z"}])
    pipeline = Pipeline(settings, state, wiki, Analyzer([FakeSource([record])]))
    metrics = pipeline.run()
    assert metrics["baseline"] and metrics["analysed"] == 0
    assert state.stats()["events"] == {"BASELINE": 1}
    assert wiki.edits == []


def test_new_article_is_processed_only_once(settings, state, page, record):
    wiki = FakeWiki(page)
    pipeline = Pipeline(settings, state, wiki, Analyzer([FakeSource([record])]))
    pipeline.run()
    wiki.members = [{"pageid": 123, "title": page.title, "timestamp": "2026-10-05T00:00:00Z"}]
    assert pipeline.run()["proposals"] == 1
    assert pipeline.run()["proposals"] == 0
    assert len(state.findings()) == 1
    assert wiki.edits == []


def test_reentry_is_a_distinct_event_and_stales_previous_proposal(settings, state, page, record):
    member = {"pageid": 123, "title": page.title, "timestamp": "2026-10-01T00:00:00Z"}
    state.sync_memberships([member], process_existing=True)
    Pipeline(settings, state, FakeWiki(page), Analyzer([FakeSource([record])])).analyze_page(page, 1)
    state.sync_memberships([])
    state.sync_memberships([dict(member, timestamp="2026-10-05T00:00:00Z")])
    assert state.finding(1)["status"] == "STALE"
    assert len(state.db.execute("SELECT * FROM events").fetchall()) == 2


def test_category_timestamp_change_stales_previous_proposal(settings, state, page, record):
    member = {"pageid": 123, "title": page.title, "timestamp": "2026-10-01T00:00:00Z"}
    state.sync_memberships([member], process_existing=True)
    Pipeline(settings, state, FakeWiki(page), Analyzer([FakeSource([record])])).analyze_page(page, 1)
    state.sync_memberships([dict(member, timestamp="2026-10-05T00:00:00Z")])
    assert state.finding(1)["status"] == "STALE"


def test_review_cannot_approve_unattested_value(settings, state, page, record):
    eid = state.add_manual_event(page.page_id, page.title)
    pipeline = Pipeline(settings, state, FakeWiki(page), Analyzer([FakeSource([record])]))
    fid = pipeline.analyze_page(page, eid)[0]
    with pytest.raises(ValueError):
        approve_finding(state, fid, "9780743273565", settings.operator)
    assert state.finding(fid)["status"] == "NEEDS_REVIEW"


def test_another_operation_cannot_take_the_run_lock(settings):
    with run_lock(settings.data_dir):
        with pytest.raises(RuntimeError):
            with run_lock(settings.data_dir):
                pass
    assert not (settings.data_dir / "run.lock").exists()


def test_catalogue_failure_is_queued_for_a_future_retry(settings, state, page):
    class Broken:
        name = "bnf"
        def search(self, *args):
            raise RuntimeError("API unavailable")
    event_id = state.add_manual_event(page.page_id, page.title)
    pipeline = Pipeline(settings, state, FakeWiki(page), Analyzer([Broken()]))
    pipeline.analyze_page(page, event_id)
    row = state.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    assert row["status"] == "FAILED" and row["next_retry"]
