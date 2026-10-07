import difflib
import re
from dataclasses import replace

import mwparserfromhell

from .models import Context, IsbnField

# Réécriture supervisée uniquement pour ces modèles connus.
_SUPPORTED = {"ouvrage", "cite book", "article", "cite journal", "isbn", "écrit", "citation", "lien web", "cite web"}
_ISBN_PARAM = re.compile(r"isbn(?:[ _-]?[1-9]\d*)?$")


def plain(value: str) -> str:
    return re.sub(r"\s+", " ", mwparserfromhell.parse(value).strip_code()).strip()


def name(value: str) -> str:
    return re.sub(r"[ _]+", " ", value.strip()).removeprefix("Modèle:").removeprefix("Template:").lower()


def context_from_template(template) -> Context:
    params = {name(str(p.name)): plain(str(p.value)) for p in template.params}
    def first(*keys):
        return next((params[k] for k in keys if params.get(k)), "")
    authors = []
    for i in range(1, 10):
        suffix = "" if i == 1 else str(i)
        full = first("auteur" + suffix, "author" + suffix, "auteur" + str(i), "author" + str(i))
        if not full:
            last = first("nom" + str(i), "last" + suffix, "last" + str(i), "nom" + suffix)
            given = first("prénom" + str(i), "prenom" + str(i), "first" + suffix, "first" + str(i))
            full = " ".join(p for p in (given, last) if p)
        if full and full not in authors:
            authors.append(full)
    date = first("année", "annee", "year", "date")
    year = re.search(r"\b(?:1[5-9]|20)\d{2}\b", date)
    return Context(
        title=first("titre", "title"),
        authors=tuple(authors),
        publisher=first("éditeur", "editeur", "publisher"),
        year=year.group() if year else "",
        edition=first("édition", "edition"),
        volume=first("tome", "volume"),
        language=first("langue", "language"),
        translator=first("traducteur", "translator", "traduction"),
    )


def context_from_line(text: str, position: int) -> Context:
    """Contexte local à ce champ ; ne pas prendre un livre cité plus loin."""
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    end = len(text) if end < 0 else end
    prefix, suffix = text[start:position], text[position:end]
    # Ne pas traverser un ISBN précédent sur une ligne avec plusieurs éditions.
    previous = list(re.finditer(r"\{\{\s*ISBN\b.*?\}\}", prefix, re.I))
    local = prefix[previous[-1].end():] if previous else prefix
    italic = list(re.finditer(r"(?<!')''([^'\n]+)''(?!')", local))
    # Les contributeurs emploient aussi *titre* dans une prose de traduction.
    markdown = list(re.finditer(r"\*([^*\n]+)\*", local))
    matches = sorted(italic + markdown, key=lambda m: m.end())
    title, before, tail = "", "", ""
    for match in reversed(matches):
        candidate = plain(match.group(1)).strip(" ,.;")
        if 2 <= len(candidate) <= 180 and len(candidate.split()) <= 24:
            title, before, tail = candidate, local[:match.start()], local[match.end():]
            break
    if not title and re.match(r"\s*[*#]\s+", prefix):
        # Bibliographie sans italique : « Auteur : Titre — description — ISBN ».
        cleaned = plain(re.sub(r"^\s*[*#]+\s*", "", local))
        pair = re.split(r"\s*:\s*", cleaned, maxsplit=1)
        if len(pair) == 2 and pair[0] and len(pair[0]) < 100:
            before, rest = pair
            title = re.split(r"\s+[–—-]\s+(?:brochure|livre|ouvrage|DVD)\b", rest, maxsplit=1, flags=re.I)[0].strip(" ,.;-()")
            tail = rest[len(title):]
    if not title:
        return Context()
    author = plain(re.sub(r"^\s*[*#\d.]+\s*", "", before)).strip(" ,.;:()")
    # Une phrase narrative ou une simple langue n'est pas un nom d'auteur.
    if len(author.split()) > 8 or re.search(r"\b(?:française|allemande|italienne|espagnole|néerlandaise|tome|volume)\b", author, re.I):
        author = ""
    tail = plain(tail)
    years = re.search(r"\b(?:1[5-9]|20)\d{2}\b", tail)
    if not years:
        # Dans les listes, l'année est souvent après le modèle ISBN.
        years = re.search(r"\b(?:1[5-9]|20)\d{2}\b", suffix)
    parts = [p.strip(" ,.;()") for p in tail.split(",")]
    publisher = next((p for p in parts if p and not re.search(r"\b(tome|volume|\d|p\.|brochure|pages)\b", p, re.I)), "")
    volume = re.search(r"\b(?:tome|volume)\s+(\d+)", tail, re.I)
    return Context(title=title, authors=(author,) if author else (), publisher=publisher,
                   year=years.group() if years else "", volume=volume.group(1) if volume else "")


def extract_fields(text: str) -> list[IsbnField]:
    code = mwparserfromhell.parse(text)
    result = []
    templates = code.filter_templates(recursive=True)
    position_cursor = {}
    for ti, template in enumerate(templates):
        template_name = name(str(template.name))
        param_names = [name(str(p.name)) for p in template.params]
        context = context_from_template(template)
        if template_name == "isbn" and not context.title:
            # L'ISBN peut être inclus dans une citation structurée ou être placé
            # après un titre en italique dans une liste bibliographique.
            for parent in reversed(templates[:ti]):
                if not any(id(n) == id(template) for p in parent.params for n in p.value.filter_templates(recursive=True)):
                    continue
                parent_context = context_from_template(parent)
                if parent_context.title:
                    in_isbn_param = any(_ISBN_PARAM.fullmatch(name(str(p.name))) and any(id(n) == id(template) for n in p.value.filter_templates(recursive=True)) for p in parent.params)
                    context = parent_context if in_isbn_param else Context(title=parent_context.title)
                    break
            if not context.title:
                rendered = str(template)
                position = text.find(rendered, position_cursor.get(rendered, 0))
                position_cursor[rendered] = position + len(rendered)
                if position >= 0:
                    context = context_from_line(text, position)
        for pi, param in enumerate(template.params):
            pn = param_names[pi]
            is_isbn = bool(_ISBN_PARAM.fullmatch(pn)) or (template_name == "isbn" and pn.isdigit())
            if not is_isbn:
                continue
            raw = str(param.value)
            restriction = ""
            if template_name not in _SUPPORTED:
                restriction = "Modèle non pris en charge pour la publication"
            elif param_names.count(pn) > 1:
                restriction = "Paramètre dupliqué dans le même modèle"
            elif any(token in raw for token in ("{{", "[[", "<!--", "<", "}}", "]]")):
                restriction = "Champ structuré/commenté : intervention manuelle"
            result.append(IsbnField(ti, pi, template_name, pn, raw, context, not restriction, restriction))
    return result


def replace_field(text: str, target: IsbnField, new_value: str) -> str:
    # Le texte doit provenir de la même révision ; index + nom + valeur vérifiés.
    if not target.editable:
        raise ValueError(target.restriction)
    code = mwparserfromhell.parse(text)
    templates = code.filter_templates(recursive=True)
    try:
        template = templates[target.template_index]
        param = template.params[target.parameter_index]
    except IndexError as exc:
        raise ValueError("Champ ISBN introuvable") from exc
    if (name(str(template.name)), name(str(param.name)), str(param.value)) != (
        target.template_name, target.parameter_name, target.raw_value
    ):
        raise ValueError("Le champ ISBN a changé")
    leading = re.match(r"\s*", target.raw_value).group()
    trailing = re.search(r"\s*$", target.raw_value).group()
    param.value = leading + new_value + trailing
    updated = str(code)
    # Garantit une seule substitution, sans normaliser le reste du wikitexte.
    expected_old = target.raw_value
    expected_new = leading + new_value + trailing
    before_template = str(mwparserfromhell.parse(text).filter_templates(recursive=True)[target.template_index])
    after_template = str(template)
    if before_template.count(expected_old) == 0 or updated == text:
        raise ValueError("Aucune modification minimale produite")
    if after_template != before_template.replace(expected_old, expected_new, 1):
        # Une occurrence identique dans un autre paramètre ne doit pas être modifiée.
        # Le contrôle AST ci-dessus reste la source de la substitution exacte.
        raise ValueError("Substitution ambiguë dans le modèle")
    return updated


def make_diff(before: str, after: str, title: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=title + " (avant)", tofile=title + " (proposition)",
    ))

