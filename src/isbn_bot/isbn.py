"""Validation stricte. Une clé recalculée ne constitue jamais une preuve."""
import re

_SEPARATORS = re.compile(r"[\s\-‐‑‒–—−\u00ad]")
_ISBN_LABEL = re.compile(r"^ISBN(?:-(?:10|13))?\s*:?\s*", re.I)
_THIRTEEN = re.compile(r"(?<![0-9Xx])97[89](?:[\s\-‐‑–]*\d){10}(?![0-9Xx])")
_TEN = re.compile(r"(?<![0-9Xx])\d(?:[\s\-‐‑–]*\d){8}[\s\-‐‑–]*[0-9Xx](?![0-9Xx])")


def normalize_isbn(value: str) -> str:
    return _SEPARATORS.sub("", _ISBN_LABEL.sub("", value.strip())).upper()


def valid_isbn10(value: str) -> bool:
    s = normalize_isbn(value)
    return bool(re.fullmatch(r"[0-9]{9}[0-9X]", s)) and sum(
        (10 if c == "X" else int(c)) * (10 - i) for i, c in enumerate(s)
    ) % 11 == 0


def valid_isbn13(value: str) -> bool:
    s = normalize_isbn(value)
    if not re.fullmatch(r"(?:978|979)[0-9]{10}", s) or s.startswith("9790"):
        return False  # 979-0 est réservé à l'ISMN, pas à l'ISBN.
    return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s)) % 10 == 0


def valid_isbn(value: str) -> bool:
    return valid_isbn10(value) or valid_isbn13(value)


def check_digit10(base: str) -> str:
    """Clé des neuf chiffres du corps ISBN-10, sans validation bibliographique."""
    if not re.fullmatch(r"[0-9]{9}", base):
        raise ValueError("Le corps ISBN-10 doit contenir neuf chiffres")
    digit = (-sum(int(c) * (10 - i) for i, c in enumerate(base))) % 11
    return "X" if digit == 10 else str(digit)


def check_digit13(base: str) -> str:
    """Clé des douze chiffres du corps ISBN-13 ; exclut les EAN et ISMN."""
    if not re.fullmatch(r"(?:978|979)[0-9]{9}", base) or base.startswith("9790"):
        raise ValueError("Le corps ISBN-13 doit contenir douze chiffres ISBN")
    return str((-sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(base))) % 10)


def isbn13(value: str) -> str:
    s = normalize_isbn(value)
    if valid_isbn13(s):
        return s
    if valid_isbn10(s):
        prefix = "978" + s[:9]
        return prefix + check_digit13(prefix)
    raise ValueError("ISBN invalide")


def extracted_tokens(value: str) -> list[str]:
    # Repérer d'abord les 13 chiffres sur toute la chaîne : une année située avant
    # l'ISBN ne doit pas former un faux ISBN-10 en consommant son début.
    matches = list(_THIRTEEN.finditer(value))
    matches += [m for m in _TEN.finditer(value) if not any(
        m.start() < longer.end() and longer.start() < m.end() for longer in matches
    )]
    return list(dict.fromkeys(normalize_isbn(m.group()) for m in sorted(matches, key=lambda m: m.start())))


def isbn10(value: str) -> str:
    s = isbn13(value)
    if not s.startswith("978"):
        raise ValueError("Un ISBN 979 n'a pas d'équivalent ISBN-10")
    base = s[3:12]
    return base + check_digit10(base)


def equivalent_isbns(value: str) -> dict[str, str]:
    """Formes d'un ISBN valide : les identifiants 979 restent exclusivement en 13."""
    canonical = isbn13(value)
    forms = {"isbn13": canonical}
    if canonical.startswith("978"):
        forms["isbn10"] = isbn10(canonical)
    return forms


def checksum_hypothesis(value: str) -> str | None:
    """Changer seulement la clé est une piste, jamais une preuve d'édition."""
    s = normalize_isbn(value)
    if re.fullmatch(r"[0-9]{9}[0-9X]", s):
        corrected = s[:9] + check_digit10(s[:9])
    elif re.fullmatch(r"(?:978|979)[0-9]{10}", s) and not s.startswith("9790"):
        corrected = s[:12] + check_digit13(s[:12])
    else:
        return None
    return corrected if corrected != s else None


def classify(value: str) -> str:
    s = normalize_isbn(value)
    if s.startswith("9790") and len(s) == 13:
        return "ISMN_AS_ISBN"
    if len(s) == 13 and s.isdigit() and not s.startswith(("978", "979")):
        return "EAN_AS_ISBN"
    if re.fullmatch(r"\d{7}[\dX]", s):
        return "ISSN_AS_ISBN"
    tokens = extracted_tokens(value)
    if len(tokens) > 1:
        return "MULTIPLE_ISBN"
    if valid_isbn(s):
        return "EXTRA_TEXT" if _ISBN_LABEL.match(value.strip()) else "VALID"
    if len(tokens) == 1 and valid_isbn(tokens[0]):
        return "EXTRA_TEXT"
    if re.fullmatch(r"\d{9}[\dX]|(?:978|979)\d{10}", s):
        return "BAD_CHECKSUM"
    if not value.strip():
        return "EMPTY"
    return "UNKNOWN"


def candidate_seeds(value: str) -> list[str]:
    """Pistes bornées incluant les deux formats et la faute de clé éventuelle."""
    result = []
    tokens = dict.fromkeys([normalize_isbn(value)] + extracted_tokens(value))
    for token in tokens:
        seed = token if valid_isbn(token) else checksum_hypothesis(token)
        if seed:
            result.extend([seed] + list(equivalent_isbns(seed).values()))
    return list(dict.fromkeys(result))[:4]


def diagnose_isbn(value: str) -> dict:
    """Contrôles mathématiques visibles, distincts des preuves de catalogue."""
    s = normalize_isbn(value)
    expected, format_name = None, None
    if re.fullmatch(r"[0-9]{9}[0-9X]", s):
        expected, format_name = check_digit10(s[:9]), "ISBN-10"
    elif re.fullmatch(r"(?:978|979)[0-9]{10}", s) and not s.startswith("9790"):
        expected, format_name = check_digit13(s[:12]), "ISBN-13"
    hypothesis = checksum_hypothesis(s)
    return {
        "normalized": s, "classification": classify(value), "format": format_name,
        "valid": valid_isbn(s), "supplied_check_digit": s[-1] if expected is not None else None,
        "expected_check_digit": expected,
        "checksum_matches": s[-1] == expected if expected is not None else None,
        "equivalents": equivalent_isbns(s) if valid_isbn(s) else {},
        "checksum_only_hypothesis": hypothesis,
        "hypothesis_equivalents": equivalent_isbns(hypothesis) if hypothesis else {},
        "search_seeds": candidate_seeds(value),
        "requires_catalogue_confirmation": bool(hypothesis),
        "hypothesis_sources": [],
    }
