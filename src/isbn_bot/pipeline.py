import logging
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .isbn import classify
from .models import Record
from .notifications import send_digest
from .parser import extract_fields, make_diff, replace_field
from .reports import write_reports
from .state import now

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, settings, state, wiki, analyzer):
        self.settings, self.state, self.wiki, self.analyzer = settings, state, wiki, analyzer

    def saved_records(self, event_id, field):
        row = self.state.db.execute("SELECT * FROM findings WHERE event_id=? AND locator=?",
                                    (event_id, field.locator)).fetchone()
        if row is None:
            return []
        snapshots = [dict(row)] + [json.loads(r[0]) for r in self.state.db.execute(
            "SELECT snapshot_json FROM finding_history WHERE finding_id=? ORDER BY id DESC LIMIT 5", (row["id"],))]
        records = {}
        for snapshot in snapshots:
            finding = json.loads(snapshot["finding_json"])
            if finding["field"]["raw_value"] != field.raw_value:
                continue
            for candidate in finding["candidates"]:
                for evidence in candidate["evidence"]:
                    data = evidence["record"]
                    records[json.dumps(data, sort_keys=True)] = Record(**data)
        return list(records.values())

    def analyze_page(self, page, event_id: int) -> list[int]:
        if page.namespace != 0:
            self.state.event_status(event_id, "OUT_OF_SCOPE")
            return []
        fields = [f for f in extract_fields(page.wikitext) if classify(f.raw_value) not in {"VALID", "EMPTY"}]
        ids, retry_needed = [], False
        for field in fields:
            if self.settings.stop_file.exists():
                raise RuntimeError("Fichier STOP présent")
            finding = self.analyzer.analyze(field, saved_records=self.saved_records(event_id, field))
            if finding.source_errors:
                log.warning("Recherche catalogue partielle pour page_id=%s : %s",
                            page.page_id, "; ".join(finding.source_errors))
            retry_needed |= bool(finding.source_errors and not finding.candidates)
            diff = ""
            if finding.proposed_value:
                try:
                    updated = replace_field(page.wikitext, field, finding.proposed_value)
                    diff = make_diff(page.wikitext, updated, page.title)
                except ValueError as exc:
                    finding.proposed_value = finding.candidate_isbn = None
                    finding.reasons.append(str(exc))
                    finding.blockers.append("MINIMAL_DIFF_FAILED")
            ids.append(self.state.save_finding(event_id, asdict(page), finding.to_dict(), diff))
        self.state.stale_missing_findings(event_id, ids)
        if retry_needed:
            retry_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
            self.state.event_status(event_id, "FAILED", "catalogue-search-incomplete", retry_at)
            self.state.alert("CATALOGUE_FAILED", f"Page {page.page_id} : recherche sans candidat après erreur de catalogue")
        else:
            self.state.event_status(event_id, "NEEDS_REVIEW" if ids else "NO_SUPPORTED_FINDING")
        return ids

    def run(self, *, process_existing: bool = False) -> dict:
        if self.settings.stop_file.exists():
            raise RuntimeError("Fichier STOP présent")
        # On n'écrit le snapshot qu'après réussite de toutes les pages de continuation.
        metrics = self.state.sync_memberships(self.wiki.category_members(), process_existing)
        if process_existing:
            metrics["queued_existing"] = self.state.queue_existing(self.settings.max_pages)
        analysed, failures, ids = 0, 0, []
        for event in self.state.pending_events(self.settings.max_pages):
            if self.settings.stop_file.exists():
                break
            self.state.event_status(event["id"], "ANALYSING")
            try:
                page = self.wiki.page(page_id=event["page_id"])
                if self.settings.category not in page.categories:
                    self.state.event_status(event["id"], "RESOLVED_EXTERNALLY")
                    continue
                ids.extend(self.analyze_page(page, event["id"]))
                analysed += 1
                if self.state.db.execute("SELECT status FROM events WHERE id=?", (event["id"],)).fetchone()[0] == "FAILED":
                    failures += 1
            except Exception as exc:
                failures += 1
                next_retry = (datetime.now(timezone.utc) + timedelta(hours=2 ** min(event["attempts"], 3))).isoformat(timespec="seconds")
                self.state.event_status(event["id"], "FAILED", type(exc).__name__, next_retry)
                self.state.alert("ANALYSIS_FAILED", f"Page {event['page_id']} : {type(exc).__name__}")
                log.error("Analyse échouée pour page_id=%s (%s)", event["page_id"], type(exc).__name__)
        metrics.update(analysed=analysed, failures=failures, wiki_edits=0, **self.case_metrics(ids))
        write_reports(self.state, self.settings.report_dir)
        try:
            metrics["email_sent"] = send_digest(self.settings, self.state, ids, metrics)
        except Exception as exc:
            metrics["email_sent"] = False
            self.state.alert("EMAIL_FAILED", type(exc).__name__)
            log.error("Notification email échouée (%s)", type(exc).__name__)
        if failures == 0:
            self.state.set_meta("last_success", now())
        log.info("Fin de run : %s", metrics)
        return metrics

    def case_metrics(self, ids: list[int]) -> dict:
        rows = [self.state.finding(i) for i in dict.fromkeys(ids)]
        proposed = [r for r in rows if json.loads(r["finding_json"]).get("proposed_value") and r["diff"]
                    and r["status"] in {"NEEDS_REVIEW", "APPROVED"}]
        return {"cases": len(rows), "proposals": len(proposed),
                "proposal_pages": len({r["event_id"] for r in proposed}),
                "candidate_cases": sum(bool(json.loads(r["finding_json"])["candidates"]) for r in rows),
                "partial_search_cases": sum(bool(json.loads(r["finding_json"])["source_errors"]) for r in rows)}

    def reanalyze(self, *, after_event: int = 0, limit: int | None = None) -> dict:
        """Rejouer les événements existants avec une pagination explicite."""
        if self.settings.stop_file.exists():
            raise RuntimeError("Fichier STOP présent")
        events = self.state.review_events(after_event, limit or self.settings.max_pages)
        before_ids = [r[0] for e in events for r in self.state.db.execute(
            "SELECT id FROM findings WHERE event_id=? AND status IN ('NEEDS_REVIEW','NO_CANDIDATE')", (e["id"],))]
        before = self.case_metrics(before_ids)
        ids, failures, analysed = [], 0, 0
        for event in events:
            if self.settings.stop_file.exists():
                break
            try:
                page = self.wiki.page(page_id=event["page_id"])
                if self.settings.category not in page.categories:
                    self.state.event_status(event["id"], "RESOLVED_EXTERNALLY")
                    self.state.stale_missing_findings(event["id"], [])
                    continue
                ids.extend(self.analyze_page(page, event["id"]))
                analysed += 1
                failures += self.state.db.execute("SELECT status FROM events WHERE id=?", (event["id"],)).fetchone()[0] == "FAILED"
            except Exception as exc:
                failures += 1
                self.state.alert("REANALYSIS_FAILED", f"Page {event['page_id']} : {type(exc).__name__}")
        metrics = {"reanalyzed": True, "analysed": analysed, "failures": failures,
                   "before": before, **self.case_metrics(ids), "wiki_edits": 0,
                   "next_after_event": events[-1]["id"] if events else after_event}
        write_reports(self.state, self.settings.report_dir)
        log.info("Fin de réanalyse : %s", metrics)
        return metrics

