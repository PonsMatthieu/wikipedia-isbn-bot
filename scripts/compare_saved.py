"""Comparaison hors ligne sur Toolforge ; ne sort que des compteurs agrégés.

Usage : python scripts/compare_saved.py /data/project/.../isbn-bot/state.sqlite3
Ne modifie ni la base ni Wikipédia ; réutilise uniquement les notices sauvegardées.
"""
import json
import sqlite3
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from isbn_bot.models import Record
from isbn_bot.parser import extract_fields, replace_field
from isbn_bot.resolver import Analyzer


def compare(path):
    connection = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    result = {"cases": 0, "before_proposals": 0, "after_proposals": 0, "gained": 0,
              "lost": 0, "new_contexts": 0, "wiki_edits": 0, "new_searches": 0}
    blockers = Counter()
    for row in connection.execute("SELECT * FROM findings WHERE status IN ('NEEDS_REVIEW','NO_CANDIDATE')"):
        page, old = json.loads(row["page_json"]), json.loads(row["finding_json"])
        fields = extract_fields(page["wikitext"])
        field = next((f for f in fields if f.locator == row["locator"] and f.raw_value == old["field"]["raw_value"]), None)
        if field is None:
            continue
        records = {}
        for candidate in old["candidates"]:
            for evidence in candidate["evidence"]:
                data = evidence["record"]
                records[json.dumps(data, sort_keys=True)] = Record(**data)
        class SavedSource:
            name = "saved"
            def search(self, *args):
                return list(records.values())
        new = Analyzer([SavedSource()]).analyze(field)
        before = bool(old.get("proposed_value") and row["diff"])
        after = bool(new.proposed_value)
        if after:
            try:
                replace_field(page["wikitext"], field, new.proposed_value)
            except ValueError:
                after = False
        result["cases"] += 1
        result["before_proposals"] += before
        result["after_proposals"] += after
        result["gained"] += after and not before
        result["lost"] += before and not after
        result["new_contexts"] += bool(field.context.title and not old["field"]["context"]["title"])
        blockers.update(new.blockers)
    connection.close()
    return {**result, "blockers_after": dict(blockers), "note": "Notices existantes uniquement ; corrections non validées"}


if __name__ == "__main__":
    print(json.dumps(compare(sys.argv[1]), ensure_ascii=False, indent=2))
