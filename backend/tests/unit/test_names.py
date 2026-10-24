"""Rule-based names and propagation."""
import pytest

from tests.conftest import found


def persons(spans):
    return [s.text for s in spans if s.entity == "PERSON"]


@pytest.mark.parametrize("text,name", [
    ("seen by Dr. Patel today", "Patel"), ("Mr. Johnson arrived", "Johnson"), ("Officer Daniel Ruiz", "Daniel Ruiz"),
    ("Det. Sarah O'Neil", "Sarah O'Neil"), ("Judge Maria De La Cruz presiding", "Maria De La Cruz"),
    ("Sgt. Ja'Marcus Williams", "Ja'Marcus Williams"), ("Dr. McDonald reviewed", "McDonald"),
    ("Mrs. Nevárez called", "Nevárez"), ("Ms. Łukasiewicz", "Łukasiewicz"), ("Dr. Patel Orthopedics", "Patel"),
    ("Trooper Hunter Wells", "Hunter Wells"),
])
def test_honorifics(rules, text, name):
    assert name in persons(rules(text)), found(rules(text))


@pytest.mark.parametrize("text,name", [("/s/ Jordan Brooks", "Jordan Brooks"), ("By: /s/ Inga Dukat\nState Bar No. 1", "Inga Dukat")])
def test_signatures(rules, text, name):
    spans = rules(text)
    assert name in persons(spans) and any(s.entity == "SIGNATURE" for s in spans)


def test_caption(rules):
    text = "CAUSE NO. 2023-CA-004821\n\nROBERT BROWN,\n     Plaintiff,\nv.\nNOÉMI VALETTE,\n     Defendant.\n"
    p = persons(rules(text))
    assert "ROBERT BROWN" in p and "NOÉMI VALETTE" in p


def test_case_style_single_names(rules):
    assert {"Santiago", "Navarro"} <= set(persons(rules("Case: Santiago v. Navarro, Cause No. 1")))


@pytest.mark.parametrize("text,name", [
    ("Independent witness Robert White, who saw it", "Robert White"), ("Supervisor Donna Smith has put", "Donna Smith"),
    ("his neighbor Will Price", "Will Price"),
])
def test_role_before_name(rules, text, name):
    assert name in persons(rules(text)), found(rules(text))


@pytest.mark.parametrize("text", ["Suspected Minor Injury, transported", "Client Signature: /s/", "registered nurse   Wage: $41.11",
                                  "the driver of Unit 2", "Store Manager"])
def test_role_word_false_positives(rules, text):
    assert not [p for p in persons(rules(text)) if p in ("Injury", "Signature", "Wage", "Unit", "Manager")]


def test_i_name_certificate(rules):
    assert "Rose Banks" in persons(rules("I, Rose Banks, Certified Shorthand Reporter No. 2974, certify"))


def test_name_comma_title(rules):
    assert "Keith Rhodes" in persons(rules("\nKeith Rhodes, Claims Adjuster\nState Farm"))


def test_minor_initials(rules):
    spans = rules("as Next Friend of C.S., a Minor,")
    assert "C.S." in persons(spans) and any(s.entity == "MINOR" for s in spans)


def test_payment_party(rules):
    assert "Alberto Nevárez" in persons(rules("Zelle Payment To Alberto Nevárez Jpm9670767874 $112.22"))


def test_name_above_address(rules):
    assert "RICHARD SANTIAGO" in persons(rules("RICHARD SANTIAGO\n17268 N Magnolia Bend Suite 3\nAustin, TX 78701"))


def test_propagation_surname_and_caps(rules):
    text = "Patient: Mary Johnson\n...\nLater Johnson reported pain. JOHNSON, MARY was discharged. Mrs. Johnson's husband"
    spans = rules(text)
    occ = [s for s in spans if s.entity == "PERSON"]
    covered = "".join(text[s.start:s.end] for s in occ)
    assert covered.count("Johnson") + covered.count("JOHNSON") >= 4


def test_propagation_skips_firm_names(rules):
    spans = rules("Plaintiff: Robert Brown\nFOR THE DEFENDANT: Brown & Kessler LLP")
    assert [s for s in spans if s.entity == "PERSON" and s.start > 30] == []


def test_left_extension_skips_common_words(rules):
    spans = rules("Spouse: Qushi Patel\nReports pain. Spouse Qushi has been helping.")
    assert all(not s.text.startswith("Spouse") for s in spans)


@pytest.mark.parametrize("text", ["The Patient Reported Pain", "Physical Therapy Daily Note", "Emergency Department",
                                  "Chief Complaint", "Plaintiff's Original Petition", "Respectfully Submitted"])
def test_title_case_phrases_not_people(rules, text):
    assert not persons(rules(text))


@pytest.mark.parametrize("text,minor", [("his daughter Emily, age 7", "Emily"), ("minor child Ethan", "Ethan"),
                                        ("Carol (6) was in the back", "Carol")])
def test_minor_flag(rules, text, minor):
    from obscura.detection.text import names
    from obscura.detection.text.base import Span
    i = text.index(minor)
    out = list(names.flag_minors(text, [Span(i, i + len(minor), "PERSON", 0.9, "t", minor)]))
    assert out and out[0].entity == "MINOR"


def test_parent_not_flagged_minor():
    from obscura.detection.text import names
    from obscura.detection.text.base import Span
    text = "Richard Santiago, Injury Severity: B — Suspected Minor Injury"
    assert not list(names.flag_minors(text, [Span(0, 16, "PERSON", 0.9, "t", "Richard Santiago")]))
