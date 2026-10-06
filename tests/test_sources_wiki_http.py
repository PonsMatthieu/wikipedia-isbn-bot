from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from defusedxml.common import DefusedXmlException

from isbn_bot.http import HttpError, Transport
from isbn_bot.models import Context
from isbn_bot.sources.bnf import parse_bnf
from isbn_bot.sources.openlibrary import OpenLibrarySource
from isbn_bot.sources.sudoc import parse_sudoc
from isbn_bot.wiki import WikiClient, WikiError

FIXTURES = Path(__file__).parent / "fixtures"


def test_bnf_unimarc_and_published_bad_isbn_are_parsed():
    records = parse_bnf((FIXTURES / "bnf.xml").read_text())
    assert len(records) == 1
    assert records[0].isbns == ("9780306406157",)
    assert records[0].invalid_isbns == ("9780306406158",)
    assert records[0].authors == ("Jane Exemple",)


def test_bnf_diagnostic_is_not_an_empty_success():
    with pytest.raises(ValueError):
        parse_bnf('<response><diagnostic><message>Unsupported query</message></diagnostic></response>')


def test_untrusted_xml_entities_are_rejected():
    xml = '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>'
    with pytest.raises(DefusedXmlException):
        parse_bnf(xml)


def test_sudoc_does_not_collect_isbns_from_other_rdf_subjects():
    record = parse_sudoc((FIXTURES / "sudoc.rdf").read_text(), "000000001")
    assert record.isbns == ("9780306406157",)
    assert record.authors == ("Jane Exemple",)


def test_openlibrary_uses_the_edition_not_work_isbn_arrays():
    class HTTP:
        def json(self, url, params=None):
            if url.endswith("search.json"):
                return {"docs": [{"key": "/works/OL1W", "isbn": ["9780743273565"],
                                  "editions": {"docs": [{"key": "/books/OL1M"}]}}]}
            if url.endswith("/books/OL1M.json"):
                return {"title": "Livre test", "isbn_13": ["9780306406157"], "authors": []}
            raise AssertionError(url)
    records = OpenLibrarySource(HTTP()).search(Context(title="Livre test"), [])
    assert records[0].isbns == ("9780306406157",)


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload, self.status_code = payload, status
        self.headers = headers or {}
    def json(self):
        return self.payload


class FakeTransport:
    def __init__(self, replies):
        self.replies, self.calls = iter(replies), []
        self.sleep = lambda _: None
    def request(self, method, url, **kwargs):
        self.calls.append((method, kwargs))
        return Response(next(self.replies))


def test_mediawiki_category_continuation_is_complete(settings):
    http = FakeTransport([
        {"query": {"categorymembers": [{"pageid": 1}]}, "continue": {"continue": "-||", "cmcontinue": "next"}},
        {"query": {"categorymembers": [{"pageid": 2}]}}
    ])
    rows = WikiClient(settings, http).category_members()
    assert [r["pageid"] for r in rows] == [1, 2]
    assert http.calls[1][1]["params"]["cmcontinue"] == "next"
    assert http.calls[0][1]["params"]["cmnamespace"] == "0"


def test_mediawiki_maxlag_on_reads_is_retried(settings):
    http = FakeTransport([{"error": {"code": "maxlag"}}, {"query": {"ok": True}}])
    assert WikiClient(settings, http).api({"action": "query"})["query"]["ok"]
    assert len(http.calls) == 2


def test_mediawiki_edit_uses_revision_and_account_assertions(settings, page):
    from dataclasses import replace
    http = FakeTransport([
        {"query": {"userinfo": {"name": "MesangeISBNBot", "rights": ["bot", "edit"]}}},
        {"query": {"tokens": {"csrftoken": "TEST-CSRF"}}},
        {"edit": {"result": "Success", "newrevid": 101}}
    ])
    settings = replace(settings, bot_account="MesangeISBNBot")
    assert WikiClient(settings, http).edit(page, "new", "summary") == 101
    method, kwargs = http.calls[-1]
    assert method == "POST"
    assert kwargs["retry"] is False
    data = kwargs["data"]
    assert data["assert"] == "bot" and data["assertuser"] == "MesangeISBNBot"
    assert data["baserevid"] == "100" and data["basetimestamp"] == page.timestamp
    assert data["nocreate"] == "1" and data["maxlag"] == "5"


def test_mediawiki_errors_on_writes_are_not_retried(settings):
    http = FakeTransport([{"error": {"code": "maxlag"}}])
    with pytest.raises(WikiError):
        WikiClient(settings, http).api({"action": "edit"}, write=True)
    assert len(http.calls) == 1


def test_http_429_get_retries_but_post_does_not(settings):
    class Session:
        headers = {}
        def __init__(self, replies):
            self.replies, self.calls = iter(replies), 0
        def request(self, *args, **kwargs):
            self.calls += 1
            return next(self.replies)
    session = Session([Response({}, 429), Response({"ok": True})])
    http = Transport(settings, session=session, sleep=lambda _: None)
    assert http.request("GET", "https://example.org").json()["ok"]
    assert session.calls == 2
    session = Session([Response({}, 503)])
    http = Transport(settings, session=session, sleep=lambda _: None)
    with pytest.raises(HttpError):
        http.request("POST", "https://example.org", data={"password": "TEST"})
    assert session.calls == 1


def test_http_error_does_not_expose_secret_url(settings):
    class Session:
        headers = {}
        def request(self, *args, **kwargs):
            raise requests.ConnectionError("https://example.org?key=SECRET")
    http = Transport(settings, session=Session(), sleep=lambda _: None)
    with pytest.raises(HttpError) as caught:
        http.request("GET", "https://example.org")
    assert "SECRET" not in str(caught.value)
