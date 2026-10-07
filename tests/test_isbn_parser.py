from dataclasses import replace

import pytest

from isbn_bot.isbn import candidate_seeds, classify, isbn10, isbn13, normalize_isbn, valid_isbn, valid_isbn10, valid_isbn13
from isbn_bot.parser import extract_fields, replace_field


@pytest.mark.parametrize("value", ["9780306406157", "978-0-306-40615-7", "0-306-40615-2", "080442957X", "0 8044 2957 x"])
def test_valid_isbn(value):
    assert valid_isbn(value)


@pytest.mark.parametrize("value", ["9780306406158", "0306406153", "4006381333931", "9790060115615", "hello9780306406157", "12345", "9780306406157 9780306406157"])
def test_not_isbn(value):
    assert not valid_isbn(value)


def test_labels_and_unicode_separators():
    assert normalize_isbn("ISBN-13 : 978‑0‑306‑40615‑7") == "9780306406157"
    assert isbn13("0306406152") == "9780306406157"


@pytest.mark.parametrize("raw,expected", [
    ("2025 978-0-306-40615-7", "EXTRA_TEXT"),
    ("ISBN 9780306406157", "EXTRA_TEXT"),
    ("9780306406157 / 9780743273565", "MULTIPLE_ISBN"),
    ("9780306406158", "BAD_CHECKSUM"),
    ("4006381333931", "EAN_AS_ISBN"),
    ("9790060115615", "ISMN_AS_ISBN"),
    ("1234567X", "ISSN_AS_ISBN"),
    ("", "EMPTY"),
])
def test_classification(raw, expected):
    assert classify(raw) == expected


def test_checksum_is_only_a_seed():
    assert candidate_seeds("9780306406158") == ["9780306406157", "0306406152"]


def test_a_year_cannot_consume_the_start_of_a_13_digit_isbn():
    assert classify("2025  978-2-07-523807-6") == "EXTRA_TEXT"
    assert candidate_seeds("2025  978-2-07-523807-6") == ["9782075238076", "2075238073"]
    assert isbn10("9780306406157") == "0306406152"


def test_nested_template_and_whitespace_are_preserved():
    text = "Avant <!-- conserver -->\n<ref>{{Ouvrage\n |titre=[[Livre test]]\n |auteur=Jane Exemple\n |isbn= 9780306406158 \n |note={{langue|fr}}\n}}</ref>\nAprès."
    field = extract_fields(text)[0]
    assert field.context.title == "Livre test"
    updated = replace_field(text, field, "9780306406157")
    assert updated == text.replace("9780306406158", "9780306406157")


def test_duplicate_parameters_are_not_publishable():
    fields = extract_fields("{{Ouvrage|titre=Test|isbn=9780306406158|isbn=9780743273566}}")
    assert len(fields) == 2
    assert all(not f.editable for f in fields)


@pytest.mark.parametrize("value", ["9780306406158<!-- note -->", "{{ISBN|9780306406158}}", "9780306406158<br/>"])
def test_structured_values_are_not_replaced(value):
    text = "{{Ouvrage|isbn=" + value + "}}"
    field = extract_fields(text)[0]
    assert not field.editable
    with pytest.raises(ValueError):
        replace_field(text, field, "9780306406157")


def test_unknown_template_is_readable_but_not_publishable():
    field = extract_fields("{{ModèleInconnu|titre=Test|isbn2=9780306406158}}")[0]
    assert field.parameter_name == "isbn2"
    assert not field.editable


def test_stale_field_value_rejected():
    text = "{{Ouvrage|isbn=9780306406158}}"
    field = extract_fields(text)[0]
    with pytest.raises(ValueError):
        replace_field(text.replace("6158", "6159"), field, "9780306406157")


def test_standalone_isbn_gets_context_from_its_bibliography_line():
    text = "1. ''Au large des Vîles, Dentelle'' tome 2, Gallimard jeunesse, {{ISBN|2025  978-2-07-523807-6}}"
    field = extract_fields(text)[0]
    assert field.context.title == "Au large des Vîles, Dentelle"
    assert field.context.publisher == "Gallimard jeunesse"
    assert field.context.volume == "2"


def test_nested_isbn_in_reprint_comment_does_not_inherit_original_year():
    text = "{{Écrit|titre=Test|année=2004|commentaire=Réédition en 2021 {{ISBN|9780306406158}}}}"
    field = extract_fields(text)[0]
    assert field.context.title == "Test"
    assert field.context.year == ""
