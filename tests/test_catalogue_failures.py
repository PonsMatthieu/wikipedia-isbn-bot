import logging

import pytest

from isbn_bot.http import HttpError, Transport
from isbn_bot.models import Context
from isbn_bot.pipeline import Pipeline
from isbn_bot.resolver import Analyzer
from isbn_bot.sources.bnf import BnfSource
from isbn_bot.sources.common import PartialSearchError, safe_source_error
from isbn_bot.sources.sudoc import SudocSource
from conftest import FakeWiki
from test_sources_wiki_http import FIXTURES, Response


def test_http_failure_retains_status_without_secret_url(settings):
    class Session:
        headers = {}
        def request(self, *args, **kwargs):
            return Response({}, status=403)
    with pytest.raises(HttpError) as caught:
        Transport(settings, session=Session()).request("GET", "https://example.org?key=SECRET")
    assert caught.value.status_code == 403
    assert safe_source_error(caught.value) == "HttpError (HTTP 403)"
    assert "SECRET" not in str(caught.value)


def test_error_details_do_not_include_arbitrary_messages_or_kinds():
    assert safe_source_error(HttpError("SECRET", kind="ReadTimeout")) == "HttpError (ReadTimeout)"
    assert safe_source_error(HttpError("SECRET", kind="SECRET")) == "HttpError"
    assert safe_source_error(ValueError("SECRET")) == "ValueError"


def test_bnf_keeps_records_and_continues_after_one_sru_diagnostic():
    class HTTP:
        calls = []
        def text(self, url, params):
            self.calls.append(params["query"])
            if "0306406152" in params["query"]:
                return '<response><diagnostic><uri>info:srw/diagnostic/1/10</uri><details>SECRET</details></diagnostic></response>'
            return (FIXTURES / "bnf.xml").read_text()
    http = HTTP()
    with pytest.raises(PartialSearchError) as caught:
        BnfSource(http).search(Context(title="Livre test"), ["9780306406157"])
    assert len(caught.value.records) == 1
    assert caught.value.errors == ["SRU ISBN: SruDiagnosticError (SRU 10)"]
    assert http.calls[-1].startswith("bib.title")
    assert "SECRET" not in str(caught.value)


def test_bnf_stops_after_transport_failure_without_losing_previous_records():
    class HTTP:
        calls = 0
        def text(self, url, params):
            self.calls += 1
            if self.calls == 1:
                return (FIXTURES / "bnf.xml").read_text()
            raise HttpError("SECRET", status_code=503)
    http = HTTP()
    with pytest.raises(PartialSearchError) as caught:
        BnfSource(http).search(Context(title="Livre test"), ["9780306406157"])
    assert len(caught.value.records) == 1
    assert http.calls == 2
    assert caught.value.errors == ["SRU ISBN: HttpError (HTTP 503)"]


def test_sudoc_empty_result_is_a_success():
    class HTTP:
        def text(self, url, **kwargs):
            return "<sudoc><query><result/></query></sudoc>"
    assert SudocSource(HTTP()).search(Context(), ["9780306406157"]) == []


def test_sudoc_keeps_records_when_another_rdf_notice_is_missing():
    class HTTP:
        calls = []
        def text(self, url, **kwargs):
            self.calls.append(url)
            if "isbn2ppn" in url:
                return "<sudoc><query><result><ppn>000000001</ppn><ppn>000000002</ppn><ppn>000000003</ppn></result></query></sudoc>"
            if url.endswith("000000002.rdf"):
                raise HttpError("SECRET", status_code=404)
            ppn = url.rsplit("/", 1)[-1][:-4]
            return (FIXTURES / "sudoc.rdf").read_text().replace("000000001", ppn)
    with pytest.raises(PartialSearchError) as caught:
        SudocSource(HTTP()).search(Context(), ["9780306406157"])
    assert [r.record_id for r in caught.value.records] == ["000000001", "000000003"]
    assert caught.value.errors == ["RDF: HttpError (HTTP 404)"]


def test_sudoc_http_403_is_visible_and_does_not_retry_other_seeds():
    class HTTP:
        calls = 0
        def text(self, url, **kwargs):
            self.calls += 1
            raise HttpError("SECRET", status_code=403)
    http = HTTP()
    with pytest.raises(PartialSearchError) as caught:
        SudocSource(http).search(Context(), ["9780306406157", "9780743273565"])
    assert caught.value.records == []
    assert caught.value.errors == ["isbn2ppn: HttpError (HTTP 403)"]
    assert http.calls == 1


def test_sudoc_does_not_mistake_html_for_an_empty_catalogue():
    class HTTP:
        def text(self, url, **kwargs):
            return "<html><body>SECRET</body></html>"
    with pytest.raises(PartialSearchError) as caught:
        SudocSource(HTTP()).search(Context(), ["9780306406157"])
    assert caught.value.errors == ["isbn2ppn: ValueError"]
    assert "SECRET" not in str(caught.value)


def test_partial_records_reach_the_report_and_errors_reach_logs(settings, state, page, record, caplog):
    class Partial:
        name = "bnf"
        def search(self, *args):
            raise PartialSearchError([record], ["SRU titre: HttpError (HTTP 503)"])
    members = [{"pageid": page.page_id, "title": page.title, "timestamp": page.timestamp}]
    pipeline = Pipeline(settings, state, FakeWiki(page, members), Analyzer([Partial()]))
    with caplog.at_level(logging.WARNING):
        metrics = pipeline.run(process_existing=True)
    assert metrics["proposals"] == 1 and metrics["failures"] == 0
    finding = state.findings()[0]
    assert "9780306406157" in finding["finding_json"]
    assert "bnf: SRU titre: HttpError (HTTP 503)" in finding["finding_json"]
    assert "page_id=123" in caplog.text and "HTTP 503" in caplog.text


def test_missing_candidates_after_catalogue_failure_still_fail_the_run(settings, state, page, caplog):
    class Broken:
        name = "sudoc"
        def search(self, *args):
            raise HttpError("SECRET", status_code=403)
    members = [{"pageid": page.page_id, "title": page.title, "timestamp": page.timestamp}]
    pipeline = Pipeline(settings, state, FakeWiki(page, members), Analyzer([Broken()]))
    with caplog.at_level(logging.WARNING):
        metrics = pipeline.run(process_existing=True)
    assert metrics["failures"] == 1 and metrics["wiki_edits"] == 0
    assert state.stats()["events"] == {"FAILED": 1}
    assert "sudoc: HttpError (HTTP 403)" in caplog.text
    assert "SECRET" not in caplog.text
