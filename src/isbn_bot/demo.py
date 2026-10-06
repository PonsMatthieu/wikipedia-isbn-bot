"""Démonstration autonome ; toutes les notices et tous les articles sont fictifs."""
from pathlib import Path
from tempfile import TemporaryDirectory

from .config import Settings
from .models import Page, Record
from .pipeline import Pipeline
from .reports import write_reports
from .resolver import Analyzer
from .state import State


class DemoSource:
    name = "bnf"

    def search(self, context, seeds, raw_isbn=""):
        return [Record(
            "bnf", "DEMO-BNF-1", "https://example.org/notices/DEMO-BNF-1",
            "Le Livre Démo", ("Élodie Exemple",), "Éditions Démo", "2004",
            isbns=("9780306406157",),
        )]


def run_demo(output: Path):
    with TemporaryDirectory(prefix="isbn-bot-demo-") as temp:
        settings = Settings(Path(temp), output.resolve())
        state = State(settings.db_path)
        try:
            page = Page(101, "Article de démonstration", 501, "2026-10-05T09:00:00Z", "2026-10-05T09:00:00Z",
                "Un exemple fictif pour tester le parcours.\n<ref>{{Ouvrage |auteur=Élodie Exemple |titre=Le Livre Démo |éditeur=Éditions Démo |année=2004 |isbn=978-0-306-40615-8 }}</ref>\n",
                categories=(settings.category,))
            event_id = state.add_manual_event(page.page_id, page.title)
            pipeline = Pipeline(settings, state, None, Analyzer([DemoSource()]))
            pipeline.analyze_page(page, event_id)
            return write_reports(state, settings.report_dir, demo=True)
        finally:
            state.close()
