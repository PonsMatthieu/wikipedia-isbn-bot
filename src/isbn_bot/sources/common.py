import re

from ..isbn import extracted_tokens, normalize_isbn, valid_isbn


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def valid_identifiers(values) -> tuple[str, ...]:
    result = []
    for value in values:
        s = normalize_isbn(str(value))
        found = [s] if valid_isbn(s) else extracted_tokens(str(value))
        result.extend(i for i in found if valid_isbn(i))
    return tuple(dict.fromkeys(result))


def year(value: str) -> str:
    match = re.search(r"\b(?:1[5-9]|20)\d{2}\b", value)
    return match.group() if match else ""


def cql_quote(value: str) -> str:
    # La requête est construite par le programme, jamais exécutée comme du code.
    return '"' + re.sub(r"[\"\r\n\\]", " ", value).strip()[:250] + '"'
