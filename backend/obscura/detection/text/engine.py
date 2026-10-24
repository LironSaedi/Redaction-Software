"""Text analysis orchestrator.

Pipeline
--------
1. normalise text (invisible chars, dash/space/quote variants) with an exact offset map
2. pattern recognizers (+ second pass on an OCR digit-confusion variant for scanned text)
3. label/key-value recognizers (forms, tables)
4. rule-based names, addresses, indirect identifiers, sensitive content
5. ML NER (spaCy transformer + GLiNER PII) — chunked for long documents
6. filtering of known false-positive shapes
7. fusion: same-entity overlaps are unioned and scores combined (noisy-OR across independent
   sources); contained spans of less-specific types are pruned
8. propagation: every other occurrence of a detected name or identifier is flagged (headers,
   footers, page 40 surname-only mentions)
9. user rules: search terms, custom lists, regex patterns, allow-list
10. thresholding against the enabled entity set
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace

from ...config import settings
from . import addresses, descriptors, financial, labels, names, negatives, ner, patterns, quasi, sensitive
from .base import NormText, Span, blank_line_numbers, looks_ocr_noisy, ocr_clean_variant
from .entities import ENTITIES, PARTIAL_RULES, entities_for_profile

log = logging.getLogger("obscura.engine")


@dataclass
class SearchTerm:
    text: str
    entity: str = "CUSTOM"
    regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = True
    exemption: str | None = None
    label: str = ""


@dataclass
class AnalyzeOptions:
    entities: set[str] | None = None
    profile: str | None = None
    use_spacy: bool = True
    use_gliner: bool = True
    ocr_text: bool = False
    transcript: bool = False  # speech-to-text input: digit groups are arbitrary
    threshold: float = field(default_factory=lambda: settings.auto_threshold)
    suggest_threshold: float = field(default_factory=lambda: settings.suggest_threshold)
    terms: list[SearchTerm] = field(default_factory=list)
    allow_list: list[str] = field(default_factory=list)
    propagate: bool = True
    sensitive_sentence_mode: bool = False
    include_suggestions: bool = True
    second_opinion: bool = False  # Microsoft Presidio re-reads the text; its extra findings become suggestions

    def enabled(self) -> set[str]:
        if self.entities is not None:
            return set(self.entities) | {"CUSTOM"}
        return entities_for_profile(self.profile) | {"CUSTOM"}


# Rank: lower = more specific. Used to decide which label wins on identical spans.
_RANK = {e: 5 for e in ENTITIES}
for _e in ("SSN", "ITIN", "CREDIT_CARD", "IBAN", "ROUTING_NUMBER", "NPI", "DEA_NUMBER", "VIN", "EMAIL",
           "IP_ADDRESS", "MAC_ADDRESS", "CRYPTO_WALLET", "MEDICARE_ID", "GPS", "CVV", "CARD_EXPIRY"):
    _RANK[_e] = 1
for _e in ("MRN", "HEALTH_PLAN_ID", "CLAIM_NUMBER", "POLICY_NUMBER", "DRIVERS_LICENSE", "PASSPORT", "LICENSE_PLATE",
           "BANK_ACCOUNT", "CASE_NUMBER", "LAW_ENFORCEMENT_ID", "EIN", "NATIONAL_ID", "DEVICE_ID", "PASSWORD",
           "USERNAME", "DATE_OF_BIRTH", "PHONE"):
    _RANK[_e] = 2
for _e in ("PERSON", "ADDRESS", "SIGNATURE", "MINOR", "CUSTOM", "ID_NUMBER"):
    _RANK[_e] = 2
for _e in ("INDIRECT_LOCATION", "INDIRECT_ROLE", "EMPLOYER", "SCHOOL", "VEHICLE_DESCRIPTION", "PHYSICAL_DESCRIPTOR",
           "DEMOGRAPHIC", "AGE", "URL", "ZIP_CODE"):
    _RANK[_e] = 3
for _e in ("ORGANIZATION", "LOCATION", "DATE", "MONEY"):
    _RANK[_e] = 4

_COEXIST = {"MINOR", "SIGNATURE", "PRIVILEGED"}
_LABEL_SOURCES = {"label", "kv", "qa", "table", "user"}
# when a span of the key type contains a span of one of the value types, the inner span is dropped
# (abbreviations and words nobody is named: "Dawn Street", "Kim Lane", "Rose Way" are real names)
_STREET_TAILS = {"blvd", "boulevard", "ave", "avenue", "rd", "ln", "pkwy", "parkway", "hwy", "highway", "ct", "cir",
                 "trl", "expressway", "expy", "fwy", "freeway", "ter"}
_FORM_TOKEN = re.compile(r"(?i)(?:d\.?o\.?b\.?|ssn|mrn|dos|doi|dol|sex|age|gender|ht|wt|pt|id|dl|f|m|male|female|"
                         r"\d{1,3}\s*(?:y|yo|y/o|yrs?)|\d{1,3})[:.]?")
_SWALLOWS = {
    "ADDRESS": {"LOCATION", "ZIP_CODE", "INDIRECT_LOCATION", "ORGANIZATION", "DATE", "PERSON", "ID_NUMBER", "AGE"},
    "INDIRECT_LOCATION": {"ORGANIZATION", "LOCATION", "ZIP_CODE", "EMPLOYER", "INDIRECT_ROLE"},
    "INDIRECT_ROLE": {"ORGANIZATION", "LOCATION", "AGE"},
    "DATE_OF_BIRTH": {"DATE", "AGE"},
    "EMAIL": {"PERSON", "URL", "ORGANIZATION", "LOCATION", "USERNAME", "INDIRECT_LOCATION"},
    "URL": {"PERSON", "ORGANIZATION", "LOCATION", "USERNAME", "INDIRECT_LOCATION", "EMAIL", "DATE"},
    "DEMOGRAPHIC": {"AGE", "DATE", "SPECIAL_CATEGORY"},
    "VEHICLE_DESCRIPTION": {"ORGANIZATION", "DATE", "PERSON", "LOCATION"},
    "EMPLOYER": {"ORGANIZATION", "INDIRECT_LOCATION"},
    "SCHOOL": {"ORGANIZATION", "LOCATION", "INDIRECT_LOCATION", "PERSON"},
    "CARD_EXPIRY": {"DATE"},
    "LAB_RESULT": {"DATE", "MEDICAL_CONDITION", "SEXUAL_REPRODUCTIVE_HEALTH", "SUBSTANCE_USE"},
    "FINANCIAL_INFO": {"MONEY"},
    "PERSON": {"LOCATION", "ORGANIZATION", "DATE"},
    "CASE_NUMBER": {"DATE", "PHONE", "ID_NUMBER", "ZIP_CODE"},
    "MEDICAL_PROCEDURE": {"MEDICAL_CONDITION", "INJURY"},
}
_NUMERIC_IDS = {"SSN", "ITIN", "EIN", "CREDIT_CARD", "BANK_ACCOUNT", "ROUTING_NUMBER", "PHONE", "MRN",
                "HEALTH_PLAN_ID", "CLAIM_NUMBER", "POLICY_NUMBER", "CASE_NUMBER", "LAW_ENFORCEMENT_ID",
                "DRIVERS_LICENSE", "PASSPORT", "LICENSE_PLATE", "NPI", "DEA_NUMBER", "MEDICARE_ID", "ID_NUMBER",
                "NATIONAL_ID", "DEVICE_ID", "ZIP_CODE", "DATE", "VIN", "IBAN", "IP_ADDRESS"}

_STATES_COUNTRIES = re.compile(
    r"(?i)^(?:the\s+)?(?:" + addresses.STATE_NAMES + r"|U\.?S\.?A?\.?|United\s+States(?:\s+of\s+America)?|America|"
    r"Canada|Mexico|England|UK|United\s+Kingdom|" + addresses.STATE_ABBR + r")$")
_DRUGS_AND_TERMS = {t.lower() for t in sensitive.MEDICATIONS + sensitive.CONDITIONS + sensitive.PROCEDURES +
                    sensitive.INJURIES + sensitive.MENTAL_HEALTH}
_PARTICLES = {"de", "da", "del", "della", "di", "van", "von", "der", "den", "le", "la", "du", "bin", "ibn", "al", "el",
              "dos", "das", "y", "e", "st.", "ter", "ten", "op", "zu", "af", "av"}
_TITLE_TAIL = re.compile(r",?\s+(?:Store|Office|General|Assistant|Regional|Senior|Claims?|Shift|Night|Case|Account|"
                         r"Certified|Licensed|Registered|Court|Official)?\s*(?:Manager|Supervisor|Reporter|Adjuster|"
                         r"Technician|Specialist|Representative|Coordinator|Director|Officer|Clerk|Assistant|"
                         r"Shorthand\s+Reporter|Paralegal|Analyst|Examiner|Engineer|Surveyor|Developer|Accountant|"
                         r"Bookkeeper|Underwriter|Processor|Teller|Banker|Auditor|Consultant|Administrator|Associate|"
                         r"Programmer|Scientist|Operator|Installer|Inspector|Estimator)\b.*$", re.I)
# statement / ledger vocabulary glued to a name ("JOSEPH SANTORELLI WEB", "CHIDI OKONKWO MEMO", "Contingent NORA L ROSS")
_STMT_TAIL = {"WEB", "MEMO", "ID", "PPD", "CCD", "TEL", "ACH", "POS", "REF", "CONF", "TRN", "TXN", "ON", "VIA", "PMT",
              "PAYMENT", "XFER", "TFR", "DEP", "DEPOSIT", "CHK", "SAV", "ACCT", "IND", "CO", "ORIG", "BNF", "OBI", "EFX",
              "XPN", "TU", "TUC", "EXP", "AUTH", "DESC", "TRACE", "SEC", "FBO", "TTEE", "CUST"}
_LEAD_ROLE = {"CONTINGENT", "PRIMARY", "BENEFICIARY", "BENE", "PAYEE", "PAYER", "PAYOR", "TTEE", "TRUSTEE", "CUSTODIAN",
              "FBO", "ATTN", "EXECUTOR", "GRANTOR", "SETTLOR", "BORROWER", "CO-BORROWER", "COBORROWER", "GUARANTOR",
              "OWNER", "JOINT", "SPOUSE", "DEPENDENT", "STUDENT", "INSURED", "SUBSCRIBER", "MEMBER", "DEBTOR"}
_DEPARTMENT = re.compile(r"(?i)\b(?:operations|department|dept|services|desk|team|center|centre|unit|division|support|"
                         r"processing|servicing|collections|recovery|underwriting|compliance|payroll|billing|accounts)\s*$")
_PERSON_BAD = re.compile(r"(?i)^(?:dr|mr|mrs|ms|patient|plaintiff|defendant|pt|md|rn|np|pa|esq|q|a|re|cc|"
                         r"attn|sir|madam|counsel|your\s+honor|honor|the\s+court|court)\.?$")


class TextAnalyzer:
    """Thread-safe; ML models are loaded lazily and shared."""

    def analyze(self, text: str, options: AnalyzeOptions | None = None) -> list[Span]:
        opts = options or AnalyzeOptions()
        if not text or not text.strip():
            return []
        # deposition line numbers are blanked (same length) so wrapped phrases match; outputs keep `text`
        base = blank_line_numbers(text)
        nt = NormText(base)
        cands: list[Span] = []
        timings: dict[str, float] = {}

        def run(name: str, fn):
            t0 = time.perf_counter()
            res = list(fn())
            timings[name] = time.perf_counter() - t0
            cands.extend(res)

        def rule_pass(target: NormText) -> None:
            for finder in patterns.ALL_PATTERN_FINDERS:
                run(finder.__name__, lambda f=finder: f(target))
            if opts.transcript:
                run("transcript_numbers", lambda: patterns.find_transcript_numbers(target))
            for finder in labels.ALL_LABEL_FINDERS:
                run(finder.__name__, lambda f=finder: f(target))
            run("names", lambda: names.find_rule_names(target))
            run("addresses", lambda: addresses.find_addresses(target))
            run("indirect", lambda: quasi.find_indirect(target))
            run("places", lambda: quasi.find_more_places(target))
            run("descriptors", lambda: descriptors.find_descriptors(target))
            run("sensitive", lambda: sensitive.find_sensitive(target))
            run("financial", lambda: financial.find_financial(target))

        rule_pass(nt)
        ocr = opts.ocr_text or looks_ocr_noisy(text)
        ml_source = base
        match_nt = nt
        if ocr:
            # OCR output: run every rule again on a copy with "Ph0ne"/"2l0-455-09l2" style confusions undone.
            # Same length, so spans map 1:1 back onto the original characters.
            cleaned = ocr_clean_variant(base)
            if cleaned != base:
                before = len(cands)
                rule_pass(NormText(cleaned))
                for sp in cands[before:]:
                    sp.text = text[sp.start:sp.end]
                    sp.score -= 0.03
                    sp.source += "+ocr"
                ml_source = cleaned
                match_nt = NormText(cleaned)
        enabled = opts.enabled()
        ml_text = restore_case(ml_source)  # NER models are weak on ALL-CAPS; same length, same offsets
        if opts.use_spacy and settings.spacy_model:
            run("spacy", lambda: ner.spacy_entities(ml_text))
        if opts.use_gliner and settings.gliner_model:
            gl_labels = list(ner.GLINER_DEFAULT_LABELS)
            run("gliner", lambda: ner.gliner_entities(ml_text, gl_labels))
        # everything after detection works on the OCR-cleaned copy when there is one (same length, same
        # offsets) so filters see "Rosalind", not "R0salind"; output spans get the original characters back
        atext = match_nt.original
        for c in cands:
            c.text = atext[c.start:c.end]
        cands.extend(names.names_above_addresses(atext, [c for c in cands if c.entity == "ADDRESS"]))

        cands = [c for c in (self._clean(atext, c) for c in self._split_columns(atext, cands)) if c is not None]
        cands = ner.merge_adjacent_people(atext, cands)
        cands = self._person_filters(atext, cands)
        spans = self._fuse(atext, cands)

        if opts.propagate:
            spans = self._propagate(atext, match_nt, spans, opts)

        persons = [s for s in spans if s.entity == "PERSON" and s.score >= opts.threshold]
        spans.extend(names.flag_minors(atext, persons))
        for sp in spans:  # an electronic signature "/s/ Augustus W. Paine": the "/s/" is part of it
            if sp.entity == "SIGNATURE" and re.search(r"/s/[ \t]?$", atext[max(0, sp.start - 4):sp.start]):
                sp.start -= len(re.search(r"/s/[ \t]?$", atext[max(0, sp.start - 4):sp.start]).group())
                sp.text = atext[sp.start:sp.end]
        quasi.grow_locations(atext, spans)
        quasi.combine_risk(atext, spans)

        spans.extend(self._user_rules(atext, opts.terms))
        spans = self._apply_allow_list(atext, spans, opts.allow_list)

        if opts.sensitive_sentence_mode:
            for sp in spans:
                if sp.entity in sensitive.SENSITIVE_CONTENT_ENTITIES:
                    a, b = sensitive.expand_to_sentence(atext, sp)
                    sp.start, sp.end, sp.text = a, b, atext[a:b]
                    sp.meta["sentence"] = True

        spans = self._fuse(atext, spans)
        for sp in spans:
            sp.text = text[sp.start:sp.end]
        out: list[Span] = []
        for sp in spans:
            if sp.entity not in enabled:
                # a disabled type that won a label conflict must not hide an enabled one
                alt = next((e for e in sp.meta.get("alt_entities", []) if e in enabled), None)
                if alt:
                    sp.meta["alt_entities"] = [sp.entity] + [e for e in sp.meta["alt_entities"] if e != alt]
                    sp.entity = alt
            if sp.entity == "INDIRECT_LOCATION" and all(
                    src.startswith("ner:") for src in sp.meta.get("sources", [sp.source])):
                sp.score = min(sp.score, 0.45)  # bare street / facility names from NER alone stay suggestions
            if (opts.ocr_text and sp.entity == "PERSON" and " " not in sp.text.strip() and
                    all(src.startswith("ner:") for src in sp.meta.get("sources", [sp.source])) and
                    re.fullmatch(r"[ \t]*", atext[atext.rfind("\n", 0, sp.start) + 1:sp.start]) and
                    re.fullmatch(r"[ \t]*", atext[sp.end:(atext.find("\n", sp.end) + 1 or len(atext) + 1) - 1])):
                sp.score = min(sp.score, 0.45)  # a lone OCR'd word on its own line ("Vicit" axis label): review
            on = sp.entity in enabled
            if sp.score < opts.suggest_threshold:
                continue
            sp.meta["selected"] = bool(on and sp.score >= opts.threshold)
            sp.meta["enabled_type"] = on
            if not sp.meta["selected"] and not (opts.include_suggestions and on):
                continue
            rule = PARTIAL_RULES.get(opts.profile or "", {}).get(sp.entity)
            if rule:
                sp.meta["partial"] = rule
            out.append(sp)
        if opts.second_opinion and opts.include_suggestions:
            from . import second_opinion
            t0 = time.perf_counter()
            try:
                out.extend(second_opinion.review_suggestions(text, out, enabled, ocr=ocr,
                                                             nlp=bool(opts.use_spacy and settings.spacy_model)))
            except Exception as e:  # the second opinion must never break the main analysis
                log.warning("second opinion failed: %s", e)
            timings["second_opinion"] = time.perf_counter() - t0
        out.sort(key=lambda s: (s.start, -s.end))
        self.last_timings = timings
        return out

    # -----------------------------------------------------------------------------------------

    @staticmethod
    def _split_columns(text: str, cands: list[Span]) -> list[Span]:
        """A person span that crosses a column gap ("BANKS, ROSE MARIE   F   70Y   DOB") is split into its
        pieces; pieces that are form labels / sex / age are dropped."""
        out: list[Span] = []
        for c in cands:
            if c.entity != "PERSON" or not re.search(r"[ \t]{3,}|\t", text[c.start:c.end]):
                out.append(c)
                continue
            pos = c.start
            for piece in re.split(r"([ \t]{3,}|\t)", text[c.start:c.end]):
                a, pos = pos, pos + len(piece)
                v = piece.strip()
                if not v or re.fullmatch(r"[ \t]+", piece) or _FORM_TOKEN.fullmatch(v):
                    continue
                lead = len(piece) - len(piece.lstrip())
                b = a + lead + len(v)
                if b < len(text) and text[b].isalpha() or v.lower() in names.HARD_STOP:
                    continue  # a cut-off word ("Bad" of "Badge") or a label is not a name piece
                out.append(dc_replace(c, start=a + lead, end=a + lead + len(v), text=v, meta=dict(c.meta)))
        return out

    @staticmethod
    def _person_filters(text: str, cands: list[Span]) -> list[Span]:
        """Drop public / non-personal "names" (case citations, eponyms, titles) and complete partial names
        (initials, "LAST, I", Jr./III) so the whole name is redacted."""
        protected = negatives.protected_ranges(text)
        out = []
        for sp in cands:
            if sp.entity not in ("PERSON", "MINOR", "SIGNATURE"):
                out.append(sp)
                continue
            if sp.entity == "PERSON" and not sp.source.startswith(("kv:", "rule:caption", "label")) and any(
                    a <= sp.start and sp.end <= b for a, b, _ in protected):
                continue
            why = sp.entity == "PERSON" and negatives.is_not_a_person(text, sp.start, sp.end)
            explicit = sp.source.startswith(("rule:nickname", "rule:spelled_name", "rule:initials"))
            if why and not (why == "abbreviation" and (explicit or sp.source.startswith(("kv:", "rule:caption", "label")))) \
                    and not (explicit and why in ("job title / credential", "legal role")):
                continue  # a quoted alias ("ROZ") is short and upper-case but still a name
            # strip trailing credentials: "Linda Marquez-Ochoa, RN, BSN, CLCP" -> "Linda Marquez-Ochoa"
            m = re.search(r"(?:,?\s+(?:" + "|".join(sorted((re.escape(c) for c in negatives.CREDENTIALS if c not in
                                                             ("ii", "iii")), key=len, reverse=True)) +
                          r")\.?)+\s*$", text[sp.start:sp.end], re.I)
            if m and m.start() > 0:
                sp.end = sp.start + m.start()
            # extend left over initials: "M. E. Delgado-Ruiz", "C. Abernathy"
            while True:
                lm = re.search(r"(?<![\w.])([A-Z]\.\s?)$", text[max(0, sp.start - 4):sp.start])
                if not lm:
                    break
                sp.start -= len(text[max(0, sp.start - 4):sp.start]) - lm.start(1)
            after = text[sp.end:sp.end + 16]
            # "GARZA-YBARRA, L" / "DOYLE, M" / "KOWALCZYK, L.R." / "NGUYEN, THANH V."
            rm = re.match(r",\s?(?:[A-Z]\.?){1,3}(?=[\s,;)#]|$)", after) if text[sp.start:sp.end].isupper() else None
            if not rm:
                rm = re.match(r"\s(?:[A-Z]\.)(?=[\s,;)]|$)", after) if text[sp.start:sp.end].count(" ") >= 1 else None
            if not rm and re.fullmatch(r"[A-Z'’-]+,\s+[A-Z][A-Z'’ -]*", text[sp.start:sp.end]):
                rm = re.match(r"\s[A-Z](?=[\s,;)(]|$)", after)  # "DELGADO-RUIZ, MARIA E" — middle initial
            if rm:
                sp.end += rm.end()
                after = text[sp.end:sp.end + 16]
            sm = re.match(r",?\s(?:Jr\.?|Sr\.?|JR\.?|SR\.?|II|III|IV)(?![\w])", after)
            if sm:
                sp.end += sm.end()
            # joint filers: "PARK, HYUN WOO & JI EUN" — the second given name shares the surname
            cur = text[sp.start:sp.end]
            if re.fullmatch(r"[A-Z'’-]+,\s+[A-Z][A-Z'’ -]+", cur):
                jm = re.match(r"(?:\s[A-Z][A-Z'’-]+){0,2}\s+(?:&|AND)\s+([A-Z][A-Z'’-]+(?:\s[A-Z][A-Z'’-]*)?)(?![\w])",
                              text[sp.end:sp.end + 50])
                if jm and jm.group(1).split()[0].lower() not in names.HARD_STOP:
                    sp.end += jm.end()
            sp.text = text[sp.start:sp.end]
            out.append(sp)
        return out

    @staticmethod
    def _clean(text: str, sp: Span) -> Span | None:
        s, e = sp.start, sp.end
        while s < e and (text[s] in " \t\n,;:\"'" or (text[s] == "(" and ")" not in text[s:e])):
            s += 1
        # a closing quote stays when it closes one inside the span: 'TAT R FARM "LUPE"'
        while e > s and (text[e - 1] in " \t\n,;:" or (text[e - 1] in "\"'" and text.count(text[e - 1], s, e - 1) % 2 == 0)
                         or (text[e - 1] == ")" and "(" not in text[s:e])):
            e -= 1
        if sp.entity not in ("CARD_EXPIRY",) and e > s and text[e - 1] == "." and not re.search(
                r"(?:\b[A-Z]|Jr|Sr|St|Ave|Blvd|Dr|Rd|Ln|Ct|Inc|Co|Corp|Ltd|Apt|Ste|No|M\.D|D\.O|Ph\.D)\.$", text[s:e]):
            e -= 1
        if e <= s:
            return None
        sp.start, sp.end, sp.text = s, e, text[s:e]
        v = sp.text
        if sp.entity == "PERSON":
            v2 = re.sub(r"['’]s$", "", v)
            if v2 != v:
                sp.end -= len(v) - len(v2)
                v = sp.text = v2
            hm = re.match(r"(?:" + names.HONORIFICS + r")\.?\s+", v)
            if hm and len(v) > hm.end():
                sp.start += hm.end()
                v = sp.text = text[sp.start:sp.end]
            initials = bool(re.fullmatch(r"(?:[A-Z]\.\s?){2,3}", v))
            if (initials or re.fullmatch(r"[A-Z]\.", v)) and sp.source.startswith(("rule:minor", "rule:initials",
                                                                                   "rule:nickname")):
                return sp  # "C.S., a Minor", "dropping H. off", "\"J.L.,\" as everyone knew him" — still a person
            if sp.source.startswith("rule:nickname") and re.fullmatch(r"[A-Z][A-Za-z.'’ -]{1,40}", v):
                return sp  # a quoted alias ("Junior", "BIG RAY") is a name even when it is also a word
            if sp.source.startswith(("rule:spelled_name", "rule:name_no_last")):
                return sp  # "P-A-R-K", "H-Y-U-N, hyphen, W-O-O"; OCR'd "0rnar (I dont know last name"
            if (not re.search(r"[A-Za-z]{2}", v) or re.search(r"\d", v) or v.islower() or _PERSON_BAD.match(v)
                    or _FORM_TOKEN.fullmatch(v)
                    or v.lower() in _DRUGS_AND_TERMS or v.lower() in names.HARD_STOP
                    or len(v) > 60 or v.count("\n") > 1):
                return None
            if labels._ORG_WORDS.search(v) and sp.source.startswith("ner:") or re.search(
                    r"(?i)\b(?:LLC|L\.L\.C\.?|Inc\.?|Corp\.?|Corporation|Ltd\.?|LLP|PLLC|P\.C\.|N\.A\.|GmbH)(?![\w])", v):
                sp.entity = "ORGANIZATION"  # a person's name never carries a corporate suffix
                sp.score = min(sp.score, 0.6)
            words = v.split()
            # trim ledger codes and role words glued to either end of the name
            while len(words) > 1 and words[-1].upper().strip(".,:") in _STMT_TAIL:
                sp.end = sp.start + text[sp.start:sp.end].rstrip().rfind(words[-1])
                sp.end = sp.start + len(text[sp.start:sp.end].rstrip())
                words = words[:-1]
            while len(words) > 1 and words[0].upper().strip(".,:") in _LEAD_ROLE:
                cut = text.find(words[1], sp.start + len(words[0]))
                sp.start = cut
                words = words[1:]
            v = sp.text = text[sp.start:sp.end]
            if all(w.upper().strip(".,:") in _STMT_TAIL for w in words) or _DEPARTMENT.search(v):
                return None  # "EFX XPN TU" (credit-bureau columns), "Deposit Operations" (a department)
            if all(w.lower().strip(".,") in names.HARD_STOP for w in words):
                return None
            if words[0].lower() in ("my", "his", "her", "our", "their", "your", "its"):
                return None  # "My Medicaid Member Eid" — a possessive phrase, not a name
            if len(words) >= 2 and words[-1].lower().strip(".") in _STREET_TAILS:
                return None  # "Ben White Blvd" — a street named after someone
            # names are capitalised word by word (particles excepted): "HVAC technician" is a job, not a person
            if any(w[0].islower() and w.lower() not in _PARTICLES for w in words if w[0].isalpha()):
                return None
            # "TEX. R. EVID", "Fed. R. Civ. P." — citation abbreviations
            if v.count(".") >= 2 and all(len(w.strip(".,")) <= 5 for w in words) and \
                    sum(w.endswith(".") for w in words) >= len(words) - 1:
                return None  # ("Rosa A. Tzul X." has whole words between its initials: a name)
            # trailing job title glued on by fusion: "Donna Smith, Store Manager"
            cut = _TITLE_TAIL.search(v)
            if cut and cut.start() == 0:
                return None  # the whole span is a job title ("Store Manager", "Certified Shorthand Reporter")
            if sp.source.startswith("ner:") and len(words) == 1 and re.match(
                    r"\s*(?:&\s+[A-Z]|(?:Shorthand|Manager|Reporter|Supervisor|LLP|LLC|Inc|PLLC|P\.C\.)\b)", text[sp.end:sp.end + 16]):
                return None  # "Brown & Kessler LLP", "Store Manager", "Certified Shorthand Reporter"
            if cut and cut.start() > 0:
                sp.end = sp.start + cut.start()
                sp.text = text[sp.start:sp.end]
                v = sp.text
        elif sp.entity == "ADDRESS" and sp.source.startswith("ner:") and not re.search(r"[A-Za-z]{3}", v):
            return None  # "72125      0450" — code columns, not an address
        elif sp.entity == "ADDRESS" and sp.source.startswith("ner:") and re.search(
                r"(?i)\b(?:co\.?|county)\s+\d+(?:st|nd|rd|th)\b|\b\d+(?:st|nd|rd|th)\s+(?:district|judicial|court)", v):
            return None  # "Travis Co 345th" — a court, not an address
        elif sp.entity == "ADDRESS" and sp.source.startswith("ner:") and not re.search(r"\d|(?i:box)", v):
            sp.entity, sp.score = "INDIRECT_LOCATION", min(sp.score, 0.45)  # a bare street name
        elif sp.entity == "EMPLOYER" and sp.source.startswith("ner:") and (
                _TITLE_TAIL.match(v) or all(w.lower().strip(".,") in negatives.OCCUPATION_WORDS for w in v.split())):
            return None  # "Assistant Principal" — a job title, not an employer
        elif sp.entity == "DATE_OF_BIRTH" and sp.source.startswith("ner:"):
            if not re.search(r"\d{1,2}[/.-]\d{1,2}|(?i:" + patterns.MONTHS + r")", v):
                return None  # a bare year is not a birth date
        elif sp.entity == "LOCATION":
            if _STATES_COUNTRIES.match(v):
                sp.score = min(sp.score, 0.3)  # HIPAA permits state; country is never identifying
            if v.lower() in _DRUGS_AND_TERMS or v.islower():
                return None
        elif sp.entity == "DATE" and sp.source.startswith("ner:spacy"):
            if not re.search(r"(?i)" + patterns.MONTHS + r"|\b(?:19|20)\d{2}\b|\d{1,2}/\d{1,2}", v):
                return None
            if re.search(r"(?i)\b(?:years?|months?|weeks?|days?|hours?|old|ago|later|prior|after|before)\b", v):
                return None
        elif sp.entity == "EMPLOYER" and sp.source.startswith("ner:"):
            if quasi._AGENCY.search(v) and quasi._OFFICIAL_CTX.search(text[max(0, sp.start - 150):sp.end + 80]):
                return None
        elif sp.entity == "ORGANIZATION":
            if v.lower() in _DRUGS_AND_TERMS or len(v) < 2 or v.islower():
                return None
        return sp

    @staticmethod
    def _family(source: str) -> str:
        # "descriptor:role+ocr" is the same rule re-run on the OCR-cleaned copy, not independent evidence
        source = source.removesuffix("+ocr")
        return ":".join(source.split(":")[:2])

    @staticmethod
    def _fuse(text: str, cands: list[Span]) -> list[Span]:
        # 1) union overlapping spans of the same entity, combining scores across sources
        by_ent: dict[str, list[Span]] = {}
        for c in cands:
            by_ent.setdefault(c.entity, []).append(c)
        fused: list[Span] = []
        for ent, group in by_ent.items():
            group.sort(key=lambda s: (s.start, -s.end))
            cur: Span | None = None
            srcs: set[str] = set()
            for sp in group:
                touching = cur is not None and (sp.start < cur.end or (
                    ent in ("ADDRESS", "PRIVILEGED", "INDIRECT_LOCATION") and sp.start <= cur.end + 1))
                if touching:
                    new_end = max(cur.end, sp.end)
                    fam = TextAnalyzer._family(sp.source)
                    if fam not in srcs:
                        cur.score = 1 - (1 - cur.score) * (1 - sp.score * 0.6) if sp.score > 0.3 else cur.score
                        srcs.add(fam)
                    cur.score = max(cur.score, sp.score)
                    if sp.end > cur.end and sp.score > cur.score - 0.25:
                        cur.end = new_end
                    elif sp.end > cur.end and ent in ("ADDRESS", "PERSON", "INDIRECT_LOCATION"):
                        cur.end = new_end
                    cur.text = text[cur.start:cur.end]
                    if sp.explanation and sp.explanation not in cur.explanation and len(cur.explanation) < 300:
                        cur.explanation += "; " + sp.explanation
                    cur.meta.setdefault("sources", [cur.source])
                    if sp.source not in cur.meta["sources"]:
                        cur.meta["sources"].append(sp.source)
                    for k, v in sp.meta.items():
                        cur.meta.setdefault(k, v)
                else:
                    if cur:
                        fused.append(cur)
                    cur = Span(sp.start, sp.end, sp.entity, sp.score, sp.source, sp.text, sp.explanation,
                               dict(sp.meta))
                    fam = TextAnalyzer._family(sp.source)
                    srcs = {fam}
            if cur:
                fused.append(cur)
        fused = [min(1, f.score) and f for f in fused]
        for f in fused:
            f.score = min(f.score, 0.995)

        # 2) prune contained / identical spans of other entities
        fused.sort(key=lambda s: (s.start, -(s.end - s.start)))
        keep = [True] * len(fused)
        for i, a in enumerate(fused):
            if not keep[i]:
                continue
            for j in range(i + 1, len(fused)):
                b = fused[j]
                if b.start >= a.end:
                    break
                if not keep[j] or b.entity == a.entity:
                    continue
                if a.entity in _COEXIST or b.entity in _COEXIST:
                    continue
                same = a.start == b.start and a.end == b.end
                if same:
                    # the more specific type wins when both are credible; evidence (score) is pooled into it
                    def key(x: Span) -> tuple:
                        labelled = x.entity != "ID_NUMBER" and any(
                            src.split(":")[0] in _LABEL_SOURCES for src in x.meta.get("sources", [x.source]))
                        return (_RANK[x.entity] - (1.5 if labelled else 0) if x.score >= 0.5 else _RANK[x.entity] + 10,
                                -x.score)
                    winner, loser = (i, j) if key(a) <= key(b) else (j, i)
                    w, l_ = fused[winner], fused[loser]
                    w.score = max(a.score, b.score)
                    alts = w.meta.setdefault("alt_entities", [])
                    for e in [l_.entity] + l_.meta.get("alt_entities", []):
                        if e != w.entity and e not in alts:
                            alts.append(e)
                    keep[loser] = False
                    if loser == i:
                        break
                    continue
                # a weak suggestion (e.g. a 0.45 "V1 Grace Hill" address guess) never swallows a confident span
                if a.contains(b):
                    if b.entity in _SWALLOWS.get(a.entity, ()) and (a.score >= 0.5 or a.score >= b.score):
                        keep[j] = False
                    elif b.entity in _NUMERIC_IDS and a.entity in _NUMERIC_IDS and a.score >= b.score:
                        keep[j] = False
                elif b.contains(a):
                    if a.entity in _SWALLOWS.get(b.entity, ()) and (b.score >= 0.5 or b.score >= a.score):
                        keep[i] = False
                        break
        return [f for f, k in zip(fused, keep) if k]

    @staticmethod
    def _propagate(text: str, nt: NormText, spans: list[Span], opts: AnalyzeOptions) -> list[Span]:
        """Find other mentions of detected values. ``nt`` may be the OCR-cleaned copy of ``text`` (same
        length), so "R0salind" in one place and "Rosa1ind" in another both match the cleaned "Rosalind"."""
        extra: list[Span] = []
        orig, text = text, nt.original
        people = [dc_replace(s, text=text[s.start:s.end]) for s in spans
                  if s.entity == "PERSON" and s.score >= max(opts.threshold, 0.6)]
        for p in people:
            if "rule:spelled_name" in p.meta.get("sources", [p.source]) and re.fullmatch(r"[A-Z, \-a-z]+", p.text):
                # "P-A-R-K" also identifies "Park" elsewhere; "H-Y-U-N, hyphen, W-O-O" → "Hyun-Woo"
                parts = [re.sub(r"[^A-Z]", "", g).title() for g in re.split(r",\s*hyphen,\s*", p.text)]
                p.text = "-".join(x for x in parts if x)
        if people:
            common = {s.text.lower() for s in spans if s.entity in ("ORGANIZATION", "LOCATION", "MEDICATION",
                                                                    "MEDICAL_CONDITION")}
            for sp in names.propagate_names(nt, people, common):
                extra.append(sp)
        # every other occurrence of a detected identifier value
        values: dict[str, Span] = {}
        for s in spans:
            if s.score < opts.threshold or s.entity in ("PERSON", "DATE", "LOCATION", "ORGANIZATION", "MONEY", "PRIVILEGED",
                                                        "INDIRECT_LOCATION", "INDIRECT_ROLE", "PHYSICAL_DESCRIPTOR",
                                                        "VEHICLE_DESCRIPTION", "DEMOGRAPHIC", "AGE", "MINOR",
                                                        "SIGNATURE") or s.entity in sensitive.SENSITIVE_CONTENT_ENTITIES:
                continue
            v = text[s.start:s.end].strip()
            if len(v) < 4 or (not re.search(r"\d", v) and len(v.split()) < 2):
                continue
            if s.meta.get("partial"):
                continue
            values.setdefault(v, s)
        # context-dependent indirect values propagate in a narrower form
        corp = re.compile(r"(?i)[,\s]+(?:LLC|L\.L\.C\.?|Inc\.?|Corp\.?|Corporation|Co\.?|Company|Ltd\.?|LLP|PLLC|P\.C\.|Group|"
                          r"Services|Holdings|Enterprises)\s*$")
        for s in spans:
            if s.score < opts.threshold:
                continue
            core = None
            stext = text[s.start:s.end]
            if s.entity == "EMPLOYER":
                core = corp.sub("", stext).strip()
                # "Swiftline Freight LLC" / "Caliche Transport" are also called "Swiftline" / "Caliche"
                short = re.sub(r"(?i)\s+(?:freight|transport(?:ation)?|trucking|logistics|construction|aggregates|"
                               r"industries|manufacturing|fabricators|enterprises|solutions|staffing|carriers|"
                               r"express|lines)\b.*$", "", core).strip()
                if short != core and len(short) >= 4 and short.lower() not in names.NON_NAME_WORDS:
                    core = short
                core = core if core != stext.strip() else (core if re.fullmatch(r"[A-Z][a-z]{4,}", core) and
                                                           not re.search(r"\b" + core.lower() + r"\b", text) else None)
            elif s.entity == "INDIRECT_LOCATION" and s.meta.get("core"):
                core = s.meta["core"]
            elif s.entity == "INDIRECT_LOCATION" and s.source.startswith("quasi:named_venue") and re.search(
                    r"(?i)(?:apartments|apts|condos?|condominiums|townhomes|townhouses|villas|lofts|motel|inn|hotel|"
                    r"suites|lodge|bar|tavern|pub|saloon|grill|lounge|club|church|chapel|mosque|masjid|synagogue|"
                    r"temple|salon|barbershop|spa|gym|daycare|preschool|shelter|mobile\s+home\s+park|trailer\s+park|"
                    r"rv\s+park|nightclub|cafe|café|diner|taqueria|cantina|icehouse|brewery|taproom)[\x22\u201d]?$", stext):
                core = re.sub(r"(?i)^(?:the\s+)?[\x22\u201c]?|\s+(?:" + quasi.VENUE_NOUNS + r")[\x22\u201d]?$", "", stext).strip()
            elif s.entity == "INDIRECT_LOCATION" and s.source.startswith("quasi:unit"):
                m = re.search(r"(\d{1,4}[A-Z])\b", stext)
                core = m.group(1) if m else None
            if not core or len(core) < 3 or core.lower() in names.NON_NAME_WORDS or not re.search(r"[A-Z]", core):
                continue
            if s.entity == "INDIRECT_LOCATION" and re.fullmatch(quasi._BRAND_RX, core, re.I):
                continue  # "Shell", "Walmart": a chain name alone does not identify the place
            rx = re.compile(r"(?<![\w])" + r"\s+".join(re.escape(w) for w in core.split()) + r"(?![\w])",
                            0 if s.entity == "INDIRECT_LOCATION" else re.I)
            for m in rx.finditer(text):
                if m.start() >= s.start and m.end() <= s.end:
                    continue
                if s.entity == "EMPLOYER" and re.match(r"(?i)(?:[ \t]+[A-Za-z&]+){0,2}[,\s]+(?:LLC|L\.L\.C|Inc|Corp|Co\.|"
                                                       r"Company|Ltd|LLP|PLLC)\b", text[m.end():m.end() + 40]):
                    continue  # the formal party name ("SWIFTLINE FREIGHT LLC," in a caption) is public
                extra.append(Span(m.start(), m.end(), s.entity, 0.75, "propagate:core", m.group(),
                                  f"another mention of a detected {ENTITIES[s.entity].label.lower()}"))
        for v, src in values.items():
            if re.fullmatch(r"(?:19|20)\d\d", v) or re.fullmatch(r"\d{3,4}-[A-Z]{1,5}|\d{1,2}-(?:19|20)\d\d", v):
                continue  # a year or a form number ("2026", "1099-NEC", "Rev. 1-2024") is never worth spreading
            # account last-4 digits spread only where the context is an account again (badges and the like still spread)
            short = bool(re.fullmatch(r"\d{4}", v)) and src.entity in ("BANK_ACCOUNT", "CREDIT_CARD", "ID_NUMBER")
            flexible = r"[\s\-.]?".join(re.escape(ch) for ch in re.sub(r"[\s\-.]", "", v)) \
                if re.fullmatch(r"[\d\s\-.()]+", v) else re.escape(v)
            rx = re.compile(r"(?<![\w])" + flexible + r"(?![\w])", re.I)
            for m in rx.finditer(text):
                line_start = text.rfind("\n", 0, m.start()) + 1
                if short and not (m.start() >= src.start and m.end() <= src.end) and not re.search(
                        r"(?i)(?:[xX*•]{2,}|\*|\.{2,}|ending(?:\s+in)?|acct\.?|account|card|loan|ln|x-|last\s+(?:4|four))"
                        r"[\s:#-]*$", text[max(0, m.start() - 24):m.start()]) and not re.search(
                        r"(?i)\b(?:bank|credit\s+union|fcu|heloc|loan|mortgage|financial|lending|card|servicing)\b",
                        text[line_start:m.start()]):
                    continue  # "Kroger #0447" is a store, even if a loan also ends in 0447
                extra.append(Span(m.start(), m.end(), src.entity, max(0.85, src.score - 0.05), "propagate:value",
                                  m.group(), f"another occurrence of a detected {ENTITIES[src.entity].label.lower()}"))
        def in_firm_name(sp: Span) -> bool:
            before, after = text[max(0, sp.start - 30):sp.start], text[sp.end:sp.end + 40]
            return bool(re.search(r"[A-Z][A-Za-z'’-]+,?\s*(?:&|and)\s*$", before) or
                        re.match(r",?\s*(?:&|and)\s+[A-Z]", after) or
                        re.match(r"(?:\s+[A-Z][a-z]+){1,2}\s+(?:LLC|Inc|Corp|PLLC|LLP|P\.C\.|Co\.|Company|operating|"
                                 r"payroll|account|Services|Group)\b", after))
        extra = [sp for sp in extra if not (sp.entity == "PERSON" and sp.source == "propagate:token" and in_firm_name(sp))]
        # the same public-name filters as first detections: "Hill" in "PROSPECT HILL SUBSTATION" is a place
        # (a surname that is also a role word — "Ward", "Cook", "Mason" — is still that person's name)
        extra = [sp for sp in extra if sp.entity != "PERSON" or (negatives.is_not_a_person(text, sp.start, sp.end) in (
            None, "abbreviation", "legal role", "job title / credential") and not (
            text[sp.start:sp.end].split() and text[sp.start:sp.end].split()[-1].lower().strip(".") in _STREET_TAILS) and
            not re.match(r"[ \t]+(?i:blvd|ave|avenue|rd|ln|pkwy|hwy|highway)\b\.?", text[sp.end:sp.end + 12]))]
        if not extra:
            return spans
        for sp in extra:
            sp.text = orig[sp.start:sp.end]
        return TextAnalyzer._fuse(orig, spans + extra)

    @staticmethod
    def _user_rules(text: str, terms: list[SearchTerm]) -> list[Span]:
        out: list[Span] = []
        for t in terms:
            if not t.text:
                continue
            flags = 0 if t.case_sensitive else re.IGNORECASE
            if t.regex:
                try:
                    rx = re.compile(t.text, flags | re.MULTILINE)
                except re.error:
                    continue
            else:
                body = r"\s+".join(re.escape(p) for p in t.text.split())
                rx = re.compile((r"(?<![\w])" + body + r"(?![\w])") if t.whole_word else body, flags)
            for m in rx.finditer(text):
                if m.end() <= m.start():
                    continue
                g = 1 if (t.regex and m.re.groups) else 0
                s, e = m.span(g)
                ent = t.entity if t.entity in ENTITIES else "CUSTOM"
                # never echo the term itself: custom lists are often lists of names
                sp = Span(s, e, ent, 0.99, "user:" + ("regex" if t.regex else "term"), text[s:e],
                          f"matches {'pattern' if t.regex else 'search term'}" + (f" from “{t.label}”" if t.label else ""))
                if t.exemption:
                    sp.meta["exemption"] = t.exemption
                out.append(sp)
        return out

    @staticmethod
    def _apply_allow_list(text: str, spans: list[Span], allow: list[str]) -> list[Span]:
        if not allow:
            return spans
        allowed = {a.strip().lower() for a in allow if a.strip()}
        return [s for s in spans if s.text.strip().lower() not in allowed]


_CAPS_LINE = re.compile(r"[^\n]+")


def restore_case(text: str) -> str:
    """Title-case lines that are mostly upper-case ("PATIENT: JOHNSON, MARY A") so NER sees name-like
    tokens. Character-for-character, so every offset stays valid."""
    out = list(text)
    for m in _CAPS_LINE.finditer(text):
        line = m.group()
        letters = [c for c in line if c.isalpha()]
        if len(letters) < 4 or sum(c.isupper() for c in letters) / len(letters) < 0.7:
            continue
        prev_alpha = False
        for i, ch in enumerate(line):
            j = m.start() + i
            if ch.isalpha():
                if prev_alpha:
                    low = ch.lower()
                    if len(low) == 1:
                        out[j] = low
                prev_alpha = True
            else:
                prev_alpha = ch in "'’"
    return "".join(out)


def partial_ranges(text: str, rule: str) -> list[tuple[int, int]]:
    """Character ranges (relative to the span) to black out under a partial-redaction rule."""
    if rule == "last4":
        idx = [i for i, c in enumerate(text) if c.isalnum()]
        keep = set(idx[-4:])
        return _runs([i for i in idx if i not in keep])
    if rule == "year":
        m = list(re.finditer(r"(?:19|20)\d{2}|\b\d{2}$", text))
        if not m:
            return [(0, len(text))]
        ys, ye = m[-1].span()
        return [r for r in ((0, ys), (ye, len(text))) if r[1] > r[0] and text[r[0]:r[1]].strip(" ,/-.")]
    if rule == "initials":
        out = []
        for m in re.finditer(r"[A-Za-z][A-Za-z'’-]*", text):
            if m.end() - m.start() > 1:
                out.append((m.start() + 1, m.end()))
        return out
    return [(0, len(text))]


def _runs(idx: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for i in idx:
        if out and out[-1][1] == i:
            out[-1] = (out[-1][0], i + 1)
        else:
            out.append((i, i + 1))
    return out


_ANALYZER: TextAnalyzer | None = None


def get_analyzer() -> TextAnalyzer:
    global _ANALYZER
    if _ANALYZER is None:
        _ANALYZER = TextAnalyzer()
    return _ANALYZER
