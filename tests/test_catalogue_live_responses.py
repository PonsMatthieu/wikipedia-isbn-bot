"""Régressions des réponses observées sur Toolforge le 6 octobre 2026."""
from types import SimpleNamespace

import pytest

from isbn_bot.http import HttpError, Transport
from isbn_bot.models import Context
from isbn_bot.pipeline import Pipeline
from isbn_bot.resolver import Analyzer
from isbn_bot.sources.bnf import BnfSource, parse_bnf
from isbn_bot.sources.common import PartialSearchError
from isbn_bot.sources.sudoc import SudocSource, missing_isbn_response
from conftest import FakeWiki
from test_sources_wiki_http import FIXTURES


def no_notice(isbn):
    return (f'<sudoc service="isbn2ppn"><error>'
            f"Aucune notice n'est associée à cette valeur {isbn}</error></sudoc>")


class Session:
    def __init__(self, reply):
        self.headers, self.calls, self.reply = {}, [], reply

    def request(self, method, url, **kwargs):
        self.calls.append(url)
        status, text = self.reply(url)
        return SimpleNamespace(status_code=status, text=text, headers={}, encoding=None)


def test_sudoc_no_notice_404_is_not_a_pipeline_failure(settings, state, page):
    session = Session(lambda url: (404, no_notice(url.rsplit('/', 1)[-1])))
    source = SudocSource(Transport(settings, state, session=session, sleep=lambda _: None))
    wiki = FakeWiki(page, [{"pageid": page.page_id, "title": page.title, "timestamp": page.timestamp}])
    metrics = Pipeline(settings, state, wiki, Analyzer([source])).run(process_existing=True)
    assert metrics["analysed"] == 1 and metrics["failures"] == 0
    assert metrics["wiki_edits"] == 0 and wiki.edits == []
    finding = state.findings()[0]
    assert finding["status"] == "NO_CANDIDATE"
    assert '"source_errors": []' in finding["finding_json"]


@pytest.mark.parametrize("body", [
    '<html><body>Not found SECRET</body></html>',
    '<sudoc service="isbn2ppn"><error>Service indisponible SECRET</error></sudoc>',
    no_notice("9780743273565"),
    no_notice("9780306406157").replace('service="isbn2ppn"', 'service="ean2ppn"'),
    no_notice("9780306406157").replace('</sudoc>', '<query/></sudoc>'),
    '<sudoc',
    '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///SECRET">]><sudoc>&x;</sudoc>',
])
def test_unrelated_or_untrusted_404_remains_an_error(settings, body):
    session = Session(lambda url: (404, body))
    source = SudocSource(Transport(settings, session=session, sleep=lambda _: None))
    with pytest.raises(PartialSearchError) as caught:
        source.search(Context(), ["9780306406157"])
    assert caught.value.records == []
    assert caught.value.errors == ["isbn2ppn: HttpError (HTTP 404)"]
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("status", [403, 500])
def test_no_notice_body_does_not_hide_other_http_errors(settings, status):
    session = Session(lambda url: (status, no_notice(url.rsplit('/', 1)[-1])))
    source = SudocSource(Transport(settings, session=session, sleep=lambda _: None))
    with pytest.raises(PartialSearchError) as caught:
        source.search(Context(), ["9780306406157"])
    assert caught.value.errors == [f"isbn2ppn: HttpError (HTTP {status})"]


def test_validated_missing_response_is_cached_without_hiding_generic_404(settings, state):
    isbn = "9780306406157"
    url = "https://www.sudoc.fr/services/isbn2ppn/" + isbn
    session = Session(lambda url: (404, no_notice(isbn)))
    transport = Transport(settings, state, session=session, sleep=lambda _: None)
    validator = lambda body: missing_isbn_response(body, isbn)
    assert transport.text(url, not_found_validator=validator) == no_notice(isbn)
    assert transport.text(url, not_found_validator=validator) == no_notice(isbn)
    assert len(session.calls) == 1
    with pytest.raises(HttpError) as caught:
        transport.text(url)
    assert caught.value.status_code == 404
    assert len(session.calls) == 2


@pytest.mark.parametrize("input_isbn, missing", [
    ("9780306406157", "9780306406157"),
    ("0306406152", "0306406152"),
    ("9780306406157", None),
])
def test_sudoc_checks_equivalent_isbn_and_fetches_each_notice_once(settings, input_isbn, missing):
    def reply(url):
        if url.endswith('.rdf'):
            return 200, (FIXTURES / "sudoc.rdf").read_text()
        isbn = url.rsplit('/', 1)[-1]
        if isbn == missing:
            return 404, no_notice(isbn)
        return 200, '<sudoc service="isbn2ppn"><query><result><ppn>000000001</ppn></result></query></sudoc>'
    session = Session(reply)
    records = SudocSource(Transport(settings, session=session, sleep=lambda _: None)).search(Context(), [input_isbn])
    assert [r.isbns for r in records] == [("9780306406157",)]
    assert len([url for url in session.calls if url.endswith('.rdf')]) == 1
    assert {url.rsplit('/', 1)[-1] for url in session.calls if 'isbn2ppn' in url} == {"9780306406157", "0306406152"}


def test_sudoc_979_search_has_no_isbn10_variant(settings):
    session = Session(lambda url: (404, no_notice(url.rsplit('/', 1)[-1])))
    assert SudocSource(Transport(settings, session=session, sleep=lambda _: None)).search(Context(), ["9791090314030"]) == []
    assert len(session.calls) == 1


def mixed_bnf_response():
    xml = (FIXTURES / "bnf.xml").read_text()
    # Une notice non convertible peut remplacer un record dans la même réponse.
    surrogate = ('<srw:record><srw:recordData><diagnostic xmlns="http://www.loc.gov/zing/srw/diagnostic/">'
                 '<uri>info:srw/diagnostic/1/131</uri><message>erreur de traitement SECRET</message>'
                 '</diagnostic></srw:recordData></srw:record>')
    return xml.replace('</srw:records>', surrogate + '</srw:records>')


def test_bnf_surrogate_diagnostic_keeps_convertible_records():
    with pytest.raises(PartialSearchError) as caught:
        parse_bnf(mixed_bnf_response())
    assert [r.isbns for r in caught.value.records] == [("9780306406157",)]
    assert caught.value.errors == ["SruDiagnosticError (SRU 131)"]
    assert "SECRET" not in str(caught.value)


def test_bnf_surviving_records_and_diagnostic_reach_pipeline(settings, state, page, caplog):
    class HTTP:
        def text(self, url, params):
            return mixed_bnf_response()
    wiki = FakeWiki(page, [{"pageid": page.page_id, "title": page.title, "timestamp": page.timestamp}])
    metrics = Pipeline(settings, state, wiki, Analyzer([BnfSource(HTTP())])).run(process_existing=True)
    # La fixture marque l'ISBN saisi comme publié erroné : un cas est enregistré,
    # sans remplacement. Le compteur proposals ne doit plus compter ce cas.
    assert metrics["failures"] == 0 and metrics["cases"] == 1 and metrics["proposals"] == 0
    assert metrics["wiki_edits"] == 0 and wiki.edits == []
    finding = state.findings()[0]
    assert '"9780306406157"' in finding["finding_json"]
    assert "bnf: SRU ISBN: SruDiagnosticError (SRU 131)" in finding["finding_json"]
    assert "SECRET" not in finding["finding_json"] and "SECRET" not in caplog.text

