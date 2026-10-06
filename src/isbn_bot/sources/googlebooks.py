from ..models import Record
from .common import valid_identifiers, year


class GoogleBooksSource:
    name = "googlebooks"

    def __init__(self, transport, key: str):
        if not key:
            raise ValueError("googlebooks activé sans GOOGLE_BOOKS_API_KEY")
        self.http, self.key = transport, key

    def search(self, context, seeds, raw_isbn="") -> list[Record]:
        queries = ["isbn:" + seed for seed in seeds]
        if context.title:
            title = context.title.replace('"', " ")[:180]
            queries.append('intitle:"' + title + '"')
        records = {}
        for query in queries[:4]:
            data = self.http.json("https://www.googleapis.com/books/v1/volumes", {"q": query, "maxResults": "10", "key": self.key})
            for item in data.get("items", []):
                info = item.get("volumeInfo", {})
                records[item["id"]] = Record(
                    source=self.name, record_id=item["id"],
                    url="https://books.google.com/books?id=" + item["id"],
                    title=info.get("title", ""), authors=tuple(info.get("authors", [])),
                    publisher=info.get("publisher", ""), year=year(info.get("publishedDate", "")),
                    language=info.get("language", ""),
                    isbns=valid_identifiers(i.get("identifier", "") for i in info.get("industryIdentifiers", []) if i.get("type") in {"ISBN_10", "ISBN_13"}),
                )
        return list(records.values())
