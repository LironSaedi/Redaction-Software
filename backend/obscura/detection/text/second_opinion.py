"""Second opinion: Microsoft Presidio (open source, MIT licence) re-reads the text after the main engine.

Presidio is an independent PII detector — its own regexes, checksums (credit card Luhn, IBAN, ABA routing, national
ID check digits), context-word scoring and spaCy NER. Anything it finds that the main engine did not cover is
surfaced for review, so a miss by one detector has a second chance to be caught.

Runs entirely on this computer:
* it is handed the spaCy pipeline Obscura already loaded (no second model, never ``spacy download``);
* tldextract is pinned to its bundled suffix list (it would otherwise fetch one from the internet);
* only Presidio's local recognizers are loaded — never the Azure / cloud ones.
"""
from __future__ import annotations

import importlib.util
import logging
import re
import threading

from .base import Span, blank_line_numbers, looks_ocr_noisy, ocr_clean_variant

log = logging.getLogger("obscura.second_opinion")

# Presidio entity -> Obscura entity
ENTITY_MAP = {
    "PERSON": "PERSON", "LOCATION": "LOCATION", "DATE_TIME": "DATE", "NRP": "SPECIAL_CATEGORY",
    "ORGANIZATION": "ORGANIZATION", "EMAIL_ADDRESS": "EMAIL", "PHONE_NUMBER": "PHONE", "URL": "URL",
    "IP_ADDRESS": "IP_ADDRESS", "CREDIT_CARD": "CREDIT_CARD", "CRYPTO": "CRYPTO_WALLET", "IBAN_CODE": "IBAN",
    "US_SSN": "SSN", "US_ITIN": "ITIN", "US_BANK_NUMBER": "BANK_ACCOUNT", "US_DRIVER_LICENSE": "DRIVERS_LICENSE",
    "US_PASSPORT": "PASSPORT", "ABA_ROUTING_NUMBER": "ROUTING_NUMBER", "MEDICAL_LICENSE": "DEA_NUMBER",
    "UK_NHS": "NATIONAL_ID", "UK_NINO": "NATIONAL_ID", "SG_NRIC_FIN": "NATIONAL_ID", "SG_UEN": "ID_NUMBER",
    "AU_ABN": "ID_NUMBER", "AU_ACN": "ID_NUMBER", "AU_TFN": "NATIONAL_ID", "AU_MEDICARE": "HEALTH_PLAN_ID",
    "IN_PAN": "NATIONAL_ID", "IN_AADHAAR": "NATIONAL_ID", "IN_VOTER": "NATIONAL_ID", "IN_PASSPORT": "PASSPORT",
    "IN_VEHICLE_REGISTRATION": "LICENSE_PLATE", "ES_NIF": "NATIONAL_ID", "ES_NIE": "NATIONAL_ID",
    "IT_FISCAL_CODE": "NATIONAL_ID", "IT_DRIVER_LICENSE": "DRIVERS_LICENSE", "IT_VAT_CODE": "ID_NUMBER",
    "IT_PASSPORT": "PASSPORT", "IT_IDENTITY_CARD": "NATIONAL_ID", "PL_PESEL": "NATIONAL_ID",
    "FI_PERSONAL_IDENTITY_CODE": "NATIONAL_ID",
}
# recognizers that call out to a service or load another large model: never used
_EXCLUDED = ("Azure", "Transformers", "Stanza", "Gliner")

_LOCK = threading.Lock()
_ANALYZER = None
_ERROR: str | None = None


def installed() -> bool:
    return importlib.util.find_spec("presidio_analyzer") is not None


def _offline_tldextract() -> None:
    import tldextract
    if not getattr(tldextract.extract, "_obscura_offline", False):
        ex = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
        ex._obscura_offline = True
        tldextract.extract = ex


def _analyzer():
    """Build Presidio once, wired to Obscura's own spaCy pipeline."""
    global _ANALYZER, _ERROR
    if _ANALYZER is not None or _ERROR is not None:
        return _ANALYZER
    with _LOCK:
        if _ANALYZER is not None or _ERROR is not None:
            return _ANALYZER
        try:
            _offline_tldextract()
            import spacy
            from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
            from presidio_analyzer.nlp_engine import SpacyNlpEngine

            class _SharedSpacy(SpacyNlpEngine):
                def load(self) -> None:  # never download or load a model of its own
                    raise RuntimeError("second opinion uses Obscura's spaCy pipeline")

            engine = _SharedSpacy(models=[{"lang_code": "en", "model_name": "obscura-shared"}])
            # only a tokenizer + stop-word vocabulary lives here; parsed Docs come from Obscura's own pipeline
            engine.nlp = {"en": spacy.blank("en")}
            registry = RecognizerRegistry(supported_languages=["en"])
            registry.load_predefined_recognizers(languages=["en"], nlp_engine=engine)
            # spaCy's people / places / dates come from the shared Doc (SpacyRecognizer only reads what the
            # pipeline produced)
            registry.recognizers = [r for r in registry.recognizers
                                    if not any(x in type(r).__name__ for x in _EXCLUDED)]
            _ANALYZER = AnalyzerEngine(registry=registry, nlp_engine=engine, supported_languages=["en"])
        except Exception as e:  # missing package or incompatible version: the second opinion is skipped
            _ERROR = f"{type(e).__name__}: {e}"
            log.warning("Presidio second opinion unavailable: %s", _ERROR)
    return _ANALYZER


def available() -> bool:
    return installed() and _analyzer() is not None


def status() -> dict:
    if not installed():
        return {"available": False, "reason": "presidio-analyzer is not installed"}
    a = _analyzer()
    if a is None:
        return {"available": False, "reason": _ERROR}
    from importlib.metadata import version
    return {"available": True, "version": version("presidio-analyzer"),
            "recognizers": sorted({type(r).__name__ for r in a.registry.recognizers})}


def quick_status() -> dict:
    """Availability without building the analyzer (for status pages)."""
    if not installed():
        return {"available": False, "reason": "presidio-analyzer is not installed"}
    if _ERROR:
        return {"available": False, "reason": _ERROR}
    from importlib.metadata import version
    return {"available": True, "version": version("presidio-analyzer")}


def _ml_text(text: str, ocr: bool | None) -> str:
    """The same normalised copy the main engine gives its NER models (same length, same offsets), so the spaCy
    pass is shared."""
    from .engine import restore_case
    base = blank_line_numbers(text)
    if ocr if ocr is not None else looks_ocr_noisy(text):
        base = ocr_clean_variant(base)
    return restore_case(base)


def analyze(text: str, min_score: float = 0.4, ocr: bool | None = None, entities: set[str] | None = None,
            nlp: bool = True) -> list[Span]:
    """Presidio's findings on text, as Obscura spans (source ``presidio:<Recognizer>``). With ``nlp`` the shared
    spaCy parse (people, places) is used; without it only Presidio's pattern / checksum recognizers run."""
    an = _analyzer()
    if an is None or not text.strip():
        return []
    from . import ner
    ml_text = _ml_text(text, ocr)
    engine = an.nlp_engine
    docs = ner.spacy_docs(ml_text) if nlp else []
    if not docs:
        blank = engine.nlp["en"]
        docs = [(off, blank.make_doc(chunk)) for off, chunk in ner.chunk_text(ml_text, 20000, 300)]
    out: list[Span] = []
    seen: set[tuple[int, int, str]] = set()
    for off, doc in docs:
        art = engine._doc_to_nlp_artifact(doc, "en")
        # the shared pipeline has no lemmatizer; lower-cased tokens keep Presidio's context words working
        art.lemmas = [lem or tok.lower_ for lem, tok in zip(art.lemmas, doc)]
        results = an.analyze(text=doc.text, language="en", nlp_artifacts=art, score_threshold=min_score)
        for r in results:
            ent = ENTITY_MAP.get(r.entity_type, "ID_NUMBER")
            if entities is not None and ent not in entities:
                continue
            s, e = off + r.start, off + r.end
            while e > s and text[e - 1] in " \t\n.,;:":
                e -= 1
            if e <= s or (s, e, ent) in seen:
                continue
            seen.add((s, e, ent))
            rec = (r.recognition_metadata or {}).get("recognizer_name", "Presidio")
            out.append(Span(s, e, ent, round(float(r.score), 3), f"presidio:{rec}", text[s:e],
                            f"Second opinion — Microsoft Presidio {rec} ({r.entity_type}, score {r.score:.2f})",
                            {"presidio_entity": r.entity_type}))
    out.sort(key=lambda sp: (sp.start, -sp.end))
    return out


def _covered(sp: Span, intervals: list[tuple[int, int]], text: str, need: float = 0.9) -> bool:
    chars = [i for i in range(sp.start, sp.end) if not text[i].isspace()]
    if not chars:
        return True
    hit = sum(1 for i in chars if any(a <= i < b for a, b in intervals))
    return hit / len(chars) >= need


def missed(text: str, spans: list[Span], **kw) -> list[Span]:
    """Presidio findings that the main engine's selected redactions do not already cover."""
    iv = [(s.start, s.end) for s in spans if s.meta.get("selected", True)]
    return [p for p in analyze(text, **kw) if not _covered(p, iv, text)]


# Presidio types that are mostly noise on legal / medical records: spaCy "DATE_TIME" includes durations and clock
# times ("~25 min", "06:00"); the pattern-based DateRecognizer is kept.
_NOISY = {("SpacyRecognizer", "DATE")}


def review_suggestions(text: str, spans: list[Span], enabled: set[str], ocr: bool | None = None,
                       nlp: bool = True) -> list[Span]:
    """Second-opinion findings to show the reviewer: types the profile redacts, not already covered by any of the main
    engine's spans (selected or suggested). They are added unselected — a person decides."""
    iv = [(s.start, s.end) for s in spans]
    out = []
    for p in analyze(text, ocr=ocr, nlp=nlp):
        rec = p.source.split(":", 1)[1]
        if p.entity not in enabled or (rec, p.entity) in _NOISY or _covered(p, iv, text):
            continue
        p.meta.update(selected=False, enabled_type=True, second_opinion=True)
        p.explanation = (f"Second opinion — Microsoft Presidio ({rec}, {p.meta['presidio_entity']}) flagged this and "
                         f"the main engine did not; review before release")
        out.append(p)
    return out


def check_output(pages: list[str], enabled: set[str], dismissed: set[str] | None = None,
                 limit: int = 200) -> dict:
    """Final check of a redacted export: anything in the released text that Presidio still recognises."""
    if not available():
        return {"checked": False, "reason": status().get("reason", "unavailable")}
    from importlib.metadata import version
    dismissed = {d.strip().lower() for d in (dismissed or set()) if d.strip()}
    findings = []
    for page, txt in enumerate(pages):
        for p in analyze(txt, nlp=True):
            rec = p.source.split(":", 1)[1]
            if p.entity not in enabled or (rec, p.entity) in _NOISY:
                continue
            if re.fullmatch(r"\[?(?:REDACTED|WITHHELD|PRIVILEGED)\]?|\(b\)\(\d+\)(?:\([A-F]\))?", p.text.strip(), re.I):
                continue
            low = p.text.strip().lower()
            reviewed = any(low == d or (len(low) >= 4 and (low in d or d in low)) for d in dismissed)
            findings.append({"page": page, "entity": p.entity, "text": p.text[:120], "score": p.score,
                             "recognizer": rec, "reviewed": reviewed})
    findings.sort(key=lambda f: (f["reviewed"], -f["score"]))
    return {"checked": True, "engine": f"Microsoft Presidio {version('presidio-analyzer')}", "count": len(findings),
            "open": sum(not f["reviewed"] for f in findings), "findings": findings[:limit]}
