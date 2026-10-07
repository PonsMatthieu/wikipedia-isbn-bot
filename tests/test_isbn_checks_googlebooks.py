import json
from dataclasses import replace

import pytest

from isbn_bot.cli import main, parser
from isbn_bot.http import HttpError
from isbn_bot.isbn import (candidate_seeds, check_digit10, check_digit13,
    checksum_hypothesis, diagnose_isbn, equivalent_isbns, isbn10, isbn13)
from isbn_bot.models import Context
from isbn_bot.parser import extract_fields
from isbn_bot.pipeline import Pipeline
from isbn_bot.reports import write_reports
from isbn_bot.resolver import Analyzer
from isbn_bot.sources.common import PartialSearchError
from isbn_bot.sources.googlebooks import GoogleBooksSource, parse_volume
from conftest import FakeSource, FakeWiki


@pytest.mark.parametrize("ten,thirteen", [
    ("0306406152", "9780306406157"),
    ("080442957X", "9780804429573"),
    ("2070360024", "9782070360024"),
])
def test_known_equivalent_forms_roundtrip(ten, thirteen):
    assert isbn13(ten) == thirteen
    assert isbn10(thirteen) == ten
    assert set(candidate_seeds(ten)) == {ten, thirteen}
    assert set(candidate_seeds(thirteen)) == {ten, thirteen}


@pytest.mark.parametrize("raw,corrected", [
    ("0306406156", "0306406152"),
    ("0804429570", "080442957X"),
    ("9780306406152", "9780306406157"),
    ("9791234567890", "9791234567896"),
])
def test_only_last_character_changes_in_a_checksum_hypothesis(raw, corrected):
    checks = diagnose_isbn(raw)
    assert checks["checksum_only_hypothesis"] == corrected
    assert checks["expected_check_digit"] == corrected[-1]
    assert checks["supplied_check_digit"] == raw[-1]
    assert corrected[:-1] == raw[:-1]
    assert checks["requires_catalogue_confirmation"]
    assert checks["hypothesis_sources"] == []


def test_979_never_acquires_an_isbn10():
    assert equivalent_isbns("9791234567896") == {"isbn13": "9791234567896"}
    assert candidate_seeds("9791234567890") == ["9791234567896"]
    with pytest.raises(ValueError):
        isbn10("9791234567896")


@pytest.mark.parametrize("raw", ["4006381333931", "9790060115615", "1234567X", "978030640615", "hello"])
def test_non_isbn_identifiers_do_not_get_a_fabricated_check_digit(raw):
    checks = diagnose_isbn(raw)
    assert checks["expected_check_digit"] is None
    assert checks["checksum_only_hypothesis"] is None
    assert checks["search_seeds"] == []


def test_valid_isbn10_is_not_mistaken_for_an_error(record):
    field = extract_fields("{{Ouvrage|titre=Livre test|auteur=Jane Exemple|isbn=0306406152}}")[0]
    finding = Analyzer([FakeSource([record])]).analyze(field)
    assert finding.error_type == "VALID"
    assert finding.proposed_value is None
    assert finding.isbn_checks["equivalents"]["isbn13"] == "9780306406157"
    assert not finding.isbn_checks["requires_catalogue_confirmation"]


def test_check_digit_calculations_reject_invalid_bodies():
    assert check_digit10("080442957") == "X"
    assert check_digit13("978030640615") == "7"
    with pytest.raises(ValueError):
        check_digit10("0306406152")
    with pytest.raises(ValueError):
        check_digit13("979006011561")
    with pytest.raises(ValueError):
        check_digit13("400638133393")
    assert checksum_hypothesis("0306406152") is None


def test_non_ascii_digits_do_not_crash_conversions():
    checks = diagnose_isbn("978٠٣٠٦٤٠٦١٥7")
    assert not checks["valid"]
    assert checks["search_seeds"] == []


def volume(**changes):
    info = {"title": "Livre test", "authors": ["Jane Exemple"],
        "publisher": "Éditeur test", "publishedDate": "2004-03", "language": "fr",
        "industryIdentifiers": [
            {"type": "ISBN_10", "identifier": "0306406152"},
            {"type": "ISBN_13", "identifier": "9780306406157"},
            {"type": "ISBN_13", "identifier": "9780306406158"},
            {"type": "OTHER", "identifier": "9780743273565"},
        ]}
    info.update(changes)
    return {"id": "TEST_VOLUME", "volumeInfo": info}


def test_googlebooks_requires_a_key():
    with pytest.raises(ValueError, match="GOOGLE_BOOKS_API_KEY"):
        GoogleBooksSource(None, " ")


def test_googlebooks_retains_only_valid_explicit_isbn_identifiers():
    record = parse_volume(volume())
    assert record.isbns == ("0306406152", "9780306406157")
    assert record.year == "2004"
    assert record.url == "https://books.google.com/books?id=TEST_VOLUME"
    assert parse_volume({"volumeInfo": {"title": "Missing ID"}}) is None


def test_googlebooks_queries_both_formats_and_keeps_title_search():
    class HTTP:
        calls = []
        def json(self, url, params):
            self.calls.append(params)
            return {"items": [volume()]}
    http = HTTP()
    context = Context(title="Livre test", authors=("Jane Exemple",))
    records = GoogleBooksSource(http, "SECRET").search(context,
        ["9780306406157", "0306406152", "9780743273565", "0743273567"])
    queries = [c["q"] for c in http.calls]
    assert "isbn:9780306406157" in queries and "isbn:0306406152" in queries
    assert len(queries) <= 6 and len(set(queries)) == len(queries)
    assert queries[-1] == 'intitle:"Livre test"'
    assert 'inauthor:"Jane Exemple"' in queries[-2]
    assert all(c["key"] == "SECRET" and c["printType"] == "books" for c in http.calls)
    assert len(records) == 1


def test_googlebooks_keeps_prior_notices_and_redacts_errors():
    class HTTP:
        calls = 0
        def json(self, *args):
            self.calls += 1
            if self.calls == 1:
                return {"items": [volume()]}
            raise HttpError("https://provider/?key=SECRET", status_code=429)
    http = HTTP()
    with pytest.raises(PartialSearchError) as caught:
        GoogleBooksSource(http, "SECRET").search(Context(title="Livre test"), ["0306406152"])
    assert len(caught.value.records) == 1
    assert caught.value.errors == ["Volumes ISBN: HttpError (HTTP 429)"]
    assert http.calls == 2
    assert "SECRET" not in str(caught.value)


def test_googlebooks_error_payload_is_not_reported_as_an_empty_success():
    class HTTP:
        def json(self, *args):
            return {"error": {"message": "SECRET", "code": 403}}
    with pytest.raises(PartialSearchError) as caught:
        GoogleBooksSource(HTTP(), "SECRET").search(Context(), ["9791234567896"])
    assert caught.value.records == []
    assert caught.value.errors == ["Volumes ISBN: ValueError"]
    assert "SECRET" not in str(caught.value)


def test_googlebooks_zero_results_are_normal():
    class HTTP:
        def json(self, *args):
            return {"totalItems": 0}
    assert GoogleBooksSource(HTTP(), "SECRET").search(Context(), ["0306406152"]) == []


def test_googlebooks_can_attest_a_checksum_hypothesis_without_editing(settings, state, page):
    class HTTP:
        def json(self, *args):
            return {"items": [volume()]}
    event_id = state.add_manual_event(page.page_id, page.title)
    analyzer = Analyzer([GoogleBooksSource(HTTP(), "SECRET")])
    finding = analyzer.analyze(extract_fields(page.wikitext)[0])
    assert finding.proposed_value == "9780306406157"
    assert finding.isbn_checks["hypothesis_sources"] == ["googlebooks"]
    assert "clé recalculée" in finding.candidates[0].reasons[-1]
    wiki = FakeWiki(page)
    Pipeline(settings, state, wiki, analyzer).analyze_page(page, event_id)
    json_path, html_path = write_reports(state, settings.report_dir)
    exported = json.loads(json_path.read_text())["cases"][0]["finding"]
    assert exported["isbn_checks"]["expected_check_digit"] == "7"
    assert "Contrôles ISBN" in html_path.read_text()
    assert "googlebooks" in html_path.read_text() and "SECRET" not in html_path.read_text()
    assert wiki.edits == []


def test_checksum_hypothesis_with_no_record_remains_unproven(page):
    finding = Analyzer([FakeSource([])]).analyze(extract_fields(page.wikitext)[0])
    assert finding.isbn_checks["checksum_only_hypothesis"] == "9780306406157"
    assert finding.isbn_checks["hypothesis_sources"] == []
    assert finding.candidates == [] and finding.proposed_value is None


def test_attestation_of_other_edition_does_not_approve_checksum_guess(page, record):
    field = extract_fields(page.wikitext)[0]
    finding = Analyzer([FakeSource([replace(record, year="2021")])]).analyze(field)
    assert finding.isbn_checks["hypothesis_sources"] == ["bnf"]
    assert finding.proposed_value is None
    assert "Année différente" in finding.candidates[0].mismatches


def test_legacy_report_gets_checks_without_rewriting_state(settings, state, page, record):
    event_id = state.add_manual_event(page.page_id, page.title)
    Pipeline(settings, state, FakeWiki(page), Analyzer([FakeSource([record])])).analyze_page(page, event_id)
    row = state.findings()[0]
    old = json.loads(row["finding_json"])
    old.pop("isbn_checks")
    serialized = json.dumps(old)
    with state.db:
        state.db.execute("UPDATE findings SET finding_json=? WHERE id=?", (serialized, row["id"]))
    json_path, _ = write_reports(state, settings.report_dir)
    assert json.loads(json_path.read_text())["cases"][0]["finding"]["isbn_checks"]["expected_check_digit"] == "7"
    assert state.finding(row["id"])["finding_json"] == serialized


def test_cli_check_isbn_needs_neither_network_nor_settings(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Pas de réseau pour ce contrôle")
    monkeypatch.setattr("requests.Session.request", forbidden)
    monkeypatch.setenv("BOT_SOURCES", "invalid")
    assert main(["check-isbn", "0306406156"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["expected_check_digit"] == "2"
    assert result["hypothesis_equivalents"]["isbn13"] == "9780306406157"


def test_cli_exposes_googlebooks_option_and_never_prints_key(monkeypatch, capsys):
    args = parser().parse_args(["run", "--sources", "bnf", "googlebooks"])
    assert args.sources == ["bnf", "googlebooks"]
    monkeypatch.setenv("BOT_SOURCES", "bnf,googlebooks")
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "SECRET")
    assert main(["sources"]) == 0
    output = capsys.readouterr().out
    google = next(item for item in json.loads(output) if item["source"] == "googlebooks")
    assert google["enabled"] and google["configured"] and google["requires_api_key"]
    assert "SECRET" not in output


def test_cli_source_selection_overrides_environment_for_the_actual_run(tmp_path, monkeypatch, capsys):
    chosen = []
    def sources(settings, transport):
        chosen.extend(settings.sources)
        return []
    class EmptyPipeline:
        def __init__(self, *args):
            pass
        def run(self, **kwargs):
            return {"failures": 0, "wiki_edits": 0}
    def forbidden(*args, **kwargs):
        raise AssertionError("Ce test ne doit pas appeler le réseau")
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BOT_SOURCES", "bnf,sudoc,openlibrary")
    monkeypatch.setattr("isbn_bot.cli.build_sources", sources)
    monkeypatch.setattr("isbn_bot.cli.Pipeline", EmptyPipeline)
    monkeypatch.setattr("requests.Session.request", forbidden)
    assert main(["run", "--sources", "googlebooks", "bnf", "googlebooks"]) == 0
    assert chosen == ["googlebooks", "bnf"]
    assert json.loads(capsys.readouterr().out)["wiki_edits"] == 0
