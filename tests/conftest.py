from dataclasses import replace

import pytest

from isbn_bot.config import Settings
from isbn_bot.models import Page, Record
from isbn_bot.state import State


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "data", tmp_path / "reports", request_delay=0, timeout=2)


@pytest.fixture
def state(settings):
    instance = State(settings.db_path)
    yield instance
    instance.close()


@pytest.fixture
def page(settings):
    return Page(123, "Article test", 100, "2026-10-05T08:00:00Z", "2026-10-05T09:00:00Z",
        "Texte conservé.\n<ref>{{Ouvrage |auteur=Jane Exemple |titre=Livre test |éditeur=Éditeur test |année=2004 |isbn=978-0-306-40615-8 }}</ref>\nFin conservée.\n",
        categories=(settings.category,))


@pytest.fixture
def record():
    return Record("bnf", "DEMO-BNF", "https://example.org/notices/demo", "Livre test", ("Jane Exemple",),
                  "Éditeur test", "2004", isbns=("9780306406157",))


class FakeSource:
    name = "bnf"

    def __init__(self, records):
        self.records = records

    def search(self, context, seeds, raw_isbn=""):
        return self.records


class FakeWiki:
    def __init__(self, page, members=None):
        self.current = page
        self.members = members or []
        self.edits = []
        self.logins = 0
        self.error = None

    def category_members(self):
        return self.members

    def page(self, **kwargs):
        return self.current

    def login(self):
        self.logins += 1

    def edit(self, page, new_text, summary):
        self.edits.append((page, new_text, summary))
        if self.error:
            raise self.error
        self.current = replace(page, wikitext=new_text, revision_id=page.revision_id + 1)
        return self.current.revision_id
