"""Contrôle réseau à lancer chez soi/Toolforge. Aucun login, aucune édition."""
from isbn_bot.config import Settings
from isbn_bot.http import Transport
from isbn_bot.models import Context
from isbn_bot.sources.bnf import BnfSource
from isbn_bot.sources.openlibrary import OpenLibrarySource
from isbn_bot.sources.sudoc import SudocSource
from isbn_bot.sources.common import safe_source_error
from isbn_bot.wiki import WikiClient


def main():
    settings = Settings.from_env()
    http = Transport(settings)
    checks = [
        ("MediaWiki", lambda: len(WikiClient(settings, http).category_members())),
        ("BnF", lambda: len(BnfSource(http).search(Context(), ["9782070360024"]))),
        ("Sudoc", lambda: len(SudocSource(http).search(Context(), ["9780306406157"]))),
        ("Open Library", lambda: len(OpenLibrarySource(http).search(Context(), ["9780306406157"]))),
    ]
    failures = 0
    for name, call in checks:
        try:
            print(f"{name}: OK ({call()} résultat(s))")
        except Exception as exc:
            failures += 1
            print(f"{name}: ÉCHEC ({safe_source_error(exc)})")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
