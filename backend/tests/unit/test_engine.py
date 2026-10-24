"""Fusion, conflicts, propagation, user rules, profiles and partial redaction."""
import pytest

from obscura.detection.text.engine import AnalyzeOptions, SearchTerm, TextAnalyzer, partial_ranges, restore_case
from obscura.detection.text.entities import ENTITIES, PROFILES, entities_for_profile
from tests.conftest import found


def test_specific_type_beats_generic_on_same_span(rules):
    spans = rules("Chart #: MR3566087")  # passes the DEA checksum by coincidence
    assert [(s.entity, s.text) for s in spans] == [("MRN", "MR3566087")]


def test_disabled_type_never_hides_enabled(rules):
    spans = rules("Chart #: MR3566087", entities={"MRN"})
    assert any(s.entity == "MRN" for s in spans)


def test_value_propagation_to_headers(rules):
    text = "MRN: 00483921\n" + "Progress note text.\n" * 5 + "Footer 00483921 page 2"
    assert sum(1 for s in rules(text) if s.text == "00483921") == 2


def test_formatted_value_propagation(rules):
    text = "SSN: 523-71-9921\nLater the form listed 523 71 9921 and 523719921."
    assert sum(1 for s in rules(text) if s.entity == "SSN") >= 3


def test_allow_list(rules):
    text = "Contact our firm: The Thompson Law Firm, P.C., 512-555-0101, or Dr. Thompson"
    spans = rules(text, allow_list=["512-555-0101", "Thompson"])
    assert "512-555-0101" not in [s.text for s in spans] and "Thompson" not in [s.text for s in spans]


@pytest.mark.parametrize("term,kw,expect", [
    (SearchTerm("Project Falcon"), {}, ["Project Falcon"]),
    (SearchTerm("falcon"), {}, ["Falcon"]),
    (SearchTerm("falcon", case_sensitive=True), {}, []),
    (SearchTerm("Falc", whole_word=True), {}, []),
    (SearchTerm("Falc", whole_word=False), {}, ["Falc"]),
    (SearchTerm(r"PRJ-\d{4}", regex=True), {}, ["PRJ-2231"]),
    (SearchTerm(r"code (\w+)", regex=True), {}, ["Zulu"]),
])
def test_user_terms(rules, term, kw, expect):
    text = "Internal: Project Falcon (PRJ-2231), code Zulu."
    got = [s.text for s in rules(text, terms=[term], entities={"CUSTOM"})]
    assert got == expect


def test_bad_regex_is_ignored(rules):
    assert rules("text", terms=[SearchTerm("(unclosed", regex=True)]) == []


def test_terms_never_echo_value_in_explanation(rules):
    spans = rules("John Q Public met us", terms=[SearchTerm("John Q Public", label="Client list")])
    assert spans and all("John Q Public" not in s.explanation for s in spans)


@pytest.mark.parametrize("text", ["Patient: Mary Johnson\nLater Johnson called.", "SSN 523-71-9921", "MRN: 00483921 again 00483921",
                                  "DOB: 01/02/1980", "Lives at 4417 Oakridge Dr, Austin, TX 78745"])
def test_explanations_never_contain_values(rules, text):
    for s in rules(text):
        v = s.text.strip()
        assert len(v) < 3 or v.lower() not in s.explanation.lower(), (s.entity, s.explanation)


@pytest.mark.parametrize("profile", list(PROFILES))
def test_profiles_resolve(profile):
    ents = entities_for_profile(profile)
    assert ents and ents <= set(ENTITIES)


def test_frcp_partial_rules(rules):
    spans = rules("SSN: 523-71-9921 DOB: 01/15/1980 Acct 48392011774", profile="frcp_5_2")
    by = {s.entity: s for s in spans}
    assert by["SSN"].meta["partial"] == "last4" and by["DATE_OF_BIRTH"].meta["partial"] == "year"


@pytest.mark.parametrize("value,rule,visible", [("523-71-9921", "last4", "9921"), ("4111 1111 1111 1234", "last4", "1234"),
                                                ("01/15/1980", "year", "1980"), ("January 15, 1980", "year", "1980"),
                                                ("Emily Rose Carter", "initials", "ERC")])
def test_partial_ranges(value, rule, visible):
    hidden = set()
    for a, b in partial_ranges(value, rule):
        hidden |= set(range(a, b))
    shown = "".join(c for i, c in enumerate(value) if i not in hidden and c.isalnum())
    assert shown == visible


def test_restore_case_preserves_length_and_offsets():
    t = "PATIENT: JOHNSON, MARY A   MRN: 00483921\nnormal line Stays"
    r = restore_case(t)
    assert len(r) == len(t) and r.startswith("Patient: Johnson, Mary A") and r.endswith("normal line Stays")


def test_ocr_rerun_is_not_a_second_source():
    from obscura.detection.text.base import Span
    text = "the night foreman at the mill"
    a, b = text.index("night"), text.index(" at")
    rule = Span(a, b, "INDIRECT_ROLE", 0.45, "descriptor:role", text[a:b])
    rerun = Span(a, b, "INDIRECT_ROLE", 0.42, "descriptor:role+ocr", text[a:b])
    [fused] = TextAnalyzer._fuse(text, [rule, rerun])
    assert fused.score == 0.45  # the same rule twice is one piece of evidence, not enough to reach 0.5
    other = Span(a, b, "INDIRECT_ROLE", 0.42, "quasi:role", text[a:b])
    [fused] = TextAnalyzer._fuse(text, [Span(a, b, "INDIRECT_ROLE", 0.45, "descriptor:role", text[a:b]), other])
    assert fused.score > 0.5  # an independent rule still adds


def test_thresholds_and_suggestions():
    an = TextAnalyzer()
    out = an.analyze("We met the manager yesterday.", AnalyzeOptions(use_spacy=False, use_gliner=False,
                                                                        include_suggestions=True))
    sugg = [s for s in out if not s.meta["selected"]]
    assert sugg and all(s.score < 0.5 for s in sugg)


def test_empty_and_whitespace(rules):
    assert rules("") == [] and rules("   \n\t ") == []


def test_huge_document_is_linear(rules):
    import time
    text = ("Patient: Mary Johnson  MRN: 00483921  DOB: 01/15/1980\nShe reports neck pain after the collision.\n" * 3000)
    t = time.perf_counter()
    spans = rules(text)
    assert time.perf_counter() - t < 30
    assert sum(1 for s in spans if s.text == "00483921") == 3000


def test_spans_are_sorted_and_within_bounds(rules):
    text = "Patient: JOHNSON, MARY  SSN 523-71-9921  Ph (512) 555-0187  mary@x.com"
    spans = rules(text)
    assert spans == sorted(spans, key=lambda s: (s.start, -s.end))
    for s in spans:
        assert 0 <= s.start < s.end <= len(text) and text[s.start:s.end] == s.text
