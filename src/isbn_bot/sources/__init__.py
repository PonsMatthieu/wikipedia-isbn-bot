from .bnf import BnfSource
from .googlebooks import GoogleBooksSource
from .openlibrary import OpenLibrarySource
from .sudoc import SudocSource


def build_sources(settings, transport):
    constructors = {
        "bnf": lambda: BnfSource(transport),
        "sudoc": lambda: SudocSource(transport),
        "openlibrary": lambda: OpenLibrarySource(transport),
        "googlebooks": lambda: GoogleBooksSource(transport, settings.google_key),
    }
    return [constructors[name]() for name in settings.sources]
