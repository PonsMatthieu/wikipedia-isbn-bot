import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .isbn import classify
from .notifications import send_digest
from .parser import extract_fields, make_diff, replace_field
from .reports import write_reports
from .state import now

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, settings, state, wiki, analyzer):
        self.settings, self.state, self.wiki, self.analyzer = settings, state, wiki, analyzer

    def analyze_page(self, page, event_id: int) -> list[int]:
        if page.namespace != 0:
            self.state.event_status(event_id, "OUT_OF_SCOPE")
            return []
        fields = [f for f in extract_fields(page.wikitext) if classify(f.raw_value) not in {"VALID", "EMPTY"}]
        ids, retry_needed = [], False
        for field in fields:
            if self.settings.stop_file.exists():
                raise RuntimeError("Fichier STOP présent")
            finding = self.analyzer.analyze(field)
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
            ids.append(self.state.save_finding(event_id, asdict(page), finding.to_dict(), diff))
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
        metrics.update(analysed=analysed, failures=failures, proposals=len(ids), wiki_edits=0)
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
