"""Accuracy gates. A change that lowers recall below these numbers fails the build."""
import pytest

from obscura.detection.text.engine import AnalyzeOptions, TextAnalyzer
from obscura.detection.text.entities import entities_for_profile
from tests.accuracy.evaluate import evaluate
from tests.corpus.templates import case_file

STRUCTURED = ["SSN", "PHONE", "EMAIL", "DATE_OF_BIRTH", "MRN", "HEALTH_PLAN_ID", "CREDIT_CARD", "CVV", "CARD_EXPIRY",
              "ROUTING_NUMBER", "BANK_ACCOUNT", "VIN", "LICENSE_PLATE", "DRIVERS_LICENSE", "POLICY_NUMBER", "CLAIM_NUMBER",
              "MEDICARE_ID", "IBAN", "GPS", "PASSWORD", "USERNAME"]


def _run(seeds, opts, profile="standard"):
    docs = [d.to_dict() for s in seeds for d in case_file(s)]
    an = TextAnalyzer()
    preds = [an.analyze(d["text"], opts) for d in docs]
    return evaluate(docs, preds, entities_for_profile(profile))


@pytest.fixture(scope="module")
def rules_report():
    return _run([5001, 5002, 5003], AnalyzeOptions(use_spacy=False, use_gliner=False, include_suggestions=False))


def test_rules_overall(rules_report):
    assert rules_report.recall >= 0.99, rules_report.table()
    assert rules_report.precision >= 0.995, rules_report.table()
    assert len(rules_report.negative_hits) == 0, rules_report.negative_hits[:5]


@pytest.mark.parametrize("entity", STRUCTURED)
def test_structured_identifiers_perfect(rules_report, entity):
    st = rules_report.per_type.get(entity)
    if not st or not st.gold:
        pytest.skip(f"no {entity} in sample")
    assert st.caught == st.gold, st.misses[:3]


@pytest.mark.parametrize("entity,floor", [("PERSON", 0.98), ("ADDRESS", 0.98), ("INDIRECT_LOCATION", 0.95),
                                          ("EMPLOYER", 0.95), ("ID_NUMBER", 0.95)])
def test_soft_entities(rules_report, entity, floor):
    st = rules_report.per_type.get(entity)
    if not st or not st.gold:
        pytest.skip()
    assert st.caught / st.gold >= floor, st.misses[:5]


@pytest.mark.ml
@pytest.mark.slow
def test_ml_ensemble_overall():
    rep = _run([6001, 6002], AnalyzeOptions(include_suggestions=False))
    assert rep.recall >= 0.995, rep.table()
    assert rep.precision >= 0.99, rep.table()


@pytest.mark.ml
@pytest.mark.slow
@pytest.mark.parametrize("split,min_recall,min_precision", [("dev", 0.97, 0.97), ("dev2", 0.89, 0.97)])
def test_heldout_set(split, min_recall, min_precision):
    """Regression gates on the two development sets. The sealed test split (39–56) is deliberately not a test:
    gating on it would turn it into something the rules are tuned against."""
    from tests.heldout.load import load_all
    docs = load_all(split)
    if not docs:
        pytest.skip("held-out documents not present")
    an = TextAnalyzer()
    preds = [an.analyze(d["text"], AnalyzeOptions(include_suggestions=False)) for d in docs]
    rep = evaluate(docs, preds, entities_for_profile("standard"))
    assert rep.recall >= min_recall, rep.table()
    assert rep.precision >= min_precision, rep.table()
