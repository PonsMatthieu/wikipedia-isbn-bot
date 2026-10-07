from urllib.parse import quote

from ..http import HttpError
from ..isbn import candidate_seeds
from ..models import Record
from .common import PartialSearchError, safe_source_error, valid_identifiers, year


class GoogleBooksSource:
    name = "googlebooks"

    def __init__(self, transport, key: str):
        if not key.strip():
            raise ValueError("googlebooks activé sans GOOGLE_BOOKS_API_KEY")
        self.http, self.key = transport, key.strip()

    def search(self, context, seeds, raw_isbn="") -> list[Record]:
        identifiers = list(dict.fromkeys(i for seed in seeds for i in candidate_seeds(seed)))
        queries = [("ISBN", "isbn:" + seed) for seed in identifiers[:4]]
        if context.title:
            title = context.title.replace('"', " ")[:180]
            title_query = 'intitle:"' + title + '"'
            if context.authors:
                author = context.authors[0].replace('"', " ")[:120]
                queries.append(("titre/auteur", title_query + ' inauthor:"' + author + '"'))
            queries.append(("titre", title_query))
        records, errors = {}, []
        for kind, query in queries:
            try:
                data = self.http.json("https://www.googleapis.com/books/v1/volumes", {
                    "q": query, "maxResults": "10", "printType": "books", "key": self.key,
                })
                if not isinstance(data, dict) or "error" in data:
                    raise ValueError("Réponse Google Books invalide")
                items = data.get("items", [])
                if not isinstance(items, list):
                    raise ValueError("Liste de volumes Google Books invalide")
                for item in items:
                    record = parse_volume(item)
                    if record is not None:
                        records[record.record_id] = record
            except Exception as exc:
                errors.append(f"Volumes {kind}: {safe_source_error(exc)}")
                if isinstance(exc, HttpError):
                    break  # Le transport a déjà effectué les reprises réseau.
        if errors:
            raise PartialSearchError(list(records.values()), errors)
        return list(records.values())


def parse_volume(item) -> Record | None:
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
        return None
    info = item.get("volumeInfo", {})
    if not isinstance(info, dict):
        return None
    def text(name):
        value = info.get(name, "")
        return value if isinstance(value, str) else ""
    authors = info.get("authors", [])
    identifiers = info.get("industryIdentifiers", [])
    return Record(
        source="googlebooks", record_id=item["id"],
        url="https://books.google.com/books?id=" + quote(item["id"], safe=""),
        title=text("title"),
        authors=tuple(a for a in authors if isinstance(a, str)) if isinstance(authors, list) else (),
        publisher=text("publisher"), year=year(text("publishedDate")), language=text("language"),
        isbns=valid_identifiers(i.get("identifier", "") for i in identifiers
            if isinstance(i, dict) and i.get("type") in {"ISBN_10", "ISBN_13"}) if isinstance(identifiers, list) else (),
    )
