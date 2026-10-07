"""Score de classement, pas probabilité calibrée. Aucune auto-approbation."""
import re

from .isbn import candidate_seeds, classify, diagnose_isbn, isbn13, normalize_isbn, valid_isbn, repair_seeds, checksum_hypothesis
from .matching import (normalized_text, similarity, title_similarity, author_similarity,
                       publisher_similarity, language_code)
from .models import Candidate, Finding, Record
from .sources.common import PartialSearchError, safe_source_error


def score_record(context, record: Record, raw_isbn: str) -> tuple[float, list[str]]:
    scores, mismatches = [], []
    if context.title:
        value = title_similarity(context.title, record.title)
        scores.append((0.35, value))
        if value < 0.65:
            mismatches.append("Titre différent")
    if context.authors:
        values = [max((author_similarity(a, b) for b in record.authors), default=0) for a in context.authors]
        scores.append((0.25, sum(values) / len(values)))
        if record.authors and max(values) < 0.5:
            mismatches.append("Auteur différent")
    if context.publisher:
        value = publisher_similarity(context.publisher, record.publisher)
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
    languages = {language_code(v) for v in re.split(r"[;,]", record.language) if v.strip()}
    if context.language and languages and language_code(context.language) not in languages:
        mismatches.append("Langue différente ou notice multilingue à vérifier")
    # La ressemblance numérique n'a qu'un poids mineur.
    scores.append((0.05, max((similarity(normalize_isbn(raw_isbn), i) for i in record.isbns), default=0)))
    score = sum(w * v for w, v in scores) / sum(w for w, _ in scores)
    if not context.title:
        score = min(score, 0.35)
    elif not context.authors and not context.publisher and not context.year:
        hypothesis = checksum_hypothesis(raw_isbn)
        attested = hypothesis and any(valid_isbn(i) and isbn13(i) == isbn13(hypothesis) for i in record.isbns)
        # Un titre exact et une correction de clé attestée désignent une édition,
        # même si la citation n'a pas renseigné les autres métadonnées.
        score = min(score, 0.85 if attested and title_similarity(context.title, record.title) >= 0.95 else 0.65)
    if mismatches:
        score = min(score, 0.59)
    return round(score, 4), mismatches


def rank(field, records: list[Record]) -> list[Candidate]:
    grouped, seen = {}, set()
    for record in records:
        signature = (record.source, record.record_id, record.title, tuple(record.authors), record.publisher,
                     record.year, record.edition, record.volume, record.language, tuple(record.isbns))
        if signature in seen:
            continue
        seen.add(signature)
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
        best = max(item.evidence, key=lambda e: (not e["mismatches"], e["score"]))
        item.score = best["score"]
        item.mismatches = list(best["mismatches"])
        # Conserver toutes les réserves dans les preuves. Une notice au titre
        # allongé/mal cataloguée ne peut plus contaminer une notice concordante.
        item.warnings = sorted({m for e in item.evidence for m in e["mismatches"]})
        for evidence in item.evidence:
            record = Record(**evidence["record"])
            same_work = title_similarity(field.context.title, record.title) >= 0.8
            if field.context.authors and record.authors:
                same_work &= max(author_similarity(a, b) for a in field.context.authors for b in record.authors) >= 0.6
            if same_work:
                item.mismatches.extend(m for m in evidence["mismatches"] if m in {
                    "Année différente", "Édition ou volume différent", "Langue différente ou notice multilingue à vérifier"
                })
        item.mismatches = sorted(set(item.mismatches))
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
        # Réparations élargies seulement si la découverte initiale n'a rien trouvé.
        # Les adaptateurs regroupent les identifiants quand leur API le permet.
        if not any(c.score >= 0.7 and not c.mismatches for c in candidates):
            extra = [s for s in repair_seeds(field.raw_value) if s not in seeds]
            for source in sources:
                if not extra or source.name not in {"bnf", "openlibrary"}:
                    continue
                try:
                    records.extend(source.search(type(field.context)(), extra, field.raw_value))
                except PartialSearchError as exc:
                    records.extend(exc.records)
                    errors.extend(f"{source.name}: {error}" for error in exc.errors)
                except Exception as exc:
                    errors.append(f"{source.name}: {safe_source_error(exc)}")
            candidates = rank(field, records)
        checks = diagnose_isbn(field.raw_value)
        hypothesis = checks["checksum_only_hypothesis"]
        if hypothesis:
            canonical = isbn13(hypothesis)
            matching = next((c for c in candidates if c.isbn == canonical), None)
            if matching:
                checks["hypothesis_sources"] = sorted({e["record"]["source"] for e in matching.evidence})
                matching.reasons.append(
                    "Même corps numérique ; clé recalculée de " + checks["supplied_check_digit"] +
                    " à " + checks["expected_check_digit"] + " ; édition exacte à vérifier"
                )
        reasons = []
        if any(normalize_isbn(field.raw_value) in r.invalid_isbns for r in records):
            classification = "PUBLISHED_BAD_ISBN"
            reasons.append("Une notice contient cet ISBN comme erroné : conserver/vérifier manuellement")
        proposed = None
        allowed = classification in {"BAD_CHECKSUM", "EXTRA_TEXT", "UNKNOWN"}
        if candidates and allowed and field.editable and candidates[0].score >= 0.7 and not candidates[0].mismatches:
            # Des éditions rivales restent visibles ; le choix est toujours humain.
            proposed = candidates[0].isbn
            rivals = [c for c in candidates[1:] if c.score >= candidates[0].score - 0.04 and not c.mismatches]
            if rivals:
                close = set(candidate_seeds(field.raw_value))
                preferred = [c for c in [candidates[0]] + rivals if c.isbn in close]
                if len(preferred) == 1:
                    proposed = preferred[0].isbn
                else:
                    proposed = None
                    reasons.append("Plusieurs éditions compatibles : choix humain requis")
        if field.restriction:
            reasons.append(field.restriction)
        if classification in {"MULTIPLE_ISBN", "ISSN_AS_ISBN", "EAN_AS_ISBN", "ISMN_AS_ISBN", "PUBLISHED_BAD_ISBN"}:
            reasons.append("Ce cas nécessite une intervention manuelle dans Wikipédia")
        if not candidates:
            reasons.append("Aucun ISBN valide attesté par les catalogues interrogés")
        if errors:
            reasons.append("Recherche partielle : certains services ont échoué")
        finding = Finding(field, classification, candidates, proposed, proposed,
                          "NEEDS_REVIEW" if candidates else "NO_CANDIDATE", reasons, list(dict.fromkeys(errors)), checks)
        finding.blockers = proposal_blockers(finding)
        finding.suggested_action = suggested_action(finding)
        return finding


def proposal_blockers(finding) -> list[str]:
    if finding.proposed_value:
        return []
    blocked = []
    if not finding.candidates:
        blocked.append("NO_CANDIDATE")
    if not finding.field.context.title:
        blocked.append("MISSING_TITLE")
    if not finding.field.editable:
        blocked.append("FIELD_RESTRICTED")
    if finding.error_type not in {"BAD_CHECKSUM", "EXTRA_TEXT", "UNKNOWN"}:
        blocked.append("TYPE_EXCLUDED")
    if finding.candidates:
        if finding.candidates[0].mismatches:
            blocked.append("METADATA_MISMATCH")
        elif finding.candidates[0].score < 0.7:
            blocked.append("SCORE_BELOW_THRESHOLD")
        else:
            blocked.append("AMBIGUOUS_EDITION")
    if finding.source_errors:
        blocked.append("PARTIAL_SEARCH")
    return blocked


def suggested_action(finding) -> str:
    return {
        "MULTIPLE_ISBN": "Séparer les ISBN et vérifier chaque édition dans le champ approprié",
        "ISSN_AS_ISBN": "Vérifier la revue puis déplacer l'identifiant dans le champ ISSN",
        "EAN_AS_ISBN": "Vérifier si le préfixe ISBN a été mal saisi ou s'il s'agit d'un EAN",
        "ISMN_AS_ISBN": "Vérifier la partition puis utiliser un champ ISMN approprié",
        "PUBLISHED_BAD_ISBN": "Vérifier l'ISBN imprimé signalé erroné dans le catalogue",
    }.get(finding.error_type, "Examiner les notices et l'édition" if finding.candidates else "Rechercher avec le titre, l'auteur et l'éditeur de la référence")

