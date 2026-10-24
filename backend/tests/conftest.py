import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# every test run gets its own throwaway data directory (never the real one)
os.environ.setdefault("OBSCURA_DATA", tempfile.mkdtemp(prefix="obscura-test-"))
os.environ.setdefault("OBSCURA_WATCHER", "0")
os.environ.setdefault("OBSCURA_REQUIRE_LOGIN", "1")  # the API suites exercise sign-in; test_local_mode turns it off

import pytest  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def rules():
    """Rules-only analyzer (fast)."""
    from obscura.detection.text.engine import AnalyzeOptions, TextAnalyzer
    an = TextAnalyzer()

    def run(text, **kw):
        kw.setdefault("use_spacy", False)
        kw.setdefault("use_gliner", False)
        kw.setdefault("include_suggestions", False)
        return an.analyze(text, AnalyzeOptions(**kw))
    return run


@pytest.fixture(scope="session")
def ml():
    from obscura.detection.text.engine import AnalyzeOptions, TextAnalyzer
    an = TextAnalyzer()

    def run(text, **kw):
        kw.setdefault("include_suggestions", False)
        return an.analyze(text, AnalyzeOptions(**kw))
    return run


def found(spans, entity=None):
    return [(s.entity, s.text) for s in spans if entity is None or s.entity == entity]


def covers(spans, value, text=None):
    """True when the value (all its occurrences' first match) is fully covered by selected spans."""
    if text is None:
        return any(value in s.text for s in spans)
    i = text.find(value)
    assert i >= 0, f"{value!r} not in text"
    need = set(range(i, i + len(value))) - {k for k in range(i, i + len(value)) if text[k].isspace()}
    have = set()
    for s in spans:
        have |= set(range(s.start, s.end))
    return need <= have
