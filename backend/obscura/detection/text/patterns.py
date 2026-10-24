"""Self-contained pattern recognizers (no label needed — the value's own structure identifies it).

Each recognizer yields :class:`Span` candidates against a :class:`NormText`. Scores are calibrated
so that 0.5 is the default auto-redaction threshold:

* >= 0.85  structure + checksum (or structure + context) — near-certain
* 0.5-0.85 strong structure, no checksum available
* < 0.5    plausible but ambiguous — surfaced to reviewers as a suggestion only
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date

import phonenumbers
from phonenumbers import Leniency

from . import validators as V
from .base import NormText, Span, window

# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------

def _ctx(nt: NormText, s: int, e: int, rx: re.Pattern, before: int = 60, after: int = 25) -> bool:
    return bool(rx.search(window(nt.lower, s, e, before, after)))


def _span(nt: NormText, s: int, e: int, entity: str, score: float, source: str, why: str = "",
          **meta) -> Span:
    os_, oe = nt.to_original(s, e)
    return Span(os_, oe, entity, min(score, 0.99), source, nt.original[os_:oe], why, meta)


MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
          r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

NEG_ID_CTX = re.compile(r"\b(?:invoice|inv|order|ord|po|purchase\s*order|sku|part|model|item|confirmation|"
                        r"tracking|ticket|ref(?:erence)?|transaction|txn|batch|lot|version|ver|isbn|upc|"
                        r"page|pg|exhibit|bates|cpt|hcpcs|ndc|rev(?:enue)?\s*code|statute|section|§|rule)\b")

# ---------------------------------------------------------------------------------------------
# SSN / ITIN
# ---------------------------------------------------------------------------------------------

SSN_CTX = re.compile(r"(?:\bssn\b|s\.s\.n|\bss\s*#|\bss\s*no\b|\bsoc(?:ial)?\.?\s*sec(?:urity)?\b|\bsocial\b|"
                     r"\btaxpayer\b|\btin\b|\btax\s*id|\bitin\b|\bseguro\s+social)")
ITIN_CTX = re.compile(r"\bitin\b|individual\s+taxpayer")
_SSN_DASH = re.compile(r"(?<![\w-])(\d{3})-(\d{2})-(\d{4})(?![\w]|-\w)")
_SSN_SPACED = re.compile(r"(?<![\w.,-])(\d{3})(?: ?[ .] ?)(\d{2})(?: ?[ .] ?)(\d{4})(?![\w]|[.,-]\d| \d)")
_SSN_PLAIN = re.compile(r"(?<![\w.,$-])(\d{9})(?![\w]|[.,-]\d)")
_SSN_MASKED = re.compile(r"(?<![\w-])(?:[xX*•#]{3}|\d{3})[- ](?:[xX*•#]{2})[- ](\d{4})(?![\w-])"
                         r"|(?<![\w-])[xX*•#]{5}(\d{4})(?![\w-])")
_LAST_N = re.compile(r"(?i)\blast\s*(?:\d|two|three|four|five|six)\s*(?:(?:digits|numbers|characters)\s*)?(?:of\s*(?:the\s*|(?:his|her|their|my|"
                     r"your|our|plaintiff's|defendant's|claimant's|patient's|client's|decedent's|the\s+\w+'s)\s+)?)?"
                     r"(ssn|social\s+security(?:\s+(?:number|no\.?|#))?|ss#|tin|tax\s*id|driver'?s?\s+licen[cs]e(?:\s+(?:number|no\.?|#))?|"
                     r"dl|(?:bank\s+|checking\s+|savings\s+)?account(?:\s+(?:number|no\.?|#))?|acct|card(?:\s+number)?|"
                     r"credit\s+card(?:\s+number)?|phone(?:\s+number)?|passport(?:\s+number)?)"
                     r"[\s:#,]*(?:is|are|was|were|:|=|-|ending)?\s*(\d{2,6})(?!\d)")
_LAST_N_ENT = [("ssn", "SSN"), ("social", "SSN"), ("ss#", "SSN"), ("tin", "SSN"), ("tax", "SSN"), ("driver", "DRIVERS_LICENSE"),
               ("dl", "DRIVERS_LICENSE"), ("account", "BANK_ACCOUNT"), ("acct", "BANK_ACCOUNT"), ("card", "CREDIT_CARD"),
               ("credit", "CREDIT_CARD"), ("phone", "PHONE"), ("passport", "PASSPORT"), ("bank", "BANK_ACCOUNT"),
               ("checking", "BANK_ACCOUNT"), ("savings", "BANK_ACCOUNT")]
_QA_LAST = re.compile(r"(?i)last\s+(?:four|4|three|3)\s+(?:digits\s+)?of\s+(?:your|his|her|the)\s+(social|ssn|"
                      r"card|account|license)[^\n]*\?\s*\n\s*(?:\d{1,2}:\d{2}\s+)?(?:A[.:]|[A-Z]{1,4}:)\s*(\d{3,4})(?!\d)")
_SSN_LAST4 = re.compile(r"(?:ssn|social security(?: number| no\.?| #)?|ss#|soc\.? sec\.?)[^\n\d]{0,30}?"
                        r"(?:last\s*(?:4|four)(?:\s*digits)?|ending(?:\s+in)?|ends\s+in)[^\n\d]{0,12}(\d{4})(?!\d)")


_ENDING = re.compile(
    r"(?i)\b(checking|savings|account|acct|loan|ln|mortgage|card|debit|credit\s*card|chk|sav|vi\s?sa|master\s?card|amex|"
    r"discover|dl|driver'?s?\s+licen[cs]e|ssn|social(?:\s+security)?)\b[^\n\d]{0,40}?"
    r"(?:ending(?:\s+in)?|ends(?:\s+(?:in|with))?|ending\s+with|\.{2,}\s?|…\s?|[x*•]{2,}-?|\*{2,}|#\s?x+)\s*(\d{3,5})(?!\d)")
_REVERSE_LAST = re.compile(
    r"(?i)\b(ssn|social\s+security(?:\s+number)?|driver'?s?\s+licen[cs]e(?:\s+number)?|dl|account(?:\s+number)?|card)"
    r"\s+last\s+(?:\d|two|three|four|five)\s*(?:digits|numbers)?\s*(?:is|are|:|=|-)?\s*(\d{2,5})(?!\d)")
# "The last three numbers of Petitioner's driver's license number are 336."
_LAST_OF = re.compile(
    r"(?i)\blast\s+(?:\d|two|three|four|five|six)\s+(?:(?:digits|numbers|characters)\s+)?of\s+(?:(?:the|his|her|their|my|your|"
    r"[a-z]+['’]s)\s+)?(ssn|social\s+security(?:\s+number)?|driver['’]?s?\s+licen[cs]e(?:\s+number)?|dl|(?:bank\s+)?"
    r"account(?:\s+number)?|card(?:\s+number)?|passport(?:\s+number)?|phone(?:\s+number)?|social)\s+(?:number\s+)?"
    r"(?:is|are|was|were|:|=|\(|on\s+file(?:\s+is)?)\s*(\d(?:[ ,.-]{0,2}\d){1,4})(?!\d)")
# "Q. … the last four of your Social. / A. 3318." — the digits come in the answer line
_LAST_OF_QA = re.compile(r"(?i)\blast\s+(?:four|4|two|three)\s+(?:digits\s+)?of\s+(?:your|his|her|their|the)\s+"
                         r"(ssn|social(?:\s+security)?(?:\s+number)?|driver['’]?s?\s+licen[cs]e|account|card)[^\n]*\n"
                         r"[ \t]*(?:\d{1,2}[ \t]+)?(?:A[.:]|ANSWER:?|[A-Z]{1,4}:)?[ \t]*(?:It's|it is|Yes,?)?[ \t]*(\d{4})(?!\d)")
# USCIS receipt numbers on green cards / I-797s: three-letter service-centre code + 10 digits
_USCIS_RECEIPT = re.compile(r"(?<![A-Z0-9])(?:EAC|WAC|LIN|SRC|NBC|MSC|IOE|YSC|ZLA|ZNY|ZSF|NFC|TSC|VSC|CSC|NSC)\d{10}(?![A-Z0-9])")
_ENDING_ENT = [("ln", "BANK_ACCOUNT"), ("check", "BANK_ACCOUNT"), ("sav", "BANK_ACCOUNT"), ("account", "BANK_ACCOUNT"), ("acct", "BANK_ACCOUNT"),
               ("loan", "BANK_ACCOUNT"), ("mortgage", "BANK_ACCOUNT"), ("chk", "BANK_ACCOUNT"), ("card", "CREDIT_CARD"),
               ("debit", "CREDIT_CARD"), ("credit", "CREDIT_CARD"), ("visa", "CREDIT_CARD"), ("master", "CREDIT_CARD"),
               ("amex", "CREDIT_CARD"), ("discover", "CREDIT_CARD"), ("dl", "DRIVERS_LICENSE"), ("driver", "DRIVERS_LICENSE"),
               ("ssn", "SSN"), ("social", "SSN")]


def find_partial_numbers(nt: NormText) -> Iterator[Span]:
    """"checking ending 0224", "card ...7719", "TX DL ****8826", "SSN last three digits: 934"."""
    for rx in (_ENDING, _REVERSE_LAST, _LAST_OF, _LAST_OF_QA):
        for m in rx.finditer(nt.text):
            k = m.group(1).lower()
            ent = next((e for key, e in _ENDING_ENT if k.startswith(key)), "ID_NUMBER")
            s, e = m.span(2)
            mask = re.search(r"[*xX•#.…]{2,}-?$", nt.text[max(0, s - 12):s])
            if mask:
                s -= len(mask.group())  # "****0918": the mask is part of the redaction
            yield _span(nt, s, e, ent, 0.88, "pattern:partial_number", f"partial {ent.replace('_', ' ').lower()}",
                        partial=True)


# claim notes / audit trails: "06/28/2026 08:14  jkirkendall  FNOL via app…" — the column after the timestamp is a user
_LOG_USER = re.compile(r"(?m)^[ \t]*\d{1,2}/\d{1,2}/\d{2,4}[ \t]+\d{1,2}:\d{2}(?::\d{2})?(?:[ \t]*[AaPp][Mm])?[ \t]+"
                       r"([a-z][a-z0-9._-]{2,23})(?=[ \t]{2,}\S)")
# "kwolf.mke (Instagram)", "elboricua_hlm on TikTok"
_HANDLE_PLATFORM = re.compile(r"(?<![\w@.])(@?[A-Za-z0-9][A-Za-z0-9._-]{2,30}[A-Za-z0-9_])\s*(?:\(|on\s+)(?i:instagram|ig|insta|"
                              r"snapchat|snap|tiktok|twitter|x|facebook|fb|venmo|cash\s*app|telegram|discord|threads|"
                              r"linkedin|reddit|youtube|twitch|kik|whatsapp)\b")
# "Ofc. M. Begay #S-114", "Det. N. Wojcik #D-6614", "Deputy Ruiz #4412": an officer's badge after the name
_OFFICER_BADGE = re.compile(r"\b(?i:ofc|officer|det|detective|sgt|sergeant|lt|cpl|corporal|dep|deputy|trooper|tpr|agent|"
                            r"inv|investigator)\.?\s+(?:[A-Z]\.\s*)?[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)?,?\s*\n?\s*"
                            r"\(?#\s*([A-Z]{0,4}-?\d{2,7})\b")
# "KPD 26-011842", "MNPD 2026-0217733", "DPD-26-0042116", "PBP 26-071194": an agency code and a report number
_AGENCY_REPORT = re.compile(r"(?<![\w-])([A-Z]{2,5})[ -](?:[A-Z]{1,3}-)?(\d{2,4}-\d{3,8}(?:-\d{2,6})?)(?![\w-])|(?<![\w-])([A-Z]{2,4}\d{2}-\d{5,8})(?![\w-])")
# "CASTANEDA, J #4127", "J. Castaneda #4127", "Ofc Ruiz #3318" in police paperwork: the number after a name is a badge
_NAME_BADGE = re.compile(r"\b(?:[A-Z][A-Za-z'’-]+,\s*[A-Z]\.?|[A-Z]\.\s*[A-Z][A-Za-z'’-]+|[A-Z][a-z]+\s+[A-Z][a-z'’-]+)\s+"
                         r"#\s*([A-Z]?\d{3,6})\b")
_POLICE_TEXT = re.compile(r"(?i)\bpolice\b|\bsheriff|\bofficer\b|\bdeputy\b|\btrooper\b|\barrest|\bbooking|"
                          r"\bincident\s+report|\bstatement\s+taken|\bP\.?D\.?\b")
_EVIDENCE_TAG = re.compile(r"(?i)\b(?:evidence\s+)?tag\s+#?\s*([A-Z]\d{2}-\d{4}-\d{3,5})\b")
_AGENCY_CTX = re.compile(r"(?i)\b(?:report|rpt|case|incident|police|pd|sheriff|cad|citation|ncic|offense|arrest|"
                         r"complaint|took\s+a\s+report|re:)\b")
# "BIRTHDATE 08211984", "DOB 19800115" — compact birth dates
_COMPACT_DOB = re.compile(r"(?i)\b(?:birth\s*date|birthdate|date\s+of\s+birth|dob|d\.o\.b\.?)\W{0,3}(\d{8})(?!\d)")


def find_immigration_ids(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for m in _USCIS_RECEIPT.finditer(t):
        yield _span(nt, *m.span(), "NATIONAL_ID", 0.9, "pattern:uscis_receipt", "USCIS receipt / card number")
    for m in _LOG_USER.finditer(t):
        if m.group(1) not in ("and", "the", "per", "spoke", "called", "rec'd", "recd", "note", "left", "sent", "rcvd"):
            yield _span(nt, *m.span(1), "USERNAME", 0.8, "pattern:log_user", "user id in a log / claim-notes entry")
    for m in _HANDLE_PLATFORM.finditer(t):
        if _usernameish(m.group(1)) and re.search(r"[\d_.@]", m.group(1)) and re.search(r"[A-Za-z]", m.group(1)):
            yield _span(nt, *m.span(1), "USERNAME", 0.85, "pattern:handle_platform", "handle on a named platform")
    for m in _AGENCY_REPORT.finditer(t):
        code = m.group(1) or ""
        if code and code in ("DOB", "SSN", "MRN", "NPI", "DEA", "EIN", "TIN", "ICD", "CPT", "DOS", "DOI", "DOL", "ROI",
                             "INV", "REQ", "PO", "ORD", "REF", "CLM", "INC", "TKT", "DOC", "PRN", "RX", "WO", "SO"):
            continue
        if code.endswith(("PD", "SD", "SP", "DPS")) or _AGENCY_CTX.search(t[max(0, m.start() - 22):m.start()]):
            yield _span(nt, *m.span(), "LAW_ENFORCEMENT_ID", 0.85, "pattern:agency_report", "agency report / case number")
    police = bool(_POLICE_TEXT.search(t[:4000]))
    if police:
        for m in _NAME_BADGE.finditer(t):
            yield _span(nt, *m.span(1), "LAW_ENFORCEMENT_ID", 0.82, "pattern:name_badge", "badge number after a name")
    for m in _EVIDENCE_TAG.finditer(t):
        yield _span(nt, *m.span(1), "LAW_ENFORCEMENT_ID", 0.85, "pattern:evidence_tag", "evidence / property tag number")
    for m in _OFFICER_BADGE.finditer(t):
        yield _span(nt, *m.span(1), "LAW_ENFORCEMENT_ID", 0.85, "pattern:officer_badge", "badge number after an officer's name")
    for m in _COMPACT_DOB.finditer(t):
        d = m.group(1)
        for mm, dd, yy in ((d[:2], d[2:4], d[4:]), (d[4:6], d[6:], d[:4])):
            if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31 and 1900 <= int(yy) <= 2030:
                yield _span(nt, *m.span(1), "DATE_OF_BIRTH", 0.95, "pattern:dob_compact", "birth date (compact)")
                break


def find_ssn(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for rx, fmt in ((_SSN_DASH, "dashed"), (_SSN_SPACED, "spaced")):
        for m in rx.finditer(t):
            s, e = m.span()
            raw = m.group()
            ctx = _ctx(nt, s, e, SSN_CTX)
            neg = _ctx(nt, s, e, NEG_ID_CTX, before=25, after=0)
            if V.itin_ok(raw):
                yield _span(nt, s, e, "ITIN", 0.95 if ctx else 0.85, f"pattern:itin_{fmt}",
                            "9xx-xx-xxxx with valid ITIN group")
                continue
            if V.ssn_ok(raw):
                score = 0.99 if ctx else (0.9 if fmt == "dashed" else 0.65)
                why = "SSN format, valid SSA area/group/serial"
            elif V.ssn_plausible(raw):
                score = 0.9 if ctx else (0.55 if fmt == "dashed" else 0.3)
                why = "SSN format (not a valid SSA allocation — possible typo or example)"
            else:
                continue
            if neg and not ctx:
                score -= 0.3
            yield _span(nt, s, e, "SSN", score, f"pattern:ssn_{fmt}", why + (", SSN context" if ctx else ""))
    for m in _SSN_PLAIN.finditer(t):
        s, e = m.span()
        if _ctx(nt, s, e, SSN_CTX, before=40, after=0):
            ok = V.ssn_ok(m.group())
            ent = "ITIN" if V.itin_ok(m.group()) else "SSN"
            yield _span(nt, s, e, ent, 0.95 if ok else 0.8, "pattern:ssn_plain", "9 digits with SSN context")
    for m in _SSN_MASKED.finditer(t):
        s, e = m.span()
        yield _span(nt, s, e, "SSN", 0.9 if _ctx(nt, s, e, SSN_CTX) else 0.75, "pattern:ssn_masked",
                    "partially-masked SSN still exposes last four digits", partial=True)
    for m in _SSN_LAST4.finditer(nt.lower):
        s, e = m.span(1)
        yield _span(nt, s, e, "SSN", 0.9, "pattern:ssn_last4", "last four digits of SSN", partial=True)
    for m in _QA_LAST.finditer(nt.text):
        k = m.group(1).lower()
        ent = "SSN" if k in ("social", "ssn") else ("CREDIT_CARD" if k == "card" else
                                                   "DRIVERS_LICENSE" if k == "license" else "BANK_ACCOUNT")
        s, e = m.span(2)
        yield _span(nt, s, e, ent, 0.88, "pattern:qa_last_digits", "partial number given in an answer", partial=True)
    for m in _LAST_N.finditer(nt.text):
        word = m.group(1).lower()
        ent = next((e for k, e in _LAST_N_ENT if word.startswith(k)), "ID_NUMBER")
        s, e = m.span(2)
        yield _span(nt, s, e, ent, 0.88, "pattern:last_n_digits", f"partial {ent.replace('_', ' ').lower()} digits",
                    partial=True)


# ---------------------------------------------------------------------------------------------
# Payment cards
# ---------------------------------------------------------------------------------------------

CARD_CTX = re.compile(r"\b(?:card|visa|master\s*card|mc|amex|american\s+express|discover|jcb|diners|credit|"
                      r"debit|cc\s*#?|pan|cardholder|payment|charged|paid\s+with)\b")
_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){11,18}\d(?![\d-])")
_CARD_MASKED = re.compile(r"(?<![\w-])(?:(?:[xX*•#]{4}[ -]?){2,3}[xX*•#]{0,4}[ -]?\d{4}|[xX*•#]{8,15}\d{4})(?![\w-])")
_CARD_ENDING = re.compile(r"\b(?:visa|mastercard|amex|discover|card|debit|credit)[^\n\d]{0,25}?"
                          r"(?:ending|ends)(?:\s+(?:in|with))?[^\n\d]{0,5}(\d{4})(?!\d)")


def _card_grouping_ok(raw: str) -> bool:
    groups = re.split(r"[ -]", raw)
    if len(groups) == 1:
        return True
    lens = [len(g) for g in groups]
    return lens in ([4, 4, 4, 4], [4, 6, 5], [4, 6, 4], [4, 4, 4, 4, 3], [4, 4, 4, 1], [4, 4, 4, 2],
                    [4, 4, 4, 3], [4, 4, 5], [4, 4, 4, 4, 2], [4, 4, 4, 4, 1], [6, 13], [4, 4, 4, 7])


def find_cards(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for m in _CARD.finditer(t):
        raw = m.group()
        d = V.digits(raw)
        if not 12 <= len(d) <= 19:
            continue
        s, e = m.span()
        ctx = _ctx(nt, s, e, CARD_CTX)
        grouping = _card_grouping_ok(raw)
        if V.credit_card_ok(d):
            score = 0.97 if (ctx or grouping) else 0.8
            yield _span(nt, s, e, "CREDIT_CARD", score, "pattern:card", f"{V.card_brand(d)} number, Luhn-valid")
        elif ctx and V.card_brand(d) and grouping and len(set(d)) > 2:
            yield _span(nt, s, e, "CREDIT_CARD", 0.7, "pattern:card_luhn_fail",
                        "card-shaped number in card context (fails Luhn — possible typo)")
    for m in _CARD_MASKED.finditer(t):
        s, e = m.span()
        yield _span(nt, s, e, "CREDIT_CARD", 0.85, "pattern:card_masked", "masked card number", partial=True)
    for m in _CARD_ENDING.finditer(nt.lower):
        s, e = m.span(1)
        yield _span(nt, s, e, "CREDIT_CARD", 0.85, "pattern:card_last4", "card last four digits", partial=True)


_EXPIRY = re.compile(r"\b(?:exp(?:iry|iration|ires)?\.?(?:\s*date)?|valid\s*(?:thru|through)|good\s*thru)"
                     r"[\s:#.\-]{0,5}((?:0[1-9]|1[0-2])\s?[/-]\s?(?:\d{2}|20\d{2}))(?![\d/])")
_CVV = re.compile(r"\b(?:cvv2?|cvc2?|cvn|cid|csc|security\s*code|card\s*(?:verification|security)\s*"
                  r"(?:code|value|number)|card\s*code)[\s:#.\-=]{0,5}(?:is\s+|was\s+)?(\d{3,4})(?!\d)")


def find_card_extras(nt: NormText) -> Iterator[Span]:
    for m in _EXPIRY.finditer(nt.lower):
        s, e = m.span(1)
        yield _span(nt, s, e, "CARD_EXPIRY", 0.9, "pattern:card_expiry", "card expiry date")
    for m in _CVV.finditer(nt.lower):
        s, e = m.span(1)
        yield _span(nt, s, e, "CVV", 0.95, "pattern:cvv", "card security code")


# ---------------------------------------------------------------------------------------------
# Phones
# ---------------------------------------------------------------------------------------------

PHONE_CTX = re.compile(r"\b(?:phone|ph|tel|telephone|cell|cellular|mobile|mob|fax|facsimile|call|called|"
                       r"texted|dial|dialed|pager|(?:home|work|office|direct|contact|best)\s*(?:#|no\.?|number|:)|"
                       r"tel[eé]fono)(?![a-z])|\((?:h|w|c|m)\)|\b(?:h|w|c|m):")
_NANP = re.compile(r"(?<![\w$.,/-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)[\s.-]?|\d{3}[\s.-])\d{3}[\s.-]\d{4}"
                   r"(?:\s*(?:x|ext\.?|extension|#)\s*\d{1,6})?(?![\w]|[.,/-]\d)")
_NANP_PLAIN = re.compile(r"(?<![\w$.,/-])(?:\+?1)?\d{10}(?![\w]|[.,/-]\d)")
_INTL = re.compile(r"(?<![\w+])\+\d{1,3}[\s.-]?(?:\(?\d{1,4}\)?[\s.-]?){2,5}\d{2,4}(?![\w])")
_PHONE_7 = re.compile(r"(?<![\w$.,/-])\d{3}-\d{4}(?![\w]|[.,/-]\d)")


def find_phones(nt: NormText) -> Iterator[Span]:
    t = nt.text
    seen: set[tuple[int, int]] = set()
    try:
        for m in phonenumbers.PhoneNumberMatcher(t, "US", leniency=Leniency.VALID, max_tries=100000):
            s, e = m.start, m.end
            raw = m.raw_string
            formatted = bool(re.search(r"[\s().+-]", raw))
            groups = [len(g) for g in re.findall(r"\d+", raw)]
            if formatted and not raw.lstrip().startswith("+") and groups not in (
                    [3, 3, 4], [1, 3, 3, 4], [3, 7], [1, 10], [3, 4], [10]) and not re.match(r"\s*\(", raw):
                continue  # "2025-118842", NDC "16729-0172-01": not phone groupings
            if _ctx(nt, s, e, NEG_ID_CTX, before=30, after=0) and not _ctx(nt, s, e, PHONE_CTX):
                continue
            ctx = _ctx(nt, s, e, PHONE_CTX)
            if not formatted and not ctx:
                score = 0.45
            else:
                score = 0.95 if ctx else 0.88
            seen.add((s, e))
            yield _span(nt, s, e, "PHONE", score, "libphonenumber", "valid phone number (libphonenumber)")
    except Exception:  # pragma: no cover - library edge cases must never break detection
        pass
    for m in _NANP.finditer(t):
        s, e = m.span()
        if (s, e) in seen:
            continue
        d = V.digits(m.group().split("x")[0])
        core = d[-10:]
        ctx = _ctx(nt, s, e, PHONE_CTX)
        valid_shape = core[0] in "23456789" and core[3] in "23456789"
        score = (0.93 if ctx else 0.8) if valid_shape else (0.8 if ctx else 0.6)
        yield _span(nt, s, e, "PHONE", score, "pattern:nanp", "NANP phone number format")
    for m in _NANP_PLAIN.finditer(t):
        s, e = m.span()
        if _ctx(nt, s, e, PHONE_CTX, before=30, after=0) and not _ctx(nt, s, e, NEG_ID_CTX, 30, 0):
            yield _span(nt, s, e, "PHONE", 0.85, "pattern:phone_plain", "10 digits with phone context")
    for m in _INTL.finditer(t):
        s, e = m.span()
        if 8 <= len(V.digits(m.group())) <= 15:
            yield _span(nt, s, e, "PHONE", 0.8, "pattern:intl_phone", "international phone format")
    for m in _PHONE_7.finditer(t):
        s, e = m.span()
        if _ctx(nt, s, e, PHONE_CTX, before=30, after=0):
            yield _span(nt, s, e, "PHONE", 0.75, "pattern:phone7", "7-digit local number with phone context")


# ---------------------------------------------------------------------------------------------
# Email / URL / handles / network
# ---------------------------------------------------------------------------------------------

# internationalised addresses (RFC 6531 / IDN) are allowed: "hgirón@girónlaw.com"
_EL = "A-Za-z0-9\u00c0-\u024f"
_EMAIL = re.compile(rf"(?<![\w.+-])[{_EL}][{_EL}._%+'-]{{0,63}}@(?:[{_EL}](?:[{_EL}-]{{0,61}}[{_EL}])?\.)+"
                    rf"(?:[A-Za-z]{{2,24}}|xn--[a-z0-9-]{{2,59}})(?![\w-])")
_EMAIL_OBF = re.compile(r"(?i)\b(?!(?:online|us|me|him|her|them|home|work|it|this|that|all|least|once|first|last|"
                        r"time|times|look|looked|looking|stop|stopped|arrived|located|available|found|seen|treated|"
                        r"visit|call|calls|reach|reached|email|e-mail|mail|is|was|are|be|or|and|but|me|you|write|"
                        r"to|him|send|contact)\b)"
                        r"[a-z0-9._%+-]{0,63}[a-z0-9_%+-](?:(?:\s+(?:dot|underscore|dash)\s+|\s?\.\s?)[a-z0-9]{1,30}){0,3}"
                        r"\s*(?:\[at\]|\(at\)|\{at\}|\s+at\s+)\s*(?!www\b)[a-z0-9-]{1,63}"
                        r"(?:\s*(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+|\.)\s*[a-z0-9-]{1,63}){0,3}"
                        r"\s*(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+|\.)\s*(?:com|net|org|edu|gov|us|io|co|info|biz|me)\b")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"'()]+[^\s<>\"'().,;:!?]")
_SOCIAL_URL = re.compile(r"(?i)(?:facebook|fb|instagram|twitter|x|tiktok|linkedin|snapchat|youtube|"
                         r"reddit|onlyfans|venmo|cash\.app|github|threads)\.(?:com|me|net)/")
_HANDLE = re.compile(r"(?<![\w@.])@[A-Za-z0-9_](?:[A-Za-z0-9_.-]{1,28}[A-Za-z0-9_])?(?![\w@])")  # Venmo allows "-"
_CASHTAG = re.compile(r"(?<![\w$])\$[A-Za-z][A-Za-z0-9_-]{2,19}(?![\w])")
_IPV4 = re.compile(r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:/\d{1,2})?(?![\w.]|\.\d)")
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
_MAC = re.compile(r"(?<![\w:-])(?:[0-9A-Fa-f]{2}([:-]))(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![\w:-])"
                  r"|(?<![\w.])[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}(?![\w.])")
_VERSION_CTX = re.compile(r"(?:\b(?:version|ver|v|build|release|firmware|sdk|rev|section|sec|rule|chapter|ch|"
                          r"article|art|paragraph|para|item|figure|fig|table|step|clause|part)\.?|§+)\s*$")


_SYS_USER = re.compile(r"(?i)\b(?:printed|exported|completed|received|entered|modified|reviewed|run|accessed|viewed|"
                       r"generated|signed|uploaded|created|updated)\b[^\n]{0,40}?\bby:?\s+((?:[A-Za-z]+\\)?[a-z][a-z0-9._-]{2,30})"
                       r"(?![\w.@-])|\buser(?:\s*id)?:\s*([A-Za-z][A-Za-z0-9._\\-]{2,30})(?![\w.@-])")
_PLATFORM_USER = re.compile(r"(?i)\b(?:facebook|fb|instagram|ig|insta|snapchat|snap|tiktok|twitter|x\.com|threads|life360|"
                            r"apple\s*id|discord|telegram|whatsapp|venmo|cash\s*app|paypal|gamertag|psn|xbox|steam|"
                            r"kik|reddit|linkedin|youtube|twitch|onlyfans|tablet\s*acct|inmate\s*account|jail\s*tablet|"
                            r"account|handle|profile|username|patient\s*portal|portal)\s*(?:account|handle|profile|name|id|"
                            r"login|user(?:name)?)?\s*[:(]?\s*[\x22\u201c']?"
                            r"(@?[A-Za-z0-9][A-Za-z0-9._-]{2,40}[A-Za-z0-9])")


def _usernameish(v: str) -> bool:
    v = v.lstrip("@")
    if not re.search(r"\d|[._]", v) and not v.isupper():
        return False  # plain words ("account settings") are not handles
    if re.fullmatch(r"\d+", v) or re.fullmatch(r"[A-Z]{2,}\d{0,2}", v):
        return False
    return len(v) >= 3


def find_digital(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for m in _SYS_USER.finditer(t):
        g = 1 if m.group(1) else 2
        v = m.group(g)
        if v.lower().rstrip(".") in ("hon", "dr", "mr", "mrs", "ms", "judge", "justice", "magistrate", "officer", "det") or \
                v.lower() in ("the", "a", "an", "fax", "mail", "email", "hand", "phone", "me", "us", "him", "her", "them",
                         "court", "staff", "patient", "provider", "system", "admin", "dr", "mr", "ms", "mrs") or \
                not (re.search(r"\d|[._\\]", v) or v.isupper() or (v.islower() and g == 2) or
                     (v.islower() and g == 1 and re.search(r"by:\s*$", t[max(0, m.start(g) - 6):m.start(g)]))):
            continue
        s, e = m.span(g)
        yield _span(nt, s, e, "USERNAME", 0.85, "pattern:system_user", "system user name")
    for m in _PLATFORM_USER.finditer(t):
        v = m.group(1)
        if not _usernameish(v):
            continue
        s, e = m.span(1)
        yield _span(nt, s, e, "USERNAME", 0.85, "pattern:platform_user", "account / handle on a named platform")
    for m in _EMAIL.finditer(t):
        s, e = m.span()
        yield _span(nt, s, e, "EMAIL", 0.97, "pattern:email", "email address")
    for m in _EMAIL_OBF.finditer(t):
        s, e = m.span()
        if "@" not in m.group():
            yield _span(nt, s, e, "EMAIL", 0.85, "pattern:email_obfuscated", "obfuscated email address")
    for m in _URL.finditer(t):
        s, e = m.span()
        social = bool(_SOCIAL_URL.search(m.group()))
        if social:  # a profile URL names an account: treat it like a handle
            yield _span(nt, s, e, "USERNAME", 0.9, "pattern:social_url", "social-media profile URL")
        else:
            yield _span(nt, s, e, "URL", 0.7, "pattern:url", "web address")
    for m in _HANDLE.finditer(t):
        s, e = m.span()
        if s > 0 and t[s - 1].isalnum():
            continue
        yield _span(nt, s, e, "USERNAME", 0.75, "pattern:handle", "@handle")
    for m in _CASHTAG.finditer(t):
        s, e = m.span()
        if _ctx(nt, s, e, re.compile(r"cash\s*app|cashtag|venmo|send|pay"), 40, 10):
            yield _span(nt, s, e, "USERNAME", 0.75, "pattern:cashtag", "payment-app cashtag")
    for m in _IPV4.finditer(t):
        s, e = m.span()
        ip = m.group().split("/")[0]
        if not V.ipv4_ok(ip):
            continue
        left = nt.lower[max(0, s - 12):s]
        if _VERSION_CTX.search(left):
            continue
        yield _span(nt, s, e, "IP_ADDRESS", 0.9, "pattern:ipv4", "IPv4 address")
    for m in _IPV6.finditer(t):
        s, e = m.span()
        if V.ipv6_ok(m.group()) and m.group().count(":") >= 3 and re.search(r"[0-9a-fA-F]{3}", m.group()):
            yield _span(nt, s, e, "IP_ADDRESS", 0.9, "pattern:ipv6", "IPv6 address")
    for m in _MAC.finditer(t):
        s, e = m.span()
        if V.mac_ok(m.group()):
            yield _span(nt, s, e, "MAC_ADDRESS", 0.9, "pattern:mac", "MAC address")


# ---------------------------------------------------------------------------------------------
# GPS
# ---------------------------------------------------------------------------------------------

_GPS_DEC = re.compile(r"(?<![\d.])([-+]?\d{1,2}\.\d{3,})\s*°?\s*([NSns])?\s*[,/ ]\s*([-+]?\d{1,3}\.\d{3,})\s*°?\s*([EWew])?(?![\d.])")
_GPS_DMS = re.compile(r"\d{1,3}\s*°\s*\d{1,2}\s*['′]\s*(?:\d{1,2}(?:\.\d+)?\s*[\"″]?)?\s*[NSns]\s*,?\s*"
                      r"\d{1,3}\s*°\s*\d{1,2}\s*['′]\s*(?:\d{1,2}(?:\.\d+)?\s*[\"″]?)?\s*[EWew]")
GPS_CTX = re.compile(r"\b(?:gps|lat|latitude|long|longitude|lng|coordinates|coords|location|geo)\b")


_GPS_FIELD = re.compile(r"(?i)\b(?:lat(?:itude)?|lon(?:g(?:itude)?)?|lng)\s*[:=]?\s*([-+]?\d{1,3}\.\d{3,})(?!\d)")


def find_gps(nt: NormText) -> Iterator[Span]:
    for m in _GPS_FIELD.finditer(nt.text):
        s, e = m.span(1)
        if abs(float(m.group(1))) <= 180:
            yield _span(nt, s, e, "GPS", 0.92, "pattern:gps_field", "latitude / longitude field")
    for m in _GPS_DEC.finditer(nt.text):
        lat, lon = float(m.group(1)), float(m.group(3))
        if not V.gps_ok(lat, lon):
            continue
        s, e = m.span()
        ctx = _ctx(nt, s, e, GPS_CTX)
        hemis = bool(m.group(2) or m.group(4))
        decimals = min(len(m.group(1).split(".")[1]), len(m.group(3).split(".")[1]))
        if ctx or hemis or decimals >= 4:
            yield _span(nt, s, e, "GPS", 0.95 if (ctx or hemis) else 0.75, "pattern:gps", "decimal coordinates")
    for m in _GPS_DMS.finditer(nt.text):
        s, e = m.span()
        yield _span(nt, s, e, "GPS", 0.95, "pattern:gps_dms", "degrees/minutes/seconds coordinates")


# ---------------------------------------------------------------------------------------------
# Dates / DOB / age
# ---------------------------------------------------------------------------------------------

DOB_CTX = re.compile(r"(?:\bd\.?\s?o\.?\s?b\b|date\s*of\s*birth|birth\s*date|birthdate|birthday|\bborn\b|"
                     r"\bb\.\s*$|\bdob/age|fecha\s+de\s+nacimiento|\bnacido\b|\bage/dob|\bdob\s*:)")
_D_MDY = re.compile(r"(?<![\w/.-])(0?[1-9]|1[0-2])( ?[/.-] ?)(0?[1-9]|[12]\d|3[01])\2((?:19|20)\d{2}|\d{2})(?![\w/]|[.-]\d)")
_D_YMD = re.compile(r"(?<![\w/.-])((?:19|20)\d{2})([/.-])(0?[1-9]|1[0-2])\2(0?[1-9]|[12]\d|3[01])(?![\w/]|[.-]\d)")
_D_DMY = re.compile(r"(?<![\w/.-])(1[3-9]|2\d|3[01])([/.-])(0?[1-9]|1[0-2])\2((?:19|20)\d{2})(?![\w/]|[.-]\d)")
_D_MON_D_Y = re.compile(r"(?i)\b(" + MONTHS + r")\.?\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?,?\s+((?:19|20)\d{2})\b")
_D_D_MON_Y = re.compile(r"(?i)\b(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?(?:\s+of)?[\s-]+(" + MONTHS +
                        r")\.?,?[\s-]+((?:19|20)\d{2}|\d{2})\b")
_D_MON_D = re.compile(r"(?i)\b(" + MONTHS + r")\.?\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\b(?!,?\s*(?:19|20)\d{2})(?!\d)")
_D_MON_Y = re.compile(r"(?i)\b(" + MONTHS + r")\.?,?\s+((?:19|20)\d{2})\b")
_D_YMD8 = re.compile(r"(?<![\w])((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?![\w])")
# "May" / "March" alone are too ambiguous; month-only words need a digit next to them (handled above).


def _valid_date(y: int, m: int, d: int) -> bool:
    if y < 100:
        y += 2000 if y <= 40 else 1900
    try:
        date(y, m, d)
    except ValueError:
        return False
    return 1880 <= y <= 2100


def _month_num(name: str) -> int:
    return _MONTH_NUM[name.lower()[:3]]


_DATE_LABEL = re.compile(r"(?i)(?:\bd\.?\s?o\.?\s?b\b|date\s*of\s*birth|birth\s*date|birthdate|birthday|\bborn\b|"
                         r"\bnacido\b|fecha\s+de\s+nacimiento|(?:visit|service|admit|admission|discharge|loss|"
                         r"incident|accident|injury|crash|report|exam|surgery|procedure|hire|termination|death|"
                         r"signature|signed|effective|expiration|issue|filing|filed|dos|doi|dol|statement|due|"
                         r"start|end|onset|appointment|appt|arrival|test|collection|order|entry|review)\s*(?:date|on)?\b"
                         r"|\bdate\b)")


def _is_dob(nt: NormText, s: int, e: int) -> bool:
    """A date is a DOB when the *nearest* date label before it on the same line is a birth label
    ("DOB: 1/2/80   Visit Date: 4/21/22" → only the first). A birth label on the line above counts
    only for a value that starts its own line (table column)."""
    t = nt.lower
    ls = t.rfind("\n", 0, s) + 1
    left = t[max(ls, s - 60):s]
    labs = list(_DATE_LABEL.finditer(left))
    if labs:
        # another field label between the birth label and this date ("DOB: 11/03/1966   Collected: 05/12/2025")
        between = left[labs[-1].end():]
        if not re.match(r"\s*[/&]", between) and re.search(r"[a-z][a-z /]{1,25}:\s*$|\d\s{2,}[a-z]", between):
            return False
        return bool(DOB_CTX.search(labs[-1].group()) or re.search(r"birth|born|nacid|nacimiento|d\.?\s?o\.?\s?b",
                                                                  labs[-1].group()))
    if DOB_CTX.search(t[e:e + 4]):
        return True
    if re.fullmatch(r"\s*(?:\d{1,2}\s+)?(?:a[.:]|answer:?|response:?)?\s*", t[ls:s]) and ls > 0:
        pls = t.rfind("\n", 0, ls - 1) + 1
        prev = t[pls:ls]
        plabs = list(_DATE_LABEL.finditer(prev))
        return len(plabs) == 1 and bool(re.search(r"birth|born|d\.?\s?o\.?\s?b", plabs[0].group()))
    return False


def find_dates(nt: NormText) -> Iterator[Span]:
    t = nt.text
    hits: list[tuple[int, int, str, float]] = []
    for m in _D_MDY.finditer(t):
        if _valid_date(int(m.group(4)), int(m.group(1)), int(m.group(3))):
            hits.append((*m.span(), "mdy", 0.9 if len(m.group(4)) == 4 else 0.8))
    for m in _D_YMD.finditer(t):
        if _valid_date(int(m.group(1)), int(m.group(3)), int(m.group(4))):
            hits.append((*m.span(), "ymd", 0.9))
    for m in _D_DMY.finditer(t):
        if _valid_date(int(m.group(4)), int(m.group(3)), int(m.group(1))):
            hits.append((*m.span(), "dmy", 0.85))
    for m in _D_MON_D_Y.finditer(t):
        if _valid_date(int(m.group(3)), _month_num(m.group(1)), int(m.group(2))):
            hits.append((*m.span(), "mon_d_y", 0.95))
    for m in _D_D_MON_Y.finditer(t):
        if _valid_date(int(m.group(3)), _month_num(m.group(2)), int(m.group(1))):
            hits.append((*m.span(), "d_mon_y", 0.95))
    for m in _D_MON_D.finditer(t):
        if m.group(1).lower() == "may" and not m.group(1)[0].isupper():
            continue
        if _valid_date(2000, _month_num(m.group(1)), int(m.group(2))):
            hits.append((*m.span(), "mon_d", 0.65))
    for m in _D_MON_Y.finditer(t):
        if m.group(1).lower() in ("may", "march") and not m.group(1)[0].isupper():
            continue
        hits.append((*m.span(), "mon_y", 0.6))
    for m in _D_YMD8.finditer(t):
        s, e = m.span()
        if _ctx(nt, s, e, re.compile(r"\b(?:date|dob|born|d\.o\.b|birthdate|birth\s*date|birthday)\b"), 30, 0) and \
                _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3))):
            hits.append((s, e, "ymd8", 0.8))
    for s, e, fmt, score in hits:
        if _is_dob(nt, s, e):
            yield _span(nt, s, e, "DATE_OF_BIRTH", 0.97, f"pattern:dob_{fmt}", "date with birth-date context")
        else:
            yield _span(nt, s, e, "DATE", score, f"pattern:date_{fmt}", "calendar date")


_AGE = re.compile(r"(?i)\b(\d{1,3})(?:[- ]|\s*-\s*)(?:years?|yrs?|y)[- ](?:old|of\s+age)\b"
                  r"|\b(?:age|aged|edad)[\s:]{1,3}(\d{1,3})\b(?!\s*(?:%|percent|degrees|mph))"
                  r"|\b(\d{1,3})\s?(?:y/?o|yo|y\.o\.|yrs?\.?\s*old)\b"
                  r"|\b(\d{1,3})\s?(?:-|\s)?(?:month|week|day)s?[- ]old\b")
_DEMO = re.compile(r"(?i)\b(?:a|an|the)?\s*\d{1,3}[- ](?:year|yr)s?[- ]old\s+(?:(?:white|black|african[- ]american|"
                   r"hispanic|latino|latina|latinx|asian|caucasian|native\s+american|pacific\s+islander|"
                   r"middle[- ]eastern|arab|indian|mixed[- ]race|biracial|multiracial)\s+)?"
                   r"(?:male|female|man|woman|boy|girl|m|f|gentleman|lady|individual|person|patient|"
                   r"non-?binary|transgender\s+(?:man|woman))\b")


def find_age(nt: NormText) -> Iterator[Span]:
    for m in _AGE.finditer(nt.text):
        gi = next(i for i in range(1, 5) if m.group(i))
        if int(m.group(gi)) > 125:
            continue
        s, e = m.span()
        yield _span(nt, s, e, "AGE", 0.85, "pattern:age", "stated age")
    for m in _DEMO.finditer(nt.text):
        s, e = m.span()
        lead = re.match(r"(?i)\s*(?:(?:a|an|the)\s+)?", nt.text[s:e])
        s += lead.end() if lead else 0
        yield _span(nt, s, e, "DEMOGRAPHIC", 0.7, "pattern:demographic",
                    "age + sex/race descriptor narrows identity")


# ---------------------------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------------------------

_VIN = re.compile(r"(?<![A-Za-z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Za-z0-9])", re.I)
VIN_CTX = re.compile(r"\b(?:vin|v\.i\.n|vehicle\s*(?:id|identification)|chassis|serial)\b")


_STATES2 = ("AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|"
            "OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY")
_PLATE_AFTER_STATE = re.compile(rf"(?<![A-Za-z])(?!(?:ID|IN|OR|ME|OK|DE|PA|HI|OH|MA|LA|AL|CO|MD|MO|MS|MT|NE|SC|SD|VA|WA|WI)\b)(?:{_STATES2})[\s,]+((?=[A-Z0-9 -]*\d)(?=[A-Z0-9 -]*[A-Z])[A-Z0-9]{{2,4}}[ -]?[A-Z0-9]{{2,4}})"
                                rf"(?![A-Za-z0-9])")
_LIC_PLATE = re.compile(rf"\bLIC\.?\s+((?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{{5,8}})\s+(?:{_STATES2})\b")
_VEHICLE_CUE = re.compile(r"(?i)\b(?:ford|honda|toyota|chevy|chevrolet|nissan|ram|dodge|"
                          r"jeep|tesla|hyundai|kia|bmw|gmc|subaru|mazda|lexus|acura|volkswagen|buick|cadillac|odyssey|"
                          r"f-?\d{3}|truck|car|van|suv|sedan|pickup|vehicle|plates?|tags?|motorcycle)\b")
_DEVICE_SERIAL = re.compile(r"(?i)\b(?:axon|bwc|body\s*cam(?:era)?|dash\s*cam|device|tablet|camera|interlock)\b[^\n]{0,25}?"
                            r"(?<![\w-])((?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]{2,}(?:-[A-Z0-9]+)*[A-Z0-9])(?![\w-])")


def find_vin(nt: NormText) -> Iterator[Span]:
    for rx in (_PLATE_AFTER_STATE, _LIC_PLATE):
        for m in rx.finditer(nt.text):
            s, e = m.span(1)
            if rx is _LIC_PLATE or _VEHICLE_CUE.search(nt.text[max(0, s - 70):s]):
                if len(V.alnum(m.group(1))) >= 4:
                    yield _span(nt, s, e, "LICENSE_PLATE", 0.88, "pattern:plate_after_state", "plate after a state code")
    for m in _DEVICE_SERIAL.finditer(nt.text):
        v = m.group(1)
        if len(V.alnum(v)) >= 6 and sum(c.isdigit() for c in v) >= 3:
            s, e = m.span(1)
            yield _span(nt, s, e, "DEVICE_ID", 0.85, "pattern:device_serial", "device / camera serial number")
    for m in _VIN.finditer(nt.text):
        v = m.group().upper()
        if not V.vin_shape_ok(v):
            continue
        s, e = m.span()
        ctx = _ctx(nt, s, e, VIN_CTX)
        if V.vin_checkdigit_ok(v):
            yield _span(nt, s, e, "VIN", 0.98, "pattern:vin", "VIN with valid check digit")
        elif ctx:
            yield _span(nt, s, e, "VIN", 0.9, "pattern:vin_ctx", "VIN-shaped with VIN context")
        else:
            yield _span(nt, s, e, "VIN", 0.6, "pattern:vin_shape", "17-char VIN shape (non-NA check digit)")


# ---------------------------------------------------------------------------------------------
# Banking / crypto / international
# ---------------------------------------------------------------------------------------------

_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?(?![A-Za-z0-9])")
_SWIFT = re.compile(r"(?<![A-Za-z0-9])[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?(?![A-Za-z0-9])")
SWIFT_CTX = re.compile(r"\b(?:swift|bic|swift/bic|bank\s+identifier|wire)\b")
_BTC58 = re.compile(r"(?<![A-Za-z0-9])[13][a-km-zA-HJ-NP-Z1-9]{25,34}(?![A-Za-z0-9])")
_BECH = re.compile(r"(?<![A-Za-z0-9])(?:bc1|BC1)[ac-hj-np-z02-9AC-HJ-NP-Z]{11,71}(?![A-Za-z0-9])")
_ETH = re.compile(r"(?<![A-Za-z0-9])0x[a-fA-F0-9]{40}(?![A-Za-z0-9])")
_MBI = re.compile(r"(?<![A-Za-z0-9])[1-9][AC-HJKMNP-RT-Y][AC-HJKMNP-RT-Y0-9]\d-?[AC-HJKMNP-RT-Y][AC-HJKMNP-RT-Y0-9]"
                  r"\d-?[AC-HJKMNP-RT-Y]{2}\d{2}(?![A-Za-z0-9])", re.I)
_DEA = re.compile(r"(?<![A-Za-z0-9])[ABCDEFGHJKLMPRSTUX][A-Z9]\d{7}(?![A-Za-z0-9])")
_NINO = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2} ?\d{2} ?\d{2} ?\d{2} ?[A-D](?![A-Za-z0-9])")
_SIN = re.compile(r"(?<![\w-])\d{3}[ -]\d{3}[ -]\d{3}(?![\w]|[ -]\d)")
SIN_CTX = re.compile(r"\b(?:sin|social\s+insurance|nas|num[ée]ro\s+d'assurance)\b")
_NPI = re.compile(r"(?<![\w-])[12]\d{9}(?![\w-])")
NPI_CTX = re.compile(r"\bnpi\b|national\s+provider")
_EIN = re.compile(r"(?<![\w-])\d{2}-\d{7}(?![\w-])")
EIN_CTX = re.compile(r"\b(?:ein|fein|tin|tax\s*id|tax\s*identification|federal\s*(?:tax\s*)?id|employer\s*id)")
_IMEI = re.compile(r"(?<![\w-])\d{2}[- ]?\d{6}[- ]?\d{6}[- ]?\d(?![\w-])")
IMEI_CTX = re.compile(r"\b(?:imei|meid|esn|device|handset|phone\s+serial)\b")


_AADHAAR = re.compile(r"(?<![\w-])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![\w-])")
_PAN_IN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z](?![A-Za-z0-9])")


def find_financial_ids(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for m in _AADHAAR.finditer(t):
        s, e = m.span()
        if V.verhoeff_ok(m.group()) and _ctx(nt, s, e, re.compile(r"aadhaar|aadhar|uidai|\buid\b"), 80, 10):
            yield _span(nt, s, e, "NATIONAL_ID", 0.95, "pattern:aadhaar", "Aadhaar number, Verhoeff valid")
    for m in _PAN_IN.finditer(t):
        s, e = m.span()
        yield _span(nt, s, e, "NATIONAL_ID", 0.85 if _ctx(nt, s, e, re.compile(r"\bpan\b|permanent account"), 40, 5)
                    else 0.55, "pattern:india_pan", "Indian PAN format")
    for m in _IBAN.finditer(t):
        if V.iban_ok(m.group()):
            s, e = m.span()
            yield _span(nt, s, e, "IBAN", 0.98, "pattern:iban", "IBAN, mod-97 valid")
    for m in _SWIFT.finditer(t):
        s, e = m.span()
        if V.swift_ok(m.group()) and _ctx(nt, s, e, SWIFT_CTX, 50, 10):
            yield _span(nt, s, e, "SWIFT_BIC", 0.9, "pattern:swift", "SWIFT/BIC code with context")
    for m in _BTC58.finditer(t):
        if V.btc_base58_ok(m.group()):
            s, e = m.span()
            yield _span(nt, s, e, "CRYPTO_WALLET", 0.97, "pattern:btc", "Bitcoin address, checksum valid")
    for m in _BECH.finditer(t):
        if V.btc_bech32_ok(m.group()):
            s, e = m.span()
            yield _span(nt, s, e, "CRYPTO_WALLET", 0.97, "pattern:btc_bech32", "Bitcoin bech32 address")
    for m in _ETH.finditer(t):
        if V.eth_ok(m.group()):
            s, e = m.span()
            yield _span(nt, s, e, "CRYPTO_WALLET", 0.92, "pattern:eth", "Ethereum address")
    for m in _MBI.finditer(t):
        if V.mbi_ok(m.group()):
            s, e = m.span()
            yield _span(nt, s, e, "MEDICARE_ID", 0.92, "pattern:mbi", "Medicare Beneficiary Identifier")
    for m in _DEA.finditer(t):
        if V.dea_ok(m.group()):
            s, e = m.span()
            ctx = _ctx(nt, s, e, re.compile(r"\bdea\b"))
            # 2 letters + 7 digits passes the DEA checksum 1 time in 10 by chance: weak without "DEA" nearby
            yield _span(nt, s, e, "DEA_NUMBER", 0.97 if ctx else 0.6, "pattern:dea", "DEA number, checksum valid")
    for m in _NINO.finditer(t):
        if V.uk_nino_ok(m.group()):
            s, e = m.span()
            yield _span(nt, s, e, "NATIONAL_ID", 0.85, "pattern:uk_nino", "UK National Insurance number")
    for m in _SIN.finditer(t):
        s, e = m.span()
        if V.ca_sin_ok(m.group()) and _ctx(nt, s, e, SIN_CTX):
            yield _span(nt, s, e, "NATIONAL_ID", 0.92, "pattern:ca_sin", "Canadian SIN, Luhn valid")
    for m in _NPI.finditer(t):
        s, e = m.span()
        if V.npi_ok(m.group()):
            ctx = _ctx(nt, s, e, NPI_CTX, 40, 5)
            yield _span(nt, s, e, "NPI", 0.97 if ctx else 0.4, "pattern:npi", "NPI, Luhn valid")
    for m in _EIN.finditer(t):
        s, e = m.span()
        ctx = _ctx(nt, s, e, EIN_CTX, 45, 5)
        if V.ein_ok(m.group()) or ctx:
            business = re.search(r"(?i)\bfein\b|employer'?s?\s+(?:federal\s+)?(?:id|ein)|payer'?s?\s+tin",
                                 nt.text[max(0, s - 30):s])
            # an employer's FEIN identifies the employer, whose name is redacted too
            yield _span(nt, s, e, "EIN", 0.95 if ctx or business else 0.45, "pattern:ein",
                        "EIN format" + (" (an employer's / business EIN)" if business else ""))
    for m in _IMEI.finditer(t):
        s, e = m.span()
        if V.imei_ok(m.group()) and _ctx(nt, s, e, IMEI_CTX):
            yield _span(nt, s, e, "DEVICE_ID", 0.92, "pattern:imei", "IMEI, Luhn valid")


# ---------------------------------------------------------------------------------------------
# Legal / medical codes
# ---------------------------------------------------------------------------------------------

_FED_CASE = re.compile(r"(?i)\b\d{1,2}:\d{2}-(?:cv|cr|mc|mj|bk|ap|md|po|sw|gj|ml|mi)-\d{3,6}(?:-[A-Z]{1,5})*\b")
_STATE_CASE = re.compile(r"(?<![\w-])(?:(?:19|20)\d{2}|\d{2})[- ]?(?:CA|CV|CC|CR|CF|CT|DR|DP|SC|TR|MM|MO|CI|PR|"
                         r"CP|FC|JV|JD|GC|LT|SP|DV|PI|MD|SM|NC|AC|CM|IN|TX|DC|FA|FD)[- ]?\d{3,8}(?:[- ][A-Z0-9]{1,6})*(?![\w-])")
_ICD10 = re.compile(r"(?<![\w.])[A-TV-Z]\d[0-9AB](?:\.[0-9A-TV-Z]{1,4})(?![\w.])")
ICD_CTX = re.compile(r"\b(?:icd|icd-?10|dx|diagnos[ie]s|diagnosis\s+code|assessment)\b")


def find_legal_medical(nt: NormText) -> Iterator[Span]:
    for m in _FED_CASE.finditer(nt.text):
        s, e = m.span()
        yield _span(nt, s, e, "CASE_NUMBER", 0.95, "pattern:federal_case", "federal case number")
    for m in _STATE_CASE.finditer(nt.text):
        s, e = m.span()
        yield _span(nt, s, e, "CASE_NUMBER", 0.8, "pattern:state_case", "state case number format")
    for m in _ICD10.finditer(nt.text):
        s, e = m.span()
        if _ctx(nt, s, e, ICD_CTX, 120, 20):
            yield _span(nt, s, e, "MEDICAL_CONDITION", 0.8, "pattern:icd10", "ICD-10 diagnosis code")


# ---------------------------------------------------------------------------------------------
# Secrets spoken/written inline ("my PIN is 4821", "password: hunter2")
# ---------------------------------------------------------------------------------------------

_SECRET = re.compile(r"(?i)\b(?:password|passwd|pwd|passcode|pass\s*code|pin(?:\s*(?:number|code|no\.?))?|"
                     r"access\s*code|gate\s*code|alarm\s*code|door\s*code|lock\s*combination|combination)(?![a-z])"
                     r"(?:\s+(?:is|was|=|of))?\s*[:=#-]?\s*[\"']?([^\s\"',;]{3,64})")
_SECRET_STOP = {"is", "was", "the", "and", "for", "number", "code", "reset", "required", "protected", "change",
                "changed", "please", "enter", "field", "will", "must", "not", "that", "you", "your", "to", "be",
                "here", "below", "above", "n/a", "none", "manager", "policy", "protection", "pad"}


# "her door lock is 4471", "the gate code was 1985", "garage code: 7741"
_CODE_IS = re.compile(r"(?i)\b(?:door|gate|lock|alarm|garage|keypad|lockbox|safe)\s+(?:lock\s+|alarm\s+)?(?:code|combo|combination|pin)?"
                      r"(?:\s+for\s+\w+)?\s*(?:is|was|:)\s*([#*]?\d{3,8}[#*]?|\d(?:-\d){2,7}(?:\s+(?:star|pound|hash))?)(?!\d)"
                      r"|(?i:door|gate|lock|alarm|garage|keypad|front|back|building)\b[^\n]{0,40}?\bcode\s+(?:is|was|:)\s*"
                      r"([#*]?\d{3,8}[#*]?|\d(?:-\d){2,7}(?:\s+(?:star|pound|hash))?)(?!\d)")
_CODE_FOR = re.compile(r"(?i)\b(?:code|combination|combo|pin)\s+(?:for|to)\s+(?:the|her|his|my|their|our)?\s*(?:front\s+|back\s+|"
                       r"side\s+)?(?:door|gate|alarm|lock|garage|safe|keypad|apartment|building|house)(?:\s+lock)?"
                       r"(?:\W{0,4}|\s+(?:is|was)\s+)\(?\s*([#*]?\d{3,8}[#*]?)\s*\)?")


# "his code is -- I think it's 082497", "her phone passcode was 4417"
_PHONE_CODE = re.compile(r"(?i)\b(?:his|her|my|their|the|phone'?s?|cell'?s?)\s+(?:phone\s+|lock\s*screen\s+|unlock\s+)?"
                         r"(?:pass\s?code|code|pin)\s+(?:is|was|:)\s*(?:--\s*|-\s+)?(?:(?:I\s+think|like|maybe|um+|uh+|I\s+believe)"
                         r"[,]?\s+(?:it'?s\s+|it\s+was\s+)?)?(\d{4,8})(?![\d/])")
# "a scanner login, hmaldonado7", "username: jdoe_82" — a handle-shaped value (has a digit, dot or underscore)
_LOGIN_VALUE = re.compile(r"(?i)\b(?:log[- ]?in|user\s?name|user\s?id|screen\s?name|handle|gamertag)\b(?:\s+(?:is|was))?[ \t]*[,:]?"
                          r"\s+(?:(?:is|was)\s+)?([a-z][a-z0-9]*(?:[._][a-z0-9]+)*\d*)(?=[\s.,;)]|$)")


def find_secrets(nt: NormText) -> Iterator[Span]:
    for m in _PHONE_CODE.finditer(nt.text):
        yield _span(nt, *m.span(1), "PASSWORD", 0.88, "pattern:passcode", "phone / device passcode")
    for m in _LOGIN_VALUE.finditer(nt.text):
        val = m.group(1)
        if len(val) < 4 or not re.search(r"[\d._]", val) or re.fullmatch(r"\d+", val):
            continue
        yield _span(nt, *m.span(1), "USERNAME", 0.88, "pattern:login", "user name / login")
    for rx in (_CODE_FOR, _CODE_IS):
        for m in rx.finditer(nt.text):
            g = 1 if m.group(1) else 2
            s, e = m.span(g)
            yield _span(nt, s, e, "PASSWORD", 0.9, "pattern:access_code", "door / gate / alarm code")
    for m in _SECRET.finditer(nt.text):
        val = m.group(1)
        if re.search(r"(?i)\bwith\s*$", nt.text[max(0, m.start() - 6):m.start()]):
            continue  # "Card Purchase With Pin 08/14" is a transaction type
        if re.fullmatch(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", val):
            continue
        if val.lower().strip(".") in _SECRET_STOP or (val.isalpha() and val.islower() and len(val) > 12):
            continue
        sep = nt.text[m.start():m.start(1)]
        if val.isalpha() and val.islower() and not re.search(r"[:=]|\bis\b|\bwas\b|[\x22']", sep):
            continue  # "password provided separately", "pinned"
        s, e = m.span(1)
        if e > s and nt.text[e - 1] in ".:":
            e -= 1
        if s > 0 and nt.text[s - 1] == "#":
            s -= 1
        yield _span(nt, s, e, "PASSWORD", 0.9 if any(c.isdigit() for c in val) else 0.75, "pattern:secret",
                    "password / PIN / access code")


# ---------------------------------------------------------------------------------------------
# Spoken digit sequences (transcripts): "five five five, one two three four"
# ---------------------------------------------------------------------------------------------

_NUMWORD = (r"(?:zero|oh|o|one|two|three|four|five|six|seven|eight|nine|double|triple|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
            r"seventy|eighty|ninety|hundred|thousand|\d{1,4})")
_SPOKEN = re.compile(r"(?i)\b" + _NUMWORD + r"(?:[\s,.-]+(?:and\s+)?" + _NUMWORD + r"){6,}\b")
_W2D = {"zero": 1, "oh": 1, "o": 1, "one": 1, "two": 1, "three": 1, "four": 1, "five": 1, "six": 1,
        "seven": 1, "eight": 1, "nine": 1, "double": 1, "triple": 2}


def _spoken_digit_count(s: str) -> int:
    n = 0
    for w in re.findall(r"[a-z]+|\d+", s.lower()):
        if w.isdigit():
            n += len(w)
        elif w in ("double", "triple"):
            n += _W2D[w]
        elif w in _W2D:
            n += 1
        elif w in ("hundred", "thousand", "and"):
            continue
        else:
            n += 2  # "twenty", "fifteen" etc. stand for 2 digits
    return n


def find_spoken_numbers(nt: NormText) -> Iterator[Span]:
    for m in _SPOKEN.finditer(nt.text):
        if not re.search(r"(?i)[a-z]", m.group()):
            continue  # pure digits are handled by the other recognizers
        n = _spoken_digit_count(m.group())
        s, e = m.span()
        lw = window(nt.lower, s, e, 80, 10)
        if n == 9 and SSN_CTX.search(lw):
            ent = "SSN"
        elif n in (15, 16) and CARD_CTX.search(lw):
            ent = "CREDIT_CARD"
        elif n in (7, 10, 11) and PHONE_CTX.search(lw):
            ent = "PHONE"
        elif n in (3, 4) and _CVV.pattern and re.search(r"cvv|security code|pin", lw):
            ent = "CVV"
        elif re.search(r"account|acct|routing", lw):
            ent = "BANK_ACCOUNT"
        elif n >= 7:
            ent = "ID_NUMBER"
        else:
            continue
        yield _span(nt, s, e, ent, 0.85, "pattern:spoken_digits", f"spoken {n}-digit number")


# ---------------------------------------------------------------------------------------------
# Transcripts: speech recognisers group digits arbitrarily ("523 -719921", "4 1 1 1 1111 1111")
# ---------------------------------------------------------------------------------------------

_DIGIT_RUN = re.compile(r"(?<![\w$])\d(?:[\d]|[ ,.\-]{1,3}(?=\d)){2,30}(?![\w])")
ACCOUNT_CTX = re.compile(r"\b(?:account|acct|routing|member|policy|claim|case|ticket|confirmation|card|pin|id)\b")


# how people give a phone number out loud: "my number is …", "reach me at …", "text me at …"
_SPOKEN_PHONE_CTX = re.compile(r"\b(?:my|his|her|your|their|the\s+callback|a\s+good)\s+number|reach\s+(?:me|him|her|us)|"
                               r"call\s+(?:me|him|her|us)|text\s+(?:me|him|her|us)|callback|call\s+back")


# a long letters+digits token spoken aloud is an identifier even when the label was misheard
# ("The plane number is CLN20230045871", "Member Eid is XOD884417203")
_SPOKEN_ALNUM_ID = re.compile(r"(?<![\w-])(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z][A-Z0-9-]{7,24}(?![\w-])")


def find_transcript_numbers(nt: NormText) -> Iterator[Span]:
    for m in _SPOKEN_ALNUM_ID.finditer(nt.text):
        if sum(c.isdigit() for c in m.group()) >= 5:
            yield _span(nt, *m.span(), "ID_NUMBER", 0.8, "pattern:transcript_id", "spoken identifier")
    for m in _DIGIT_RUN.finditer(nt.text):
        raw = m.group()
        d = V.digits(raw)
        if "\n" in raw:
            continue
        s, e = m.span()
        lw = window(nt.lower, s, e, 90, 15, prev_line=False)
        if len(d) < 4 and not (len(d) == 3 and re.search(r"cvv|cvc|security code", lw)):
            continue
        ent, why = None, ""
        if len(d) == 9 and SSN_CTX.search(lw):
            ent, why = "SSN", "spoken 9-digit number with SSN context"
        elif 13 <= len(d) <= 19 and (CARD_CTX.search(lw) or V.credit_card_ok(d)):
            ent, why = "CREDIT_CARD", "spoken card number"
        elif len(d) in (7, 10, 11) and (PHONE_CTX.search(lw) or _SPOKEN_PHONE_CTX.search(lw)):
            ent, why = "PHONE", "spoken phone number"
        elif len(d) == 9 and re.search(r"\brouting\b", lw):
            ent, why = "ROUTING_NUMBER", "spoken routing number"
        elif re.search(r"\b(?:account|acct)\b", lw):
            ent, why = "BANK_ACCOUNT", "spoken account number"
        elif len(d) in (3, 4) and re.search(r"cvv|security code|\bpin\b", lw):
            ent, why = "CVV" if "pin" not in lw else "PASSWORD", "spoken card code / PIN"
        elif len(d) >= 6 and ACCOUNT_CTX.search(lw):
            ent, why = "ID_NUMBER", "spoken identifier"
        if ent:
            yield _span(nt, s, e, ent, 0.9, "pattern:transcript_number", why)


ALL_PATTERN_FINDERS = [find_partial_numbers, find_immigration_ids, find_ssn, find_cards, find_card_extras, find_phones, find_digital, find_gps, find_dates,
                       find_age, find_vin, find_financial_ids, find_legal_medical, find_secrets,
                       find_spoken_numbers]
# finders worth re-running on the OCR digit-confusion variant of scanned text
NUMERIC_FINDERS = [find_ssn, find_cards, find_phones, find_dates, find_financial_ids]
