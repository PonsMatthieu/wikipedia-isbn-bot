from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Context:
    title: str = ""
    authors: tuple[str, ...] = ()
    publisher: str = ""
    year: str = ""
    edition: str = ""
    volume: str = ""
    language: str = ""
    translator: str = ""


@dataclass(frozen=True)
class IsbnField:
    template_index: int
    parameter_index: int
    template_name: str
    parameter_name: str
    raw_value: str
    context: Context
    editable: bool = True
    restriction: str = ""

    @property
    def locator(self) -> str:
        return f"t{self.template_index}:p{self.parameter_index}"


@dataclass(frozen=True)
class Record:
    source: str
    record_id: str
    url: str
    title: str
    authors: tuple[str, ...] = ()
    publisher: str = ""
    year: str = ""
    edition: str = ""
    volume: str = ""
    language: str = ""
    translator: str = ""
    isbns: tuple[str, ...] = ()
    invalid_isbns: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Page:
    page_id: int
    title: str
    revision_id: int
    timestamp: str
    start_timestamp: str
    wikitext: str
    namespace: int = 0
    categories: tuple[str, ...] = ()


@dataclass
class Candidate:
    isbn: str
    score: float
    evidence: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)


@dataclass
class Finding:
    field: IsbnField
    error_type: str
    candidates: list[Candidate]
    candidate_isbn: str | None = None
    proposed_value: str | None = None
    status: str = "NEEDS_REVIEW"
    reasons: list[str] = field(default_factory=list)
    source_errors: list[str] = field(default_factory=list)
    isbn_checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
