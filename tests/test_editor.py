from dataclasses import replace

import pytest

from isbn_bot.editor import Editor, allows_bot, approve_finding
from isbn_bot.http import HttpError
from isbn_bot.pipeline import Pipeline
from isbn_bot.resolver import Analyzer
from isbn_bot.wiki import WikiError
from conftest import FakeSource, FakeWiki


def prepared(settings, state, page, record):
    wiki = FakeWiki(page)
    eid = state.add_manual_event(page.page_id, page.title)
    fid = Pipeline(settings, state, wiki, Analyzer([FakeSource([record])])).analyze_page(page, eid)[0]
    approve_finding(state, fid, None, settings.operator)
    live = replace(settings, mode="REVIEW_ONLY", write_enabled=True, community_approved=True, bot_account="MesangeISBNBot")
    return Editor(live, state, wiki), wiki, fid


def test_dry_run_never_logs_in_or_edits(settings, state, page, record):
    editor, wiki, fid = prepared(settings, state, page, record)
    editor.settings = settings
    with pytest.raises(ValueError):
        editor.apply(fid, confirmed=True)
    assert wiki.logins == 0 and wiki.edits == []


def test_community_gate_and_confirmation_are_required(settings, state, page, record):
    editor, wiki, fid = prepared(settings, state, page, record)
    with pytest.raises(ValueError):
        editor.apply(fid)
    editor.settings = replace(editor.settings, community_approved=False)
    with pytest.raises(ValueError):
        editor.apply(fid, confirmed=True)
    assert wiki.edits == []


def test_minimal_approved_edit_is_persisted_once(settings, state, page, record):
    editor, wiki, fid = prepared(settings, state, page, record)
    assert editor.apply(fid, confirmed=True) == 101
    assert wiki.edits[0][1] == page.wikitext.replace("978-0-306-40615-8", "9780306406157")
    assert state.finding(fid)["status"] == "EDITED"
    with pytest.raises(ValueError):
        editor.apply(fid, confirmed=True)
    assert len(wiki.edits) == 1


def test_changed_revision_is_never_overwritten(settings, state, page, record):
    editor, wiki, fid = prepared(settings, state, page, record)
    wiki.current = replace(page, revision_id=101)
    with pytest.raises(ValueError, match="révision"):
        editor.apply(fid, confirmed=True)
    assert state.finding(fid)["status"] == "STALE"
    assert wiki.edits == []


def test_page_outside_category_is_never_edited(settings, state, page, record):
    editor, wiki, fid = prepared(settings, state, page, record)
    wiki.current = replace(page, categories=())
    with pytest.raises(ValueError, match="catégorie"):
        editor.apply(fid, confirmed=True)
    assert wiki.edits == []


def test_stop_file_prevents_authentication(settings, state, page, record):
    editor, wiki, fid = prepared(settings, state, page, record)
    editor.settings.stop_file.write_text("STOP")
    with pytest.raises(ValueError, match="STOP"):
        editor.apply(fid, confirmed=True)
    assert wiki.logins == 0


@pytest.mark.parametrize("template", ["{{nobots}}", "{{bots|deny=all}}", "{{bots|allow=AnotherBot}}", "{{bots|deny=MesangeISBNBot}}", "{{bots|optout=all}}"])
def test_bot_optouts_are_respected(template):
    assert not allows_bot(template, "MesangeISBNBot")


def test_permission_error_halts_further_writes(settings, state, page, record):
    editor, wiki, fid = prepared(settings, state, page, record)
    wiki.error = WikiError("blocked")
    with pytest.raises(WikiError):
        editor.apply(fid, confirmed=True)
    assert state.get_meta("write_halted") == "blocked"
    assert state.finding(fid)["status"] == "EDIT_FAILED"


def test_lost_response_is_not_retried(settings, state, page, record):
    editor, wiki, fid = prepared(settings, state, page, record)
    wiki.error = HttpError("Timeout")
    with pytest.raises(RuntimeError, match="incertain"):
        editor.apply(fid, confirmed=True)
    assert state.finding(fid)["status"] == "UNKNOWN_SUBMISSION"
    with pytest.raises(ValueError):
        editor.apply(fid, confirmed=True)
    assert len(wiki.edits) == 1


def test_no_result_in_edit_response_is_treated_as_uncertain(settings, state, page, record):
    editor, wiki, fid = prepared(settings, state, page, record)
    wiki.error = WikiError("edit-not-confirmed")
    with pytest.raises(WikiError):
        editor.apply(fid, confirmed=True)
    assert state.finding(fid)["status"] == "UNKNOWN_SUBMISSION"


def test_unfinished_submission_after_crash_halts_new_writes(settings, state, page, record):
    editor, wiki, fid = prepared(settings, state, page, record)
    state.begin_edit(fid, page.revision_id, "pending-hash", "summary")
    with pytest.raises(ValueError, match="incertaine"):
        editor.apply(fid, confirmed=True)
    assert state.get_meta("write_halted") == "unknown-submission"
    assert wiki.logins == 0
