from urllib.parse import quote

from ..models import Record
from .common import valid_identifiers, year


class OpenLibrarySource:
    name = "openlibrary"

    def __init__(self, transport):
        self.http = transport

    def search(self, context, seeds, raw_isbn="") -> list[Record]:
        keys = []
        for seed in seeds:
            # L'API Books retourne une édition ; jamais les ISBN agrégés d'un Work.
            payload = self.http.json("https://openlibrary.org/api/books", {
                "bibkeys": "ISBN:" + seed, "format": "json", "jscmd": "data",
            })
            data = payload.get("ISBN:" + seed, {})
            for key in data.get("identifiers", {}).get("openlibrary", []):
                if str(key).startswith("OL") and str(key).endswith("M"):
                    keys.append("/books/" + key)
        if context.title:
            params = {"title": context.title, "fields": "key,editions,editions.key", "limit": "5"}
            if context.authors:
                params["author"] = context.authors[0]
            payload = self.http.json("https://openlibrary.org/search.json", params)
            for doc in payload.get("docs", []):
                for edition in doc.get("editions", {}).get("docs", []):
                    if edition.get("key", "").startswith("/books/"):
                        keys.append(edition["key"])
        records = []
        for key in list(dict.fromkeys(keys))[:8]:
            if not key.startswith("/books/OL") or not key.endswith("M"):
                continue
            data = self.http.json("https://openlibrary.org" + quote(key, safe="/") + ".json")
            authors = []
            for author in data.get("authors", [])[:6]:
                author_key = author.get("key", "")
                if author_key.startswith("/authors/OL") and author_key.endswith("A"):
                    person = self.http.json("https://openlibrary.org" + quote(author_key, safe="/") + ".json")
                    if person.get("name"):
                        authors.append(person["name"])
            records.append(Record(
                source=self.name, record_id=key, url="https://openlibrary.org" + key,
                title=data.get("title", ""), authors=tuple(authors),
                publisher=" ; ".join(data.get("publishers", [])), year=year(data.get("publish_date", "")),
                edition=data.get("edition_name", ""),
                language=" ; ".join(l.get("key", "").rsplit("/", 1)[-1] for l in data.get("languages", [])),
                isbns=valid_identifiers(data.get("isbn_10", []) + data.get("isbn_13", [])),
            ))
        return records
