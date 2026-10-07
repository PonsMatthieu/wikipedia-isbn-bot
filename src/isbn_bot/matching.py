"""Comparaisons bibliographiques Unicode et variantes de catalogage."""
import re
import unicodedata
from difflib import SequenceMatcher


def normalized_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Conserver tous les alphabets, notamment cyrillique, grec et japonais.
    return " ".join(re.findall(r"[^\W_]+", text, re.UNICODE))


def similarity(left: str, right: str) -> float:
    a, b = normalized_text(left), normalized_text(right)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def title_similarity(left: str, right: str) -> float:
    a, b = normalized_text(left), normalized_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    short, long = sorted((a, b), key=len)
    # Un titre principal attesté peut être suivi d'un sous-titre de catalogue.
    # Éviter de confondre des titres courts comme « France » et « France libre ».
    if long.startswith(short + " ") and len(short) >= 18 and len(short.split()) >= 3:
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def author_similarity(left: str, right: str) -> float:
    def tokens(value):
        value = re.sub(r"\([^)]*\)|\b\d{3,4}\b", " ", value)
        return normalized_text(value).split()
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    if sorted(a) == sorted(b):
        return 1.0
    shared = set(a) & set(b)
    # Une initiale ne suffit pas : un nom entier commun est exigé.
    if any(len(t) > 2 for t in shared):
        aa, bb = [t for t in a if t not in shared], [t for t in b if t not in shared]
        if aa and bb and len(aa) == len(bb) and all(
            x == y or (min(len(x), len(y)) == 1 and x[0] == y[0])
            for x, y in zip(sorted(aa), sorted(bb))
        ):
            return 0.95
        if not aa or not bb:
            return 0.8
    return max(similarity(left, right), similarity(" ".join(sorted(a)), " ".join(sorted(b))))


def publisher_similarity(left: str, right: str) -> float:
    def clean(value):
        value = re.sub(r"^.*?\s:\s*", "", value)
        parts = normalized_text(value).split()
        stop = {"editions", "edition", "editeur", "publisher", "publishers", "publishing", "ltd", "inc", "sa"}
        return " ".join(x for x in parts if x not in stop)
    a, b = clean(left), clean(right)
    if not a or not b:
        return similarity(left, right)
    if a == b or (len(a) >= 5 and a in b) or (len(b) >= 5 and b in a):
        return 1.0
    return similarity(a, b)


def language_code(value: str) -> str:
    code = normalized_text(value)
    return {"fr": "fre", "francais": "fre", "fra": "fre", "en": "eng", "anglais": "eng",
            "de": "ger", "deu": "ger", "allemand": "ger", "nl": "dut", "nld": "dut",
            "ru": "rus", "it": "ita", "es": "spa", "ja": "jpn", "pt": "por"}.get(code, code)


def title_variants(title: str) -> list[str]:
    full = re.sub(r"\s+", " ", title).strip(" ,.;")[:240]
    main = re.split(r"\s*[:：]\s*|\s+[–—]\s+", full, maxsplit=1)[0].strip()
    return list(dict.fromkeys(t for t in (full, main) if t))
