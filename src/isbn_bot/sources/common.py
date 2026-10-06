import re

from ..isbn import extracted_tokens, normalize_isbn, valid_isbn
from ..http import HttpError
from ..models import Record


class SruDiagnosticError(ValueError):
    def __init__(self, codes=()):
        self.codes = tuple(sorted(set(codes)))
        super().__init__("Diagnostic SRU BnF : requête ou service indisponible")


def safe_source_error(exc: Exception) -> str:
    """Détails structurés seulement : jamais une URL ni un message fournisseur brut."""
    if isinstance(exc, PartialSearchError):
        return "Recherche partielle : " + "; ".join(exc.errors)
    if isinstance(exc, HttpError):
        if isinstance(exc.status_code, int) and 100 <= exc.status_code <= 599:
            return f"HttpError (HTTP {exc.status_code})"
        if exc.kind in {"Timeout", "ConnectTimeout", "ReadTimeout", "ConnectionError", "SSLError",
                        "ProxyError", "TooManyRedirects", "ChunkedEncodingError", "ContentDecodingError"}:
            return f"HttpError ({exc.kind})"
        return "HttpError"
    if isinstance(exc, SruDiagnosticError):
        codes = ",".join(str(c) for c in exc.codes) or "inconnu"
        return f"SruDiagnosticError (SRU {codes})"
    return type(exc).__name__


class PartialSearchError(RuntimeError):
    """Une recherche incomplète conserve ses notices et ses erreurs contrôlées."""
    def __init__(self, records: list[Record], errors: list[str]):
        super().__init__("; ".join(errors))
        self.records = records
        self.errors = list(dict.fromkeys(errors))


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
