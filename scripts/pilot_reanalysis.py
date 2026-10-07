"""Réanalyse réseau isolée : copie locale de SQLite, jamais la base source.

À lancer sur le serveur qui détient la base. Le dossier de sortie doit être
nouveau ; les rapports et les preuves restent sur ce serveur.
"""
import argparse
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from isbn_bot.config import Settings
from isbn_bot.http import Transport
from isbn_bot.pipeline import Pipeline
from isbn_bot.resolver import Analyzer
from isbn_bot.sources import build_sources
from isbn_bot.state import State, run_lock
from isbn_bot.wiki import WikiClient


def snapshot_database(source: Path, output: Path) -> Path:
    source = source.resolve(strict=True)
    output = output.resolve()
    # Refuser toute réutilisation de dossier ou écrasement d'une ancienne base.
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    destination = output / "state.sqlite3"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as copied:
            original.backup(copied)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--after-event", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    if args.after_event < 0 or args.limit < 1:
        parser.error("after-event doit être positif ou nul ; limit doit être positif")
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    database = snapshot_database(args.database, args.output)
    settings = replace(
        Settings.from_env(), data_dir=database.parent, report_dir=database.parent / "reports",
        mode="DRY_RUN", write_enabled=False, community_approved=False,
        bot_login="", bot_password="", bot_account="", mail_host="", mail_to="",
    )
    with run_lock(settings.data_dir):
        state = State(settings.db_path)
        try:
            wiki = WikiClient(settings, Transport(settings))
            analyzer = Analyzer(build_sources(settings, Transport(settings, state)))
            metrics = Pipeline(settings, state, wiki, analyzer).reanalyze(
                after_event=args.after_event, limit=args.limit)
            metrics["isolated_copy"] = True
            metrics["archived_versions"] = state.db.execute(
                "SELECT COUNT(*) FROM finding_history").fetchone()[0]
            print(json.dumps(metrics, ensure_ascii=False, indent=2))
            return 1 if metrics["failures"] else 0
        finally:
            state.close()


if __name__ == "__main__":
    raise SystemExit(main())
