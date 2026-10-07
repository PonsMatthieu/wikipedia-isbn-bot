import re
from urllib.parse import quote

from ..models import Record
from ..matching import title_variants, title_similarity, language_code
from .common import PartialSearchError, safe_source_error, valid_identifiers, year


class OpenLibrarySource:
    name = "openlibrary"

    def __init__(self, transport):
        self.http = transport

    def search(self, context, seeds, raw_isbn="") -> list[Record]:
        keys, works, records, errors = [], [], {}, []

        def fetch(url, params=None):
            try:
                return self.http.json(url, params)
            except Exception as exc:
                errors.append(safe_source_error(exc))
                return None

        # Books renvoie des éditions ; les ISBN agrégés des œuvres sont ignorés.
        for offset in range(0, min(len(seeds), 32), 16):
            group = seeds[offset:offset + 16]
            payload = fetch("https://openlibrary.org/api/books", {
                "bibkeys": ",".join("ISBN:" + seed for seed in group), "format": "json", "jscmd": "data",
            })
            if payload is None:
                break
            for seed in group:
                data = payload.get("ISBN:" + seed, {})
                for key in data.get("identifiers", {}).get("openlibrary", []):
                    if re.fullmatch(r"OL\d+M", str(key)):
                        keys.append("/books/" + key)
        if context.title:
            searches = []
            for title in title_variants(context.title)[:2]:
                base = {"title": title, "fields": "key,title,author_name,editions,editions.key", "limit": "10"}
                if context.authors:
                    searches.append(dict(base, author=context.authors[0]))
                searches.append(base)
            for params in searches:
                payload = fetch("https://openlibrary.org/search.json", params)
                if payload is None:
                    break
                for doc in payload.get("docs", []):
                    for edition in doc.get("editions", {}).get("docs", []):
                        if re.fullmatch(r"/books/OL\d+M", edition.get("key", "")):
                            keys.append(edition["key"])
                    work = doc.get("key", "")
                    if not work.startswith("/"):
                        work = "/works/" + work
                    if re.fullmatch(r"/works/OL\d+W", work) and title_similarity(context.title, doc.get("title", "")) >= 0.65:
                        works.append(work)

        def parse(data, key):
            if not data or not valid_identifiers(data.get("isbn_10", []) + data.get("isbn_13", [])):
                return None
            authors = []
            for author in data.get("authors", [])[:6]:
                author_key = author.get("key", "")
                if re.fullmatch(r"/authors/OL\d+A", author_key):
                    person = fetch("https://openlibrary.org" + quote(author_key, safe="/") + ".json")
                    if person and person.get("name"):
                        authors.append(person["name"])
            return Record(
                source=self.name, record_id=key, url="https://openlibrary.org" + key,
                title=data.get("title", ""), authors=tuple(authors),
                publisher=" ; ".join(data.get("publishers", [])), year=year(data.get("publish_date", "")),
                edition=data.get("edition_name", ""),
                language=" ; ".join(l.get("key", "").rsplit("/", 1)[-1] for l in data.get("languages", [])),
                isbns=valid_identifiers(data.get("isbn_10", []) + data.get("isbn_13", [])),
            )

        for key in list(dict.fromkeys(keys))[:16]:
            data = fetch("https://openlibrary.org" + quote(key, safe="/") + ".json")
            record = parse(data, key)
            if record:
                records[key] = record
        # Le search API ne retourne actuellement qu'une édition par œuvre.
        # Si elle ne correspond pas, explorer les vraies notices des éditions.
        matching = any(title_similarity(context.title, r.title) >= 0.8
                       and (not context.year or r.year == context.year)
                       and (not context.language or language_code(context.language) in
                            {language_code(v) for v in r.language.split(" ; ")}) for r in records.values())
        if not matching:
            for work in list(dict.fromkeys(works))[:2]:
                for offset in (0, 50):
                    payload = fetch("https://openlibrary.org" + work + "/editions.json", {"limit": "50", "offset": str(offset)})
                    if payload is None:
                        break
                    entries = payload.get("entries", [])
                    eligible = [d for d in entries if (not context.year or year(d.get("publish_date", "")) == context.year)
                                and title_similarity(context.title, d.get("title", "")) >= 0.65]
                    for data in eligible[:20]:
                        key = data.get("key", "")
                        if key in records or not re.fullmatch(r"/books/OL\d+M", key):
                            continue
                        record = parse(data, key)
                        if record:
                            records[key] = record
                    if len(entries) < 50 or eligible:
                        break
        if errors:
            raise PartialSearchError(list(records.values()), list(dict.fromkeys(errors)))
        return list(records.values())

