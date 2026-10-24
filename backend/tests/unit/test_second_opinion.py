"""Microsoft Presidio as a local second opinion: offline, mapped to Obscura types, never auto-redacting."""
import socket

import pytest

from obscura.detection.text import second_opinion as so
from obscura.detection.text.base import Span
from obscura.detection.text.entities import ENTITIES

pytestmark = pytest.mark.skipif(not so.installed(), reason="presidio-analyzer not installed")

TEXT = ("Patient Maria Delgado, SSN 523-71-9921, card 4111 1111 1111 1111, email maria.d@example.com, "
        "IBAN GB82 WEST 1234 5698 7654 32, DEA AB1234563, server 10.20.30.40.")


@pytest.fixture(scope="module")
def no_network():
    real = socket.socket.connect

    def refuse(*a, **k):
        raise AssertionError(f"network access attempted: {a}")
    socket.socket.connect = refuse
    yield
    socket.socket.connect = real


def test_builds_offline(no_network):
    st = so.status()
    assert st["available"], st
    assert not any("Azure" in r or "Transformers" in r for r in st["recognizers"])


def test_quick_status_never_builds():
    assert so.quick_status()["available"] in (True, False)


def test_tldextract_pinned_offline(no_network):
    so._analyzer()
    import tldextract
    assert getattr(tldextract.extract, "_obscura_offline", False)
    assert tldextract.extract("mail.example.co.uk").suffix == "co.uk"


@pytest.mark.parametrize("value,entity", [("523-71-9921", "SSN"), ("4111 1111 1111 1111", "CREDIT_CARD"),
                                          ("maria.d@example.com", "EMAIL"), ("GB82 WEST 1234 5698 7654 32", "IBAN"),
                                          ("AB1234563", "DEA_NUMBER"), ("10.20.30.40", "IP_ADDRESS")])
def test_pattern_recognizers(no_network, value, entity):
    found = {(sp.text, sp.entity) for sp in so.analyze(TEXT, nlp=False)}
    assert (value, entity) in found


def test_spans_point_at_the_original_text():
    for sp in so.analyze(TEXT, nlp=False):
        assert TEXT[sp.start:sp.end] == sp.text
        assert sp.source.startswith("presidio:")
        assert "Microsoft Presidio" in sp.explanation


def test_every_mapping_is_a_known_entity():
    assert set(so.ENTITY_MAP.values()) <= set(ENTITIES)


def test_uppercase_and_ocr_text_keep_offsets():
    t = "PATIENT: DELGADO, MARIA   SSN 523-7l-992l   PH0NE (512) 555-0187\n"
    for sp in so.analyze(t, nlp=False):
        assert t[sp.start:sp.end] == sp.text


def test_review_suggestions_skip_what_obscura_covered():
    ours = [Span(TEXT.index("523-71-9921"), TEXT.index("523-71-9921") + 11, "SSN", 0.99, "pattern:ssn")]
    sug = so.review_suggestions(TEXT, ours, set(ENTITIES), nlp=False)
    assert not any(s.text == "523-71-9921" for s in sug)
    assert any(s.text == "4111 1111 1111 1111" for s in sug)


def test_review_suggestions_are_unselected_and_flagged():
    sug = so.review_suggestions(TEXT, [], set(ENTITIES), nlp=False)
    assert sug and all(s.meta["selected"] is False and s.meta["second_opinion"] for s in sug)


def test_review_suggestions_respect_profile():
    sug = so.review_suggestions(TEXT, [], {"EMAIL"}, nlp=False)
    assert {s.entity for s in sug} == {"EMAIL"}


def test_noisy_spacy_dates_dropped():
    sug = so.review_suggestions("The visit lasted about 25 minutes on Tuesday.", [], set(ENTITIES))
    assert not any(s.entity == "DATE" and "SpacyRecognizer" in s.source for s in sug)


def test_check_output_clean_text():
    rep = so.check_output(["Patient [REDACTED] was seen for cervical strain. (b)(6)"], set(ENTITIES))
    assert rep["checked"] and rep["open"] == 0


def test_check_output_finds_leftovers():
    rep = so.check_output(["Call back at maria.d@example.com or card 4111 1111 1111 1111."], set(ENTITIES))
    assert rep["checked"] and rep["open"] >= 2
    assert {f["entity"] for f in rep["findings"]} >= {"EMAIL", "CREDIT_CARD"}
    assert all(f["page"] == 0 for f in rep["findings"])


def test_check_output_marks_reviewed_text():
    rep = so.check_output(["Contact maria.d@example.com"], set(ENTITIES), dismissed={"maria.d@example.com"})
    assert rep["open"] == 0 and rep["findings"][0]["reviewed"] is True


def test_check_output_page_numbers():
    rep = so.check_output(["nothing here", "email maria.d@example.com"], {"EMAIL"})
    assert [f["page"] for f in rep["findings"]] == [1]


def test_engine_option_adds_suggestions():
    from obscura.detection.text.engine import AnalyzeOptions, TextAnalyzer
    t = "Reach the claims desk at intake.desk@example.org about the file."
    base = TextAnalyzer().analyze(t, AnalyzeOptions(use_spacy=False, use_gliner=False, entities={"IP_ADDRESS"}))
    assert base == []
    with_so = TextAnalyzer().analyze(t, AnalyzeOptions(use_spacy=False, use_gliner=False, entities={"EMAIL"},
                                                       second_opinion=True))
    assert all(not s.meta.get("second_opinion") or not s.meta["selected"] for s in with_so)


def test_engine_option_off_by_default():
    from obscura.detection.text.engine import AnalyzeOptions
    assert AnalyzeOptions().second_opinion is False
