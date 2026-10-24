"""ML named-entity recognition: spaCy transformer + GLiNER PII, both run locally.

Long documents are chunked on sentence/line boundaries with overlap so entities on chunk edges are
never lost, and offsets are mapped back to the full text.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from collections.abc import Iterator

from ... import config  # noqa: F401  (forces offline env before ML imports)
from ...config import MODELS_DIR, settings, torch_device
from .base import Span

log = logging.getLogger("obscura.ner")

from ..ml_lock import TORCH_LOCK as _lock  # shared with the vision models
_spacy = None
_spacy_name = None
_gliner = None
_gliner_name = None

# GLiNER label prompt -> Obscura entity
GLINER_LABELS: dict[str, str] = {
    "person": "PERSON",
    "first name": "PERSON",
    "last name": "PERSON",
    "name medical professional": "PERSON",
    "street address": "ADDRESS",
    "location address": "ADDRESS",
    "location street": "INDIRECT_LOCATION",
    "location city": "LOCATION",
    "date of birth": "DATE_OF_BIRTH",
    "phone number": "PHONE",
    "email address": "EMAIL",
    "social security number": "SSN",
    "credit card number": "CREDIT_CARD",
    "bank account number": "BANK_ACCOUNT",
    "driver license number": "DRIVERS_LICENSE",
    "passport number": "PASSPORT",
    "license plate": "LICENSE_PLATE",
    "medical record number": "MRN",
    "health insurance id": "HEALTH_PLAN_ID",
    "username": "USERNAME",
    "password": "PASSWORD",
    "organization": "ORGANIZATION",
    "employer": "EMPLOYER",
    "medical condition": "MEDICAL_CONDITION",
    "medication": "MEDICATION",
}
# entities that are worth asking GLiNER about — structured IDs are better served by validators
GLINER_DEFAULT_LABELS = ["person", "first name", "last name", "street address", "location city", "date of birth",
                         "organization", "employer", "medical condition", "medication"]

SPACY_MAP = {"PERSON": "PERSON", "ORG": "ORGANIZATION", "GPE": "LOCATION", "LOC": "LOCATION",
             "FAC": "INDIRECT_LOCATION", "DATE": "DATE", "NORP": "SPECIAL_CATEGORY"}


def _load_spacy():
    global _spacy, _spacy_name
    if _spacy is not None or not settings.spacy_model:
        return _spacy
    with _lock:
        if _spacy is None:
            import spacy
            name = settings.spacy_model
            try:
                _spacy = spacy.load(name, exclude=["lemmatizer"])
            except OSError:
                # en_core_web_lg was benchmarked and removed: ~10x the false positives of the transformer model
                log.warning("spaCy model %s missing; spaCy NER disabled", name)
                settings.spacy_model = ""
                return None
            _spacy.max_length = 5_000_000
            _spacy_name = name
    return _spacy


def _load_gliner():
    global _gliner, _gliner_name
    if _gliner is not None or not settings.gliner_model:
        return _gliner
    with _lock:
        if _gliner is None:
            import warnings
            warnings.filterwarnings("ignore")
            from gliner import GLiNER
            path = MODELS_DIR / "gliner" / settings.gliner_model
            m = GLiNER.from_pretrained(str(path), local_files_only=True)
            dev = torch_device()
            try:
                m = m.to(dev)
            except Exception:  # pragma: no cover
                m = m.to("cpu")
            m.eval()
            _gliner = m
            _gliner_name = settings.gliner_model
    return _gliner


def loaded_models() -> dict:
    return {"spacy": _spacy_name, "gliner": _gliner_name}


def chunk_text(text: str, max_chars: int, overlap: int) -> Iterator[tuple[int, str]]:
    """Yield (offset, chunk) pieces split on paragraph / sentence / line boundaries."""
    n = len(text)
    pos = 0
    while pos < n:
        end = min(n, pos + max_chars)
        if end < n:
            window = text[pos:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if cut > max_chars * 0.5:
                end = pos + cut + 1
        yield pos, text[pos:end]
        if end >= n:
            break
        pos = max(end - overlap, pos + 1)
        # start the next chunk at a word boundary
        while pos < n and pos > 0 and text[pos - 1].isalnum():
            pos += 1


# Parsed chunks of the most recent documents, so the Presidio second opinion reuses the spaCy pass the main engine
# just made instead of running the transformer twice. Transformer activations are dropped before caching.
_DOC_CACHE: OrderedDict[int, object] = OrderedDict()
_DOC_CACHE_CHARS = 400_000
_cache_lock = threading.Lock()


def _cache_get(chunk: str):
    with _cache_lock:
        doc = _DOC_CACHE.get(hash(chunk))
        if doc is not None and doc.text == chunk:
            _DOC_CACHE.move_to_end(hash(chunk))
            return doc
    return None


def _cache_put(chunk: str, doc) -> None:
    if doc.has_extension("trf_data"):
        doc._.trf_data = None
    with _cache_lock:
        _DOC_CACHE[hash(chunk)] = doc
        while len(_DOC_CACHE) > 1 and sum(len(d.text) for d in _DOC_CACHE.values()) > _DOC_CACHE_CHARS:
            _DOC_CACHE.popitem(last=False)


def spacy_docs(text: str) -> list[tuple[int, object]]:
    """(offset, spaCy Doc) for each chunk of text, from the cache when the chunk was just parsed."""
    nlp = _load_spacy()
    if nlp is None or not text.strip():
        return []
    chunks = list(chunk_text(text, 20000, 300))
    docs = [_cache_get(c) for _, c in chunks]
    todo = [i for i, d in enumerate(docs) if d is None]
    if todo:
        with _lock:
            fresh = list(nlp.pipe((chunks[i][1] for i in todo), batch_size=4))
        for i, d in zip(todo, fresh):
            _cache_put(chunks[i][1], d)
            docs[i] = d
    return [(off, d) for (off, _), d in zip(chunks, docs)]


def spacy_entities(text: str) -> list[Span]:
    if _load_spacy() is None or not text.strip():
        return []
    out: list[Span] = []
    for off, doc in spacy_docs(text):
        for ent in doc.ents:
            entity = SPACY_MAP.get(ent.label_)
            if not entity:
                continue
            s, e = off + ent.start_char, off + ent.end_char
            val = text[s:e]
            if entity == "PERSON":
                if not re.search(r"[A-Za-z]{2}", val) or val.isdigit():
                    continue
                # spaCy alone on a single token is weak evidence ("Sav", "Zelle"); agreement with GLiNER or a
                # rule lifts it above the threshold through score fusion
                score = 0.85 if len(val.split()) >= 2 else 0.48
            elif entity == "DATE":
                if not re.search(r"\d", val):
                    continue  # "yesterday", "two weeks" are not dates of anything
                score = 0.6
            elif entity == "SPECIAL_CATEGORY":
                score = 0.4
            elif entity == "INDIRECT_LOCATION":
                if re.match(r"(?i)unit\s*\d", val):
                    continue
                score = 0.4  # a bare facility/street name is context, not an identifier on its own
            else:
                score = 0.7
            out.append(Span(s, e, entity, score, f"ner:spacy:{ent.label_}", val, f"spaCy {ent.label_}"))
    return out


def gliner_entities(text: str, labels: list[str] | None = None, threshold: float = 0.35) -> list[Span]:
    model = _load_gliner()
    if model is None or not text.strip():
        return []
    labels = labels or GLINER_DEFAULT_LABELS
    chunks = [(off, c) for off, c in chunk_text(text, 1400, 200) if c.strip()]
    out: list[Span] = []
    batch = 8
    for i in range(0, len(chunks), batch):
        part = chunks[i:i + batch]
        with _lock:
            try:
                results = model.inference([c for _, c in part], labels, threshold=threshold, batch_size=batch)
            except AttributeError:  # older gliner API
                results = [model.predict_entities(c, labels, threshold=threshold) for _, c in part]
        for (off, _), ents in zip(part, results):
            for ent in ents:
                entity = GLINER_LABELS.get(ent["label"])
                if not entity:
                    continue
                s, e = off + ent["start"], off + ent["end"]
                score = float(ent["score"])
                out.append(Span(s, e, entity, 0.4 + 0.55 * score, f"ner:gliner:{ent['label']}", text[s:e],
                                f"GLiNER “{ent['label']}” ({score:.2f})"))
    return out


def merge_adjacent_people(text: str, spans: list[Span]) -> list[Span]:
    """GLiNER splits "first name" / "last name": join "Mary" + "Johnson" into one PERSON span. A comma only
    joins "DOE, JANE" (single-word surname first), never "Rose Banks, Certified Reporter"."""
    people = sorted((s for s in spans if s.entity == "PERSON"), key=lambda s: s.start)
    others = [s for s in spans if s.entity != "PERSON"]
    merged: list[Span] = []
    for sp in people:
        if merged:
            last = merged[-1]
            gap = text[last.end:sp.start]
            if 0 <= len(gap) <= 3 and re.fullmatch(r"[\s,.]*", gap) and "\n" not in gap and "   " not in gap and \
                    ("," not in gap or len(last.text.split()) == 1):
                merged[-1] = Span(last.start, max(last.end, sp.end), "PERSON", max(last.score, sp.score),
                                  last.source, text[last.start:max(last.end, sp.end)], last.explanation)
                continue
            if sp.start < last.end:
                if sp.end > last.end:
                    merged[-1] = Span(last.start, sp.end, "PERSON", max(last.score, sp.score), last.source,
                                      text[last.start:sp.end], last.explanation)
                continue
        merged.append(sp)
    return merged + others
