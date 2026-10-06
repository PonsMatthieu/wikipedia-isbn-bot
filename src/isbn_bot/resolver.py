"""Score de classement, pas probabilité calibrée. Aucune auto-approbation."""
import re
import unicodedata
from difflib import SequenceMatcher

from .isbn import candidate_seeds, classify, isbn13, normalize_isbn, valid_isbn
from .models import Candidate, Finding, Record
from .sources.common import PartialSearchError, safe_source_error


def normalized_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def similarity(left: str, right: str) -> float:
    a, b = normalized_text(left), normalized_text(right)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def language_code(value: str) -> str:
    code = normalized_text(value)
    return {"fr": "fre", "francais": "fre", "fra": "fre", "en": "eng", "anglais": "eng",
            "de": "ger", "deu": "ger", "allemand": "ger", "nl": "dut", "nld": "dut"}.get(code, code)


def score_record(context, record: Record, raw_isbn: str) -> tuple[float, list[str]]:
    scores, mismatches = [], []
    if context.title:
        value = similarity(context.title, record.title)
        scores.append((0.35, value))
        if value < 0.65:
            mismatches.append("Titre différent")
    if context.authors:
        values = [max((similarity(a, b) for b in record.authors), default=0) for a in context.authors]
        scores.append((0.25, sum(values) / len(values)))
        if record.authors and max(values) < 0.5:
            mismatches.append("Auteur différent")
    if context.publisher:
        value = similarity(context.publisher, record.publisher)
        scores.append((0.15, value))
        if record.publisher and value < 0.4:
            mismatches.append("Éditeur différent")
    if context.year:
        scores.append((0.10, float(context.year == record.year)))
        if record.year and context.year != record.year:
            mismatches.append("Année différente")
    if context.edition or context.volume:
        pairs = [(a, b) for a, b in ((context.edition, record.edition), (context.volume, record.volume)) if a]
        scores.append((0.10, sum(similarity(a, b) for a, b in pairs) / len(pairs)))
        for a, b in pairs:
            if b and similarity(a, b) < 0.7:
                mismatches.append("Édition ou volume différent")
    if context.translator:
        if not record.translator:
            mismatches.append("Traducteur à confirmer")
        elif similarity(context.translator, record.translator) < 0.7:
            mismatches.append("Traducteur différent")
    if context.language and record.language and language_code(context.language) != language_code(record.language):
        mismatches.append("Langue différente ou notice multilingue à vérifier")
    # La ressemblance numérique n'a qu'un poids mineur.
    scores.append((0.05, max((similarity(normalize_isbn(raw_isbn), i) for i in record.isbns), default=0)))
    score = sum(w * v for w, v in scores) / sum(w for w, _ in scores)
    if not context.title:
        score = min(score, 0.35)
    elif not context.authors and not context.publisher and not context.year:
        score = min(score, 0.65)
    if mismatches:
        score = min(score, 0.59)
    return round(score, 4), mismatches


def rank(field, records: list[Record]) -> list[Candidate]:
    grouped = {}
    for record in records:
        score, mismatches = score_record(field.context, record, field.raw_value)
        for value in record.isbns:
            if not valid_isbn(value):
                continue
            canonical = isbn13(value)
            item = grouped.setdefault(canonical, Candidate(canonical, 0.0))
            item.evidence.append({"record": record.to_dict(), "matched_isbn": value,
                                  "score": score, "mismatches": mismatches})
            item.score = max(item.score, score)
    for item in grouped.values():
        best = max(item.evidence, key=lambda e: e["score"])
        item.mismatches = sorted({m for e in item.evidence for m in e["mismatches"]})
        if item.mismatches:
            item.score = min(item.score, 0.59)
        sources = sorted({e["record"]["source"] for e in item.evidence})
        item.reasons = ["ISBN explicitement présent dans : " + ", ".join(sources)]
        if len(sources) > 1:
            item.reasons.append("Plusieurs catalogues concordent sur l'identifiant ; indépendance éditoriale à vérifier")
    return sorted(grouped.values(), key=lambda c: (-c.score, c.isbn))[:10]


class Analyzer:
    def __init__(self, sources):
        self.sources = sources

    def analyze(self, field) -> Finding:
        classification = classify(field.raw_value)
        seeds = candidate_seeds(field.raw_value)
        records, errors = [], []
        # Découverte d'abord ; Sudoc confirme ensuite les candidats réellement trouvés.
        sources = sorted(self.sources, key=lambda s: s.name == "sudoc")
        for source in sources:
            source_seeds = seeds
            if source.name == "sudoc":
                preliminary = rank(field, records)
                source_seeds = list(dict.fromkeys(seeds + [c.isbn for c in preliminary if c.score >= 0.7]))[:5]
            try:
                records.extend(source.search(field.context, source_seeds, field.raw_value))
            except PartialSearchError as exc:
                records.extend(exc.records)
                errors.extend(f"{source.name}: {error}" for error in exc.errors)
            except Exception as exc:
                # Ni URL ni corps d'erreur fournisseur : risque de contenir une clé.
                errors.append(f"{source.name}: {safe_source_error(exc)}")
        candidates = rank(field, records)
        reasons = []
        if any(normalize_isbn(field.raw_value) in r.invalid_isbns for r in records):
            classification = "PUBLISHED_BAD_ISBN"
            reasons.append("Une notice contient cet ISBN comme erroné : conserver/vérifier manuellement")
        proposed = None
        allowed = classification in {"BAD_CHECKSUM", "EXTRA_TEXT", "UNKNOWN"}
        if candidates and allowed and field.editable and candidates[0].score >= 0.7 and not candidates[0].mismatches:
            # Des éditions rivales restent visibles ; le choix est toujours humain.
            proposed = candidates[0].isbn
        if field.restriction:
            reasons.append(field.restriction)
        if classification in {"MULTIPLE_ISBN", "ISSN_AS_ISBN", "EAN_AS_ISBN", "ISMN_AS_ISBN", "PUBLISHED_BAD_ISBN"}:
            reasons.append("Ce cas nécessite une intervention manuelle dans Wikipédia")
        if not candidates:
            reasons.append("Aucun ISBN valide attesté par les catalogues interrogés")
        if errors:
            reasons.append("Recherche partielle : certains services ont échoué")
        return Finding(field, classification, candidates, proposed, proposed,
                       "NEEDS_REVIEW" if candidates else "NO_CANDIDATE", reasons, errors)
