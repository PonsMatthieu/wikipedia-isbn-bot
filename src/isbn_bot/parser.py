import difflib
import re
from dataclasses import replace

import mwparserfromhell

from .models import Context, IsbnField

# Réécriture supervisée uniquement pour ces modèles connus.
_SUPPORTED = {"ouvrage", "cite book", "article", "cite journal", "isbn", "écrit"}
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
                prefix = text[text.rfind("\n", 0, position) + 1:position] if position >= 0 else ""
                titles = list(re.finditer(r"(?<!')''([^'\n]+)''(?!')", prefix))
                if titles:
                    last = titles[-1]
                    tail = plain(prefix[last.end():])
                    year_match = re.search(r"\b(?:1[5-9]|20)\d{2}\b", tail)
                    parts = [p.strip(" ,.;") for p in tail.split(",")]
                    publisher = next((p for p in parts if p and not re.search(r"\b(tome|volume|\d|p\.)", p, re.I)), "")
                    volume_match = re.search(r"\b(?:tome|volume)\s+(\d+)", tail, re.I)
                    context = Context(title=plain(last.group(1)).strip(" ,.;"), publisher=publisher,
                                      year=year_match.group() if year_match else "",
                                      volume=volume_match.group(1) if volume_match else "")
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
