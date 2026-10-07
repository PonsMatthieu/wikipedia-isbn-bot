import argparse
import json
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from .config import AVAILABLE_SOURCES, Settings
from .demo import run_demo
from .editor import Editor, approve_finding, content_hash
from .http import Transport
from .isbn import diagnose_isbn
from .notifications import send_digest
from .pipeline import Pipeline
from .reports import write_reports
from .resolver import Analyzer
from .sources import build_sources
from .state import State, run_lock
from .wiki import WikiClient


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bot ISBN Wikipédia : analyse et corrections supervisées")
    p.add_argument("--env", type=Path, help="Fichier .env explicite (variables injectées prioritaires)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialiser la base sans appel réseau")
    run = sub.add_parser("run", help="Veille et analyse ; ne publie jamais")
    run.add_argument("--process-existing", action="store_true", help="Traiter aussi un lot de pages de la liste initiale")
    page = sub.add_parser("analyze-page", help="Analyser un article précis sans édition")
    page.add_argument("title")
    for command in (run, page):
        command.add_argument("--sources", nargs="+", choices=AVAILABLE_SOURCES,
                             help="Catalogues à interroger ; remplace BOT_SOURCES pour cette analyse")
    check = sub.add_parser("check-isbn", help="Vérifier clé et conversions ISBN-10/13, hors ligne")
    check.add_argument("value")
    sub.add_parser("sources", help="Afficher les catalogues disponibles et leur configuration, sans clé secrète")
    listing = sub.add_parser("list", help="Liste des propositions")
    listing.add_argument("--status", default="")
    show = sub.add_parser("show", help="Afficher preuves et diff")
    show.add_argument("id", type=int)
    approve = sub.add_parser("approve", help="Approuver une proposition dans la base ; ne publie pas")
    approve.add_argument("id", type=int)
    approve.add_argument("--isbn", help="Choisir un autre candidat attesté")
    reject = sub.add_parser("reject", help="Rejeter une proposition")
    reject.add_argument("id", type=int)
    apply = sub.add_parser("apply", help="Publier UNE proposition déjà approuvée")
    apply.add_argument("id", type=int)
    apply.add_argument("--confirm", action="store_true")
    reconcile = sub.add_parser("reconcile", help="Vérifier une soumission dont le résultat est incertain")
    reconcile.add_argument("id", type=int)
    reconcile.add_argument("--accept-match", action="store_true", help="Clore seulement si le texte actuel correspond exactement")
    sub.add_parser("export", help="Régénérer le rapport JSON et HTML")
    sub.add_parser("status", help="Statistiques locales")
    sub.add_parser("stop", help="Créer le fichier STOP")
    resume = sub.add_parser("resume", help="Reprendre après traitement d'un incident")
    resume.add_argument("--confirm", action="store_true")
    sub.add_parser("notify-test", help="Envoyer un mail de test avec la configuration SMTP")
    demo = sub.add_parser("demo", help="Parcours fictif complet, hors ligne, sans identifiants")
    demo.add_argument("--output", type=Path, default=Path("reports/demo"))
    return p


def print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.umask(0o077)
    if args.command == "check-isbn":
        print_json(diagnose_isbn(args.value))
        return 0
    if args.command == "demo":
        json_path, html_path = run_demo(args.output)
        print_json({"demo": True, "report_json": str(json_path), "report_html": str(html_path), "wiki_edits": 0})
        return 0
    try:
        settings = Settings.from_env(args.env)
        if getattr(args, "sources", None):
            settings = replace(settings, sources=tuple(dict.fromkeys(args.sources)))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.command == "sources":
        print_json([{"source": name, "enabled": name in settings.sources,
                     "requires_api_key": name == "googlebooks",
                     "configured": name != "googlebooks" or bool(settings.google_key.strip())}
                    for name in AVAILABLE_SOURCES])
        return 0
    state = None
    try:
        with run_lock(settings.data_dir):
            state = State(settings.db_path)
            if args.command == "init":
                print_json({"database": str(settings.db_path), "mode": settings.mode, "wiki_edits": 0})
            elif args.command == "status":
                print_json({**state.stats(), "stop_file": settings.stop_file.exists(), "mode": settings.mode})
            elif args.command == "list":
                rows = state.findings(tuple(args.status.split(",")) if args.status else ())
                print_json([{"id": r["id"], "status": r["status"], "title": json.loads(r["page_json"])["title"],
                             "candidate_isbn": json.loads(r["finding_json"])["candidate_isbn"]} for r in rows])
            elif args.command == "show":
                row = state.finding(args.id)
                row["page"] = json.loads(row.pop("page_json"))
                row["finding"] = json.loads(row.pop("finding_json"))
                print_json(row)
            elif args.command == "approve":
                approve_finding(state, args.id, args.isbn, settings.operator)
                write_reports(state, settings.report_dir)
                print_json({"id": args.id, "status": "APPROVED", "wiki_edits": 0})
            elif args.command == "reject":
                row = state.finding(args.id)
                if row["status"] not in {"NEEDS_REVIEW", "NO_CANDIDATE", "APPROVED"}:
                    raise ValueError("Cette proposition n'est pas rejetable")
                state.set_finding_status(args.id, "REJECTED")
                write_reports(state, settings.report_dir)
                print_json({"id": args.id, "status": "REJECTED"})
            elif args.command == "export":
                print_json({"files": [str(p) for p in write_reports(state, settings.report_dir)]})
            elif args.command == "stop":
                settings.stop_file.write_text("Arrêt demandé par l'opérateur\n", encoding="utf-8")
                print_json({"stopped": True})
            elif args.command == "resume":
                if not args.confirm:
                    raise ValueError("Vérifier l'incident puis ajouter --confirm")
                if state.findings(("SUBMITTING", "UNKNOWN_SUBMISSION")):
                    raise ValueError("Réconcilier les soumissions incertaines avant de reprendre")
                settings.stop_file.unlink(missing_ok=True)
                with state.db:
                    state.db.execute("DELETE FROM meta WHERE key='write_halted'")
                print_json({"stopped": False, "writes_enabled": settings.write_enabled})
            elif args.command == "notify-test":
                if not settings.mail_host or not settings.mail_to:
                    raise ValueError("Configurer MAIL_HOST et MAIL_TO")
                state.alert("SMTP_TEST", "Test de notification du bot ISBN")
                sent = send_digest(settings, state, [], {"test": True, "wiki_edits": 0})
                print_json({"email_sent": sent})
            else:
                # Sessions distinctes : les cookies Wikipédia ne vont pas aux catalogues.
                wiki = WikiClient(settings, Transport(settings))
                if args.command == "apply":
                    revid = Editor(settings, state, wiki).apply(args.id, confirmed=args.confirm)
                    write_reports(state, settings.report_dir)
                    print_json({"id": args.id, "status": "EDITED", "newrevid": revid})
                elif args.command == "reconcile":
                    row = state.db.execute("SELECT * FROM edits WHERE finding_id=?", (args.id,)).fetchone()
                    if row is None or row["state"] not in {"SUBMITTING", "UNKNOWN_SUBMISSION"}:
                        raise ValueError("Aucune soumission incertaine pour cette proposition")
                    page_id = json.loads(state.finding(args.id)["page_json"])["page_id"]
                    current = wiki.page(page_id=page_id)
                    match = content_hash(current.wikitext) == row["new_hash"] and current.revision_id != row["old_revid"]
                    if args.accept_match:
                        if not match:
                            raise ValueError("Texte différent : inspection manuelle de l'historique requise")
                        state.finish_edit(args.id, "RECONCILED", current.revision_id)
                        write_reports(state, settings.report_dir)
                    print_json({"id": args.id, "text_matches": match, "current_revid": current.revision_id,
                                "closed": bool(args.accept_match), "note": "Une égalité de texte ne prouve pas l'identité de son auteur"})
                else:
                    sources = build_sources(settings, Transport(settings, state))
                    pipeline = Pipeline(settings, state, wiki, Analyzer(sources))
                    if args.command == "run":
                        metrics = pipeline.run(process_existing=args.process_existing)
                        print_json(metrics)
                        return 1 if metrics["failures"] else 0
                    if args.command == "analyze-page":
                        if settings.stop_file.exists():
                            raise ValueError("Fichier STOP présent")
                        page = wiki.page(title=args.title)
                        event_id = state.add_manual_event(page.page_id, page.title)
                        ids = pipeline.analyze_page(page, event_id)
                        write_reports(state, settings.report_dir)
                        print_json({"finding_ids": ids, "wiki_edits": 0})
        return 0
    except Exception as exc:
        # Messages locaux contrôlés ; pas d'exception HTTP brute, ni d'URL/secrets.
        safe = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        logging.error("%s", safe)
        if state is not None:
            try:
                state.alert("COMMAND_FAILED", args.command + ": " + type(exc).__name__)
                send_digest(settings, state, [], {"command": args.command, "failed": True})
            except Exception:
                logging.error("Notification d'incident non envoyée")
        return 1
    finally:
        if state is not None:
            state.close()
