import hashlib
import json
import re
from dataclasses import asdict

import mwparserfromhell

from .http import HttpError
from .isbn import isbn13, normalize_isbn, valid_isbn
from .models import Context, IsbnField, Page
from .parser import make_diff, name, replace_field
from .wiki import WikiError


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def field_from_dict(data: dict) -> IsbnField:
    item = dict(data)
    context = dict(item.pop("context"))
    context["authors"] = tuple(context["authors"])
    return IsbnField(context=Context(**context), **item)


def allows_bot(text: str, bot_name: str) -> bool:
    bot = bot_name.casefold().replace("_", " ")
    for template in mwparserfromhell.parse(text).filter_templates(recursive=True):
        tn = name(str(template.name))
        if tn in {"nobots", "sans bots"}:
            return False
        if tn != "bots":
            continue
        params = {name(str(p.name)): str(p.value).strip().casefold() for p in template.params}
        def names(value):
            return {v.strip().replace("_", " ") for v in value.split(",")}
        if "deny" in params and names(params["deny"]) & {"all", bot}:
            return False
        if "allow" in params and not names(params["allow"]) & {"all", bot}:
            return False
        # Tous les opt-outs sont respectés dans ce premier périmètre.
        if params.get("optout"):
            return False
    return True


def validate_choice(finding: dict, value: str) -> dict:
    if not valid_isbn(value):
        raise ValueError("Le candidat choisi n'est pas un ISBN valide")
    canonical = isbn13(value)
    candidate = next((c for c in finding["candidates"] if c["isbn"] == canonical), None)
    if candidate is None or not candidate.get("evidence"):
        raise ValueError("L'ISBN choisi n'est pas attesté dans cette proposition")
    backed = any(any(valid_isbn(i) and isbn13(i) == canonical for i in e["record"]["isbns"]) for e in candidate["evidence"])
    if not backed:
        raise ValueError("L'ISBN n'apparaît pas dans les notices sauvegardées")
    if candidate["score"] < 0.7 or candidate["mismatches"]:
        raise ValueError("Correspondance d'édition insuffisante : corriger manuellement dans Wikipédia")
    if finding["error_type"] not in {"BAD_CHECKSUM", "EXTRA_TEXT", "UNKNOWN"}:
        raise ValueError("Classe d'erreur exclue de la publication V1")
    if not finding["field"]["editable"]:
        raise ValueError(finding["field"]["restriction"])
    return candidate


def approve_finding(state, finding_id: int, value: str | None, operator: str):
    row = state.finding(finding_id)
    finding = json.loads(row["finding_json"])
    choice = value or finding.get("candidate_isbn")
    if not choice:
        raise ValueError("Aucun candidat proposé ; sélectionner un ISBN attesté avec --isbn")
    candidate = validate_choice(finding, choice)
    choice = candidate["isbn"]
    original = json.loads(row["page_json"])
    updated = replace_field(original["wikitext"], field_from_dict(finding["field"]), choice)
    finding.update(candidate_isbn=choice, proposed_value=choice, status="APPROVED")
    state.approve(finding_id, choice, operator, finding, make_diff(original["wikitext"], updated, original["title"]))


class Editor:
    def __init__(self, settings, state, wiki):
        self.settings, self.state, self.wiki = settings, state, wiki

    def guard(self):
        if self.settings.mode != "REVIEW_ONLY" or not self.settings.write_enabled:
            raise ValueError("Publication désactivée : exiger REVIEW_ONLY et BOT_WRITE_ENABLED=true")
        if not self.settings.community_approved:
            raise ValueError("BOT_COMMUNITY_APPROVED doit être activé après accord communautaire")
        if self.settings.stop_file.exists():
            raise ValueError("Fichier STOP présent : bot arrêté")
        if self.state.get_meta("write_halted"):
            raise ValueError("Écriture arrêtée après incident : voir docs/OPERATIONS.md")
        if self.state.findings(("SUBMITTING", "UNKNOWN_SUBMISSION")):
            self.state.set_meta("write_halted", "unknown-submission")
            raise ValueError("Une soumission précédente reste incertaine ; utiliser reconcile")
        if self.state.edit_errors() >= 5:
            self.state.set_meta("write_halted", "circuit-breaker")
            raise ValueError("Circuit breaker : trop d'échecs parmi les dernières éditions")
        from .state import now
        attempted_today = self.state.db.execute("SELECT count(*) FROM edits WHERE created_at>=?", (now()[:10],)).fetchone()[0]
        if attempted_today >= self.settings.max_edits:
            raise ValueError("Limite quotidienne de soumissions atteinte (BOT_MAX_EDITS)")

    def apply(self, finding_id: int, *, confirmed: bool = False) -> int:
        self.guard()
        if not confirmed:
            raise ValueError("Ajouter --confirm pour soumettre cette proposition approuvée")
        row = self.state.finding(finding_id)
        if row["status"] != "APPROVED":
            raise ValueError("La proposition doit être APPROVED et ne pas avoir été soumise")
        finding = json.loads(row["finding_json"])
        choice = row["selected_isbn"]
        validate_choice(finding, choice)
        original = Page(**json.loads(row["page_json"]))
        try:
            self.wiki.login()
            current = self.wiki.page(page_id=original.page_id)
        except WikiError as exc:
            if exc.code in {"blocked", "wrong-account", "missing-bot-right", "login-failed"}:
                self.state.set_meta("write_halted", exc.code)
            raise
        if current.namespace != 0:
            raise ValueError("Seul l'espace principal est autorisé")
        if current.revision_id != original.revision_id or current.wikitext != original.wikitext:
            self.state.set_finding_status(finding_id, "STALE")
            raise ValueError("La révision a changé ; relancer analyze-page")
        if self.settings.category not in current.categories:
            self.state.set_finding_status(finding_id, "STALE")
            raise ValueError("La page a quitté la catégorie")
        if not allows_bot(current.wikitext, self.settings.bot_account):
            self.state.set_finding_status(finding_id, "OPTED_OUT")
            raise ValueError("L'article refuse les interventions du bot")
        self.guard()  # Contrôle STOP juste avant la soumission.
        updated = replace_field(current.wikitext, field_from_dict(finding["field"]), choice)
        source_names = sorted({e["record"]["source"] for c in finding["candidates"] if c["isbn"] == choice for e in c["evidence"]})
        summary = "Bot : correction d'un ISBN invalide, validation humaine (" + ", ".join(source_names) + ")"
        self.state.begin_edit(finding_id, current.revision_id, content_hash(updated), summary)
        try:
            new_revid = self.wiki.edit(current, updated, summary)
        except WikiError as exc:
            # CAPTCHA/abus/blocage/droits : arrêt persistant immédiat.
            status = "UNKNOWN_SUBMISSION" if exc.code == "edit-not-confirmed" else "EDIT_FAILED"
            self.state.finish_edit(finding_id, status, error_code=exc.code)
            if exc.code != "editconflict":
                self.state.set_meta("write_halted", exc.code)
            self.state.alert("EDIT_ERROR", f"Proposition {finding_id} : {exc.code}")
            raise
        except Exception as exc:
            # La requête peut avoir été acceptée même si la réponse n'est pas arrivée.
            self.state.finish_edit(finding_id, "UNKNOWN_SUBMISSION", error_code=type(exc).__name__)
            self.state.set_meta("write_halted", "unknown-submission")
            self.state.alert("UNKNOWN_SUBMISSION", f"Proposition {finding_id} : résultat à vérifier")
            raise RuntimeError("Résultat de soumission incertain ; ne pas retenter, utiliser reconcile") from None
        self.state.finish_edit(finding_id, "EDITED", new_revid)
        self.state.event_status(row["event_id"], "EDITED")
        # Toutes les autres propositions de cette révision nécessitent une analyse neuve.
        for other in self.state.findings(("APPROVED", "NEEDS_REVIEW")):
            page = json.loads(other["page_json"])
            if page["page_id"] == original.page_id and page["revision_id"] == original.revision_id:
                self.state.set_finding_status(other["id"], "STALE")
        return new_revid
