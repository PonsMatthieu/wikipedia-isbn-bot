import re

from defusedxml import ElementTree as ET

from ..http import HttpError
from ..isbn import isbn10, isbn13, normalize_isbn
from ..models import Record
from .common import PartialSearchError, SruDiagnosticError, cql_quote, local_name, safe_source_error, valid_identifiers, year


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
        records, errors = {}, []
        for query in queries[:8]:
            try:
                xml = self.http.text(self.endpoint, {
                    "version": "1.2", "operation": "searchRetrieve", "query": query,
                    "recordSchema": "unimarcxchange", "maximumRecords": "20",
                })
                for record in parse_bnf(xml):
                    records[record.record_id] = record
            except PartialSearchError as exc:
                for record in exc.records:
                    records[record.record_id] = record
                kind = "ISBN" if query.startswith("bib.isbn") else "titre"
                errors.extend(f"SRU {kind}: {error}" for error in exc.errors)
            except Exception as exc:
                kind = "ISBN" if query.startswith("bib.isbn") else "titre"
                errors.append(f"SRU {kind}: {safe_source_error(exc)}")
                # Le transport a déjà retenté les erreurs réseau : ne pas multiplier
                # les appels à un service indisponible. Un diagnostic CQL reste local
                # à sa requête et permet de poursuivre les autres recherches.
                if isinstance(exc, HttpError):
                    break
        if errors:
            raise PartialSearchError(list(records.values()), errors)
        return list(records.values())


def parse_bnf(xml: str) -> list[Record]:
    root = ET.fromstring(xml)
    diagnostic_error = None
    diagnostics = [e for e in root.iter() if local_name(e.tag) == "diagnostic"]
    if diagnostics:
        codes = []
        for diagnostic in diagnostics:
            for element in diagnostic:
                if local_name(element.tag) == "uri":
                    match = re.fullmatch(r"info:srw/diagnostic/\d+/(\d{1,5})", (element.text or "").strip())
                    if match:
                        codes.append(int(match[1]))
        diagnostic_error = SruDiagnosticError(codes)
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
    if diagnostic_error:
        if records:
            raise PartialSearchError(records, [safe_source_error(diagnostic_error)])
        raise diagnostic_error
    return records
