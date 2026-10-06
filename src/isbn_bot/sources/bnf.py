from defusedxml import ElementTree as ET

from ..isbn import isbn10, isbn13, normalize_isbn
from ..models import Record
from .common import cql_quote, local_name, valid_identifiers, year


class BnfSource:
    name = "bnf"
    endpoint = "https://catalogue.bnf.fr/api/SRU"

    def __init__(self, transport):
        self.http = transport

    def search(self, context, seeds, raw_isbn="") -> list[Record]:
        identifiers = []
        for seed in seeds:
            identifiers.append(seed)
            identifiers.append(isbn13(seed))
            try:
                identifiers.append(isbn10(seed))
            except ValueError:
                pass
        queries = ["bib.isbn all " + cql_quote(s) for s in dict.fromkeys(identifiers)]
        suspect = normalize_isbn(raw_isbn)
        if len(suspect) in {10, 13} and suspect not in seeds:
            queries.append("bib.isbn all " + cql_quote(suspect))
        if context.title:
            queries.append("bib.title all " + cql_quote(context.title))
        records = {}
        for query in queries[:8]:
            xml = self.http.text(self.endpoint, {
                "version": "1.2", "operation": "searchRetrieve", "query": query,
                "recordSchema": "unimarcxchange", "maximumRecords": "20",
            })
            for record in parse_bnf(xml):
                records[record.record_id] = record
        return list(records.values())


def parse_bnf(xml: str) -> list[Record]:
    root = ET.fromstring(xml)
    if any(local_name(e.tag) == "diagnostic" for e in root.iter()):
        raise ValueError("Diagnostic SRU BnF : requête ou service indisponible")
    records = []
    for node in root.iter():
        # Évite de confondre l'enveloppe SRU avec le record MARC interne.
        if local_name(node.tag) != "record" or not any(local_name(c.tag) == "datafield" for c in node):
            continue
        fields, controls = {}, {}
        for child in node:
            tag = child.attrib.get("tag", "")
            if local_name(child.tag) == "controlfield":
                controls[tag] = (child.text or "").strip()
            if local_name(child.tag) == "datafield":
                fields.setdefault(tag, []).append({
                    c: [s.text or "" for s in child if s.attrib.get("code") == c]
                    for c in {s.attrib.get("code", "") for s in child}
                })
        def values(tag, code):
            return [v.strip() for f in fields.get(tag, []) for v in f.get(code, []) if v.strip()]
        def first(tag, code):
            return next(iter(values(tag, code)), "")
        authors = []
        for tag in ("700", "701"):
            for author in fields.get(tag, []):
                person = " ".join(author.get("b", []) + author.get("a", [])).strip()
                if person:
                    authors.append(person)
        record_id = controls.get("003") or node.attrib.get("id") or controls.get("001", "")
        if not record_id:
            continue
        if record_id.startswith("http"):
            url = record_id.replace("http://", "https://", 1)
        elif record_id.startswith("ark:/"):
            url = "https://catalogue.bnf.fr/" + record_id
        else:
            url = "https://catalogue.bnf.fr/"  # Aucun ARK inventé depuis un identifiant interne.
        title = " : ".join(values("200", "a") + values("200", "e") + values("200", "h") + values("200", "i"))
        records.append(Record(
            source="bnf", record_id=record_id, url=url, title=title,
            authors=tuple(authors), publisher=first("214", "c") or first("210", "c"),
            year=year(first("214", "d") or first("210", "d")), edition=first("205", "a"),
            volume=first("200", "h") or first("200", "v"), language=first("101", "a"),
            isbns=valid_identifiers(values("010", "a")),
            invalid_isbns=tuple(normalize_isbn(v) for v in values("010", "z")),
        ))
    return records
