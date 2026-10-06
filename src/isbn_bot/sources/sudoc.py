import re

from defusedxml import ElementTree as ET

from ..http import HttpError
from ..models import Record
from .common import PartialSearchError, local_name, safe_source_error, valid_identifiers, year


_RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"


class SudocSource:
    name = "sudoc"

    def __init__(self, transport):
        self.http = transport

    def search(self, context, seeds, raw_isbn="") -> list[Record]:
        records, errors = {}, []
        # isbn2ppn ne fait pas de recherche libre titre/auteur. Les ISBN découvertes
        # dans les autres catalogues sont également corroborées via ce service.
        for seed in list(dict.fromkeys(seeds))[:5]:
            try:
                xml = self.http.text("https://www.sudoc.fr/services/isbn2ppn/" + seed)
                root = ET.fromstring(xml)
                if local_name(root.tag) != "sudoc":
                    raise ValueError("Réponse isbn2ppn Sudoc invalide")
            except Exception as exc:
                errors.append("isbn2ppn: " + safe_source_error(exc))
                if isinstance(exc, HttpError) and exc.status_code not in {404, 410}:
                    break
                continue
            ppns = [(e.text or "").strip() for e in root.iter() if local_name(e.tag).lower() == "ppn"]
            for ppn in ppns[:3]:
                if not re.fullmatch(r"\d{8}[\dXx]", ppn):
                    continue
                try:
                    record = parse_sudoc(self.http.text("https://www.sudoc.fr/" + ppn + ".rdf"), ppn)
                except Exception as exc:
                    errors.append("RDF: " + safe_source_error(exc))
                    if isinstance(exc, HttpError) and exc.status_code not in {404, 410}:
                        raise PartialSearchError(list(records.values()), errors) from None
                    continue
                if record:
                    records[ppn] = record
        if errors:
            raise PartialSearchError(list(records.values()), errors)
        return list(records.values())


def parse_sudoc(xml: str, ppn: str) -> Record | None:
    root = ET.fromstring(xml)
    nodes = list(root.iter())
    by_about = {e.attrib[_RDF + "about"]: e for e in nodes if _RDF + "about" in e.attrib}
    # Manifestation identifiée par le PPN : ne pas mélanger Work et personnes RDF.
    subject = next((e for e in nodes if e.attrib.get(_RDF + "about", "").rstrip("/").endswith(ppn + "/id")), None)
    if subject is None:
        subject = next((e for e in nodes if e.attrib.get(_RDF + "about", "").rstrip("/").endswith("/" + ppn)), None)
    if subject is None:
        return None
    def literals(names):
        return [(e.text or "").strip() for e in subject if local_name(e.tag) in names and (e.text or "").strip()]
    def dereference(element):
        if (element.text or "").strip():
            return element.text.strip()
        target = by_about.get(element.attrib.get(_RDF + "resource", ""))
        if target is None:
            return ""
        return next(((e.text or "").strip() for e in target.iter() if local_name(e.tag) in {"name", "prefLabel", "label"} and (e.text or "").strip()), "")
    authors = tuple(filter(None, (dereference(e) for e in subject if local_name(e.tag) in {"creator", "aut"})))
    translators = [dereference(e) for e in subject if local_name(e.tag) == "trl"]
    identifiers = literals({"isbn", "isbn10", "isbn13"})
    title = next(iter(literals({"title"})), "")
    if not title:
        return None
    return Record(
        source="sudoc", record_id=ppn, url="https://www.sudoc.fr/" + ppn,
        title=title, authors=authors, publisher=" ; ".join(literals({"publisher"})),
        year=year(" ".join(literals({"date", "issued", "publicationDate"}))),
        edition=" ; ".join(literals({"edition", "editionStatement"})),
        translator=" ; ".join(filter(None, translators)), isbns=valid_identifiers(identifiers),
    )
