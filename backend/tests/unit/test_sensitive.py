"""Sensitive medical / legal content."""
import pytest

from obscura.detection.text.base import Span
from obscura.detection.text.sensitive import expand_to_sentence
from tests.conftest import found

STRICT = {"profile": "strict"}


@pytest.mark.parametrize("text,entity", [
    ("history of opioid use disorder on Suboxone maintenance", "SUBSTANCE_USE"),
    ("attends AA meetings weekly", "SUBSTANCE_USE"), ("positive urine drug screen for cocaine", "SUBSTANCE_USE"),
    ("diagnosed with major depressive disorder", "MENTAL_HEALTH"), ("reports suicidal ideation without plan", "MENTAL_HEALTH"),
    ("PTSD since the collision", "MENTAL_HEALTH"), ("placed on a 5150 psychiatric hold", "MENTAL_HEALTH"),
    ("HIV positive, viral load undetectable", "SEXUAL_REPRODUCTIVE_HEALTH"), ("currently 14 weeks pregnant", "SEXUAL_REPRODUCTIVE_HEALTH"),
    ("history of elective abortion in 2019", "SEXUAL_REPRODUCTIVE_HEALTH"), ("treated for chlamydia", "SEXUAL_REPRODUCTIVE_HEALTH"),
    ("BRCA1 genetic testing was positive", "GENETIC"), ("receives SSDI for a permanent disability", "DISABILITY"),
    ("prescribed gabapentin 300 mg", "MEDICATION"), ("takes Xanax as needed", "MEDICATION"),
    ("type 2 diabetes and hypertension", "MEDICAL_CONDITION"), ("comminuted fracture of the left tibia", "INJURY"),
    ("underwent an ACDF at C5-6", "MEDICAL_PROCEDURE"), ("prior felony conviction for burglary", "CRIMINAL_HISTORY"),
    ("is an undocumented immigrant with a pending asylum case", "IMMIGRATION_STATUS"),
    ("she is a practicing Muslim", "SPECIAL_CATEGORY"), ("earns $24.86 per hour", "FINANCIAL_INFO"),
])
def test_sensitive_terms(rules, text, entity):
    spans = rules(f"Patient {text}.", **STRICT)
    assert any(s.entity == entity for s in spans), found(spans)


@pytest.mark.parametrize("text", ["HbA1c 7.2%", "glucose 182 mg/dL", "BP 142/91", "tested positive for COVID",
                                  "negative for THC", "CD4 count 450 cells/mm3", "results were positive for hepatitis C"])
def test_lab_results(rules, text):
    assert any(s.entity == "LAB_RESULT" for s in rules(f"Labs: {text}.", **STRICT)), found(rules(text, **STRICT))


@pytest.mark.parametrize("text", ["We will add more chairs.", "The mat was wet.", "He went to the ER for SI joint pain?",
                                  "She is single."])
def test_ambiguous_short_terms_need_cues(rules, text):
    spans = [s for s in rules(text, **STRICT) if s.entity in ("MENTAL_HEALTH", "SUBSTANCE_USE", "DISABILITY")]
    assert not [s for s in spans if s.text.lower() in ("add", "mat", "si")], found(spans)


def test_privilege_paragraph(rules):
    text = "Intro line.\n\nPRIVILEGED & CONFIDENTIAL - ATTORNEY WORK PRODUCT\nWe recommend settling for $85,000.\nMore advice.\n\nNext para."
    spans = [s for s in rules(text, **STRICT) if s.entity == "PRIVILEGED"]
    assert spans and "We recommend" in spans[0].text and "Next para" not in spans[0].text and "Intro" not in spans[0].text


@pytest.mark.parametrize("text,amount", [("we demand $250,000.00, the policy limits", "$250,000.00"),
                                         ("the adjuster offered $18,500", "$18,500"),
                                         ("settled for $1.2 million", "$1.2 million")])
def test_settlement_amounts(rules, text, amount):
    assert amount in [s.text for s in rules(text, **STRICT) if s.entity == "MONEY"], found(rules(text, **STRICT))


def test_sentence_mode(rules):
    text = "Seen today. Patient has a history of opioid use disorder and is on methadone. Return in 2 weeks."
    spans = rules(text, profile="medical_sensitive", sensitive_sentence_mode=True)
    sub = [s for s in spans if s.entity == "SUBSTANCE_USE"]
    assert sub and sub[0].text.startswith("Patient has a history") and sub[0].text.endswith("methadone.")


def test_expand_to_sentence():
    text = "A. B is here; C has HIV and D. E."
    i = text.index("HIV")
    a, b = expand_to_sentence(text, Span(i, i + 3, "X", 1, "t", "HIV"))
    assert text[a:b] == "C has HIV and D."


def test_standard_profile_keeps_injuries_visible(rules):
    spans = rules("Patient sustained a comminuted fracture of the left tibia.")
    assert not [s for s in spans if s.entity in ("INJURY", "MEDICAL_CONDITION")]
