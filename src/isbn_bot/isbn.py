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
    return bool(re.fullmatch(r"\d{9}[\dX]", s)) and sum(
        (10 if c == "X" else int(c)) * (10 - i) for i, c in enumerate(s)
    ) % 11 == 0


def valid_isbn13(value: str) -> bool:
    s = normalize_isbn(value)
    if not re.fullmatch(r"(?:978|979)\d{10}", s) or s.startswith("9790"):
        return False  # 979-0 est réservé à l'ISMN, pas à l'ISBN.
    return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s)) % 10 == 0


def valid_isbn(value: str) -> bool:
    return valid_isbn10(value) or valid_isbn13(value)


def isbn13(value: str) -> str:
    s = normalize_isbn(value)
    if valid_isbn13(s):
        return s
    if valid_isbn10(s):
        prefix = "978" + s[:9]
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(prefix))
        return prefix + str((-total) % 10)
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
    digit = (-sum(int(c) * (10 - i) for i, c in enumerate(base))) % 11
    return base + ("X" if digit == 10 else str(digit))


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
    """Quelques pistes bornées : ISBN présents et hypothèse de faute de clé."""
    result = [s for s in extracted_tokens(value) if valid_isbn(s)]
    s = normalize_isbn(value)
    if re.fullmatch(r"(?:978|979)\d{10}", s) and not s.startswith("9790"):
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s[:12]))
        result.append(s[:12] + str((-total) % 10))
    elif re.fullmatch(r"\d{9}[\dX]", s):
        digit = (-sum(int(c) * (10 - i) for i, c in enumerate(s[:9]))) % 11
        result.append(s[:9] + ("X" if digit == 10 else str(digit)))
    return list(dict.fromkeys(result))[:3]
