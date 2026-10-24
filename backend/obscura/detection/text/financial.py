"""Financial documents: bank / card statements, checks, tax forms, pay stubs, loans, credit reports, wires.

Statement lines name people in places prose rules never look ("ONLINE TRANSFER TO DAVID CHEN XXXXXX8812",
"VENMO *JSMITH1987", "CHECK 1042 PAID TO R. OKAFOR"), and account numbers come masked in a dozen styles
("x-8812", "517805XXXXXX", "6045****1188", MICR lines on checks). These finders cover those layouts.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from .base import NormText, Span

_CAPWORD = r"[A-Z][A-Za-z'’.-]*"
# a name in a statement line: 1–4 words, stops at account masks, references, dates, amounts
_STMT_NAME = rf"({_CAPWORD}(?:[ ]{_CAPWORD}){{0,3}}?)"
_STMT_STOP = (r"(?=\s+(?:X{2,}|x{2,}|\*{2,}|#|REF\b|Ref\b|CONF\b|Conf\b|ON\s+\d|on\s+\d|ID\b|TRN\b|TXN\b|ACCT\b|Acct\b|"
              r"ACCOUNT\b|SAV\b|CHK\b|MEMO\b|Memo\b|FOR\b|for\b|\d)|\s*$|\s{2,}|\s*[,;(])")
_NOT_PARTY = {"SAVINGS", "CHECKING", "SAV", "CHK", "ACCOUNT", "ACCT", "LOAN", "CARD", "CREDIT", "BROKERAGE", "IRA",
              "SHARE", "MONEY", "MARKET", "EXTERNAL", "INTERNAL", "SELF", "MYSELF", "OWN", "BANK", "THE", "YOUR", "MY"}

_TRANSFER_PARTY = re.compile(
    r"(?i:(?:online|mobile|internet|external|book|wire|ach|bank|instant|real[- ]time|p2p)\s+)?"
    r"(?i:transfer|xfer|tfr|payment|pmt|send|sent|deposit)\s+(?i:to|from)\s+" + _STMT_NAME + _STMT_STOP)
_CHECK_PAYEE = re.compile(r"(?i:check|chk|ck)\s*#?\s*\d{2,7}\s+(?i:paid\s+to|payable\s+to|to|payee:?)\s+" + _STMT_NAME
                          + _STMT_STOP)
# P2P apps print the counterparty's handle or display name after an asterisk
_P2P_STAR = re.compile(r"(?i:venmo|cash\s*app|square\s*cash|zelle|apple\s*cash|paypal(?=\s*\*\s*[A-Z]+ [A-Z]+\b))\s*\*\s*([A-Za-z0-9][A-Za-z0-9._ -]{1,30}?)"
                       r"(?=\s*\*|\s{2,}|\s+[A-Z]{2,}\s+[A-Z]{2}\b|\s+\d|\s*$)")
# ACH addenda: "IND NAME:REYES, ANTHONY J", "IND ID:000045771"
_ACH_IND_ID = re.compile(r"(?i)\bIND(?:IVIDUAL)?\s*ID\s*[:#]\s*([A-Z0-9-]{4,22})")
_ACH_CO_NAME = re.compile(r"(?i)\b(?:ORIG(?:INATOR)?\s+)?CO(?:MPANY)?\s+NAME\s*:")

# masked numbers
_MASK_PREFIX = re.compile(r"(?<![\w*])(\d{2,12})([Xx*•]{2,12})(\d{0,4})(?![\w*])")     # 517805XXXXXX, 6045****1188
_MASK_RUN = re.compile(r"(?<![\w*])(?:[Xx*•]{4,16}|[Xx*•]{2,4}(?:[ -][Xx*•]{2,4}){1,3}[ -]?)(\d{4})(?!\d)")  # XXXXXX8812
_MASK_SHORT = re.compile(r"(?i)\b(savings|checking|account|acct|card|loan|sav|chk|debit|credit|share|ira|brokerage)\b"
                         r"[^\n\d]{0,12}?(?<![A-Za-z])x-?(\d{4})(?!\d)")                   # Savings x-8812

# MICR line on checks: ⑆routing⑆ account⑈ check, often OCR'd as A…A …C or |:…|: …||'
_MICR = re.compile(r"(?:⑆|(?<![A-Za-z0-9])A|\|:|:)(\d{9})(?:⑆|A(?![A-Za-z0-9])|\|:|:)\s*(\d[\d -]{2,16}\d)\s*(?:⑈|C(?![A-Za-z0-9])|\|\|'?|\")")

_SECURITY_ANSWER = re.compile(
    r"(?i)(?:security|secret|challenge|verification)\s+(?:question|answer)s?\b[^\n]{0,80}?\b(?:answer|ans\.?|a)\s*[:=-]\s*"
    r"([^\n;,.]{2,40}?)(?=\s*(?:[;,.\n]|$|\s{2,}))"
    r"|(?i:mother'?s\s+maiden\s+name|first\s+pet'?s\s+name|city\s+of\s+birth|high\s+school\s+mascot)\s*[:?=-]\s*"
    r"(?:answer\s*[:=-]\s*)?([A-Z][^\n;,.?]{1,30}?)(?=\s*(?:[;,.\n]|$|\s{2,}))")

_STATE_ID = re.compile(r"(?i)employer'?s\s+state\s+(?:id|i\.d\.)\s*(?:number|no\.?|#)?[^\n]*\n[ \t]*[A-Z]{2}[ \t]+"
                       r"([0-9A-Z][0-9A-Z-]{4,20})")
_MERS_MIN = re.compile(r"(?i)\bMIN\s*(?:#|no\.?|number)?\s*[:#]?\s*(\d{7}-?\d{10}-?\d)\b")
_LOAN_TYPE = re.compile(r"(?i)\b(?:auto|car|vehicle|student|personal|home\s+equity|heloc|mortgage|installment|payday|title)"
                        r"\s+loan\s*(?:#|no\.?|number|acct|account)?\s*[:#]?\s*([A-Z]{0,4}-?\d[\d-]{4,18}\d)\b")
_PAREN_HOLDER = re.compile(r"(?i:iban|account|acct|a/c|beneficiary)[^\n()]{4,60}\(\s*([A-Z][a-z]+(?:[ '-][A-Z][a-z]+){1,3})\s*\)")


# "RECIPIENT'S name\nDANIELA M OKONKWO" — tax-form / application name boxes with the value on the next line
_NAME_BOX = re.compile(r"(?im)^[ \t]*[a-z]?[ \t]*(?:recipient|payer|payee|employee|borrower|co-?borrower|debtor|taxpayer|"
                       r"account\s*holder|owner|beneficiary|transferor|lender|student|parent)['’]?s?\s+(?:first\s+)?"
                       r"name\b[^\n]*\n[ \t]*([A-Z][A-Za-z.'’-]+(?:[ ][A-Z][A-Za-z.'’-]*){1,4})[ \t]*$")
_ORG_HINT = re.compile(r"(?i)\b(?:inc|llc|l\.l\.c|corp|corporation|company|co\.|bank|n\.a\.|trust\s+co|credit\s+union|fcu|"
                       r"visa|mastercard|amex|american\s+express|discover|card|cards|loan|loans|mortgage|financial|"
                       r"capital|auto|insurance|mutual|savings|paypal|lending|finance|servicing|utilities|energy|"
                       r"electric|water|gas|wireless|mobile|telecom|cable|"
                       r"services|group|partners|lp|llp|fund|association|university|hospital|county|state\s+of|"
                       r"department|irs|treasury)\b")
# financial status: "FICO Score 8 is 612", "net worth is approximately $1.2 million", "annual income of $84,000"
_CREDIT_SCORE = re.compile(r"(?i)\b(?:fico|vantage\s*score|credit)\s*(?:score)?\s*(?:\d\s+)?(?:is|was|of|:)?\s*"
                           r"(?<![\d.$])([3-8]\d{2})(?![\d,.%])")
_STATUS = re.compile(r"(?i)\b(net\s+worth|annual\s+(?:household\s+)?income|household\s+income|gross\s+(?:annual\s+)?income|"
                     r"monthly\s+(?:gross\s+)?income|take-?home\s+pay|debt-to-income(?:\s+ratio)?|total\s+(?:assets|liabilities))"
                     r"\b[^.\n]{0,40}?(?:\$\s?\d[\d,.]*(?:\s*(?:million|thousand|k|m)\b)?|\d{1,3}(?:\.\d+)?\s?%)")
# "c Employer's name, address, and ZIP code\n  ELLERY ROOFING & GUTTERS LLC" (W-2 box c and similar)
_EMPLOYER_BOX = re.compile(r"(?im)^[ \t]*[a-z]?[ \t]*employer['’]?s\s+name\b[^\n]*\n[ \t]*([A-Z0-9][^\n]{2,70}?)[ \t]*$")
# lists of people after an owner / alias label: "Account Owners: A and B", "Also known as: X; Y"
_PEOPLE_LIST = re.compile(r"(?im)\b(?:account\s+owners?|joint\s+owners?|owners?\s+of\s+record|co-?owners?|"
                          r"statement\s+for|prepared\s+for|customer\s+name|primary\s+owner|also\s+known\s+as|a\.?k\.?a\.?|"
                          r"other\s+names?\s+used)\s*:\s*([^\n]{3,160})")
_LIST_NAME = re.compile(r"([A-Z][A-Za-z'’.-]*(?:[ ][A-Z][A-Za-z'’.-]*){1,4})")
_ORDER_OF = re.compile(r"(?i)pay\s+to\s+the\s+order\s+of[:\s]+([A-Z][A-Za-z.'’-]+(?:[ ][A-Z][A-Za-z.'’-]+){0,3})")
_ENDORSE = re.compile(r"(?i)\bendorse(?:d|ment)\b[^\n]{0,90}?(?:—|–|\s-\s|\bby:?)\s*([A-Z][a-z]+(?:[ ][A-Z][a-z.'’-]+){1,3})")


# OFX / QFX / QBO downloads: <ACCTID>4831007299 <BANKID>021000021; QIF: "P" payee lines; MT940 :25: account
_OFX_TAG = re.compile(r"(?i)<(ACCTID|BANKID|BRANCHID|ACCTKEY|USERID|USERPASS|NAME|PAYEEID|MEMO)>\s*([^<\r\n]{1,80})")
_QIF_PAYEE = re.compile(r"(?m)^P([A-Z][^\n]{1,60})$")
_MT940_ACCOUNT = re.compile(r"(?m)^:25:\s*([A-Z0-9/ -]{6,40})$")


# ---- round 2: layouts found on the independent financial development documents ------------------------------
_X_DASH = re.compile(r"(?<![\w])[xX]-(\d{4})(?![\d])|(?<=[A-Za-z] )\*(\d{4})(?![\d])")      # LN x-4417, FCU *0418
_DOTS = re.compile(r"(?<![\w.])\.{3}\s?(\d(?:[\d]|[ -](?=\d)){1,11})(?![\d])")            # ...8126, ...20-17, ...11 84 07
_CARD_TXN = re.compile(r"\bCARD\s+#?\s*(\d{4})(?![\d/,.])")                               # POS ... CARD 5106
_ENDING_ANY = re.compile(r"(?i)\bending(?:\s+in)?\s*[:#]?\s*(\d{4})(?![\d/])")
_NOT_ACCT_ENDING = re.compile(r"(?i)(?:year|period|quarter|month|week|fiscal|date|qtr|fy|season|term)s?\s*$")
_MASK_GROUPS = re.compile(r"(?<![\w*])((?:[\dXx*•]{2,6}[ -]){1,4}[\dXx*•]{2,6})(?![\w*])")  # 4147 54XX XXXX 4158
_MICR_ANY = re.compile(r"(?<![\w])[⑆⑈A-D|:\"]{1,3}(\d{9})[⑆⑈A-D|:\"]{1,3}\s*(\d(?:[\d]|[ -](?=\d)){3,18})\s*[⑆⑈A-D|:\"'‘’]{1,3}")
_BOFD = re.compile(r">\s?(\d{9})\s?<")                                                    # deposit stamp >211390839<
_RT = re.compile(r"\b(?:RT|R/T|RTN|ABA)\s*#?\s*:?\s*(\d{9})\b")
_CASHTAG = re.compile(r"(?<![\w$])(\$[A-Za-z][A-Za-z0-9_]{2,19})(?![\w])")
_SIGN_IN_AS = re.compile(r"(?i)\b(?:sign(?:ed)?\s+in\s+as|log(?:ged)?\s+in\s+as|user(?:name|\s*id)?|login|handle|"
                         r"processed\s+by|submitted\s+(?:\d\S*\s+)*by|entered\s+by|by)\s+[\"“]?"
                         r"((?=[a-z0-9._]*[a-z])[a-z][a-z0-9]*(?:[._][a-z0-9]+)+)[\"”]?(?![\w@]|\.(?:com|org|net|gov|edu|io)\b)")
_QUOTED_HANDLE = re.compile(r"(?i)\b(?:buyer|user|member|seller|customer|account)\s+[\"“]([A-Za-z0-9][A-Za-z0-9._-]{2,30})"
                            r"\*{0,6}[\"”]|user\s*id[^\n\"“]{0,30}[\"“]([A-Za-z0-9._-]{3,30})\*{0,6}[\"”]")
_ENS = re.compile(r"\b([a-z0-9-]{3,40}\.eth)\b")
_IP_PIN = re.compile(r"(?i)identity\s+protection\s+pin[^\n]{0,70}?(\d{6})\b")
_CODE_SAID = re.compile(r"(?i)(?<!business\s)(?<!activity\s)(?<!naics\s)(?<!zip\s)(?<!area\s)(?<!postal\s)(?<!promo\s)"
                        r"(?<!product\s)(?<!discount\s)(?<!country\s)(?<!tax\s)\b(?:code|pin|passcode|otp|one-?time\s+(?:code|passcode))\b"
                        r"[^\n]{0,45}?\b(?:it\s+was|it's|is|was)"
                        r"\s*[\"“']?(\d{4,8})\b")
_SPELLED_CODE = re.compile(r"(?i)\b(?:code|pin|digits|passcode)\b[^\n]{0,40}?((?:(?:zero|one|two|three|four|five|six|seven|"
                           r"eight|nine|oh)[ ,-]+){3,8}(?:zero|one|two|three|four|five|six|seven|eight|nine|oh))\b")
_PASSWORD_SAID = re.compile(r"(?i)\b(?:pw|pwd|password|pass\s?word|temporary\s+password|new\s+password)\b[^\n]{0,90}?(?:\n[^\n]{0,20}?)?"
                            r"(?:\bis:?|:|=|\bwas\b|\s-+)\s*[\"“']?((?=\S*[A-Za-z])(?=\S*[\d!@#$%^&*])[^\s\"”',]{6,40})"
                            r"|(?i:\bpw\s+)((?=\S*[A-Za-z])(?=\S*[\d!@#$%^&*])[^\s\"”',]{6,40})")
_PASSPHRASE = re.compile(r"(?i)pass\s?phrase[^\n\"“]{0,60}[\"“]([^\"”]{4,60})[\"”]")
_SPACED_PIN = re.compile(r"(?i)\bpin\b[^\n]{0,30}?[-:]\s*((?:\d\s){3,7}\d)\b")
# "Court of Common Pleas of Lehigh County, No. 2026-C-1418", "Gen. Sess. No. 26-GS-1170", "Probate No. ESPR 014471"
_COURT_NO = re.compile(r"(?i)(?:\b(?:court|county|district|division|session|probate|chancery|superior|bankruptcy)\b|"
                       r"\b(?:ct|sess|co)\.)[^\n]{0,70}?\bNo\.?\s*:?\s*((?=[A-Z0-9 -]*\d{3})[A-Z0-9]{1,8}(?:[ -][A-Z0-9]{1,10}){0,4})(?![\w-])")
_IND_NAME = re.compile(r"(?m)\bIND(?:IVIDUAL)?\s+NAME\s*:?\s*([A-Z][A-Z' ,.-]+?)(?=\s{2,}|\s*$)")
_WIRE_PARTY = re.compile(r"(?m)^[ \t]*(?:BENE|BNF|BENEFICIARY|OBI)\s*:?[ \t]+([A-Z][A-Z.' -]{2,40}?)[ \t]*$")
_STUDENT = re.compile(r"\bSTUDENT\s+([A-Z][A-Z'-]+(?: [A-Z]\.?)?)\s+ID\b")
_IN_RE = re.compile(r"(?i:in\s+re\s+(?:the\s+)?(?:marriage|estate|matter|custody|guardianship|conservatorship)\s+of)\s+"
                    r"([A-Z][a-z]+(?:\s[A-Z]\.)?(?:\s[A-Z][A-Za-z'’-]+)+)(?:,?\s+and\s+([A-Z][a-z]+(?:\s[A-Z]\.)?(?:\s[A-Z][A-Za-z'’-]+)+))?")
_MINOR_INITIALS = re.compile(r"(?:\b(?:for|FBO|[Pp]assenger|[Cc]hild|[Ss]on|[Dd]aughter|[Gg]randson|[Gg]randdaughter|[Mm]inor)"
                             r"\s+)([A-Z]\.[A-Z]\.)|\b([A-Z]\.[A-Z]\.)(?=,?\s*(?:\(age\s*\d|a\s+minor|minor\b|\(\d{1,2}\)))")
_FOR_CHILD = re.compile(r"\b(?:529(?:\s+plan)?|school\s+fees|tuition|college\s+fund|allowance|UTMA|UGMA|custodial\s+account)"
                        r"\s+for\s+([A-Z][a-z]{2,})(?:\s+and\s+([A-Z][a-z]{2,}))?")
_EMPLOYER_NO_COLON = re.compile(r"(?m)\b(?:Employer|E(?:m|rn)p[l1]oyer)[ \t]{1,4}(?!name|'s|’s|id|ID|EIN|ein|\(|:)"
                                r"([A-Z][A-Za-z&.,'’ -]{3,60}?)(?=\s{2,}|[ \t]*$)")
_GROUP_EMPLOYER = re.compile(r"(?im)^[ \t]*(?:group(?:\s+name)?|employer\s+group|plan\s+sponsor|plan\s+name)\s*:[ \t]*"
                             r"(?!no\b|#)([A-Z][^\n]{3,60}?)(?=\s{2,}|\s*$)")
_VOE = re.compile(r"(?i)verification\s+of\s+employment\s*\(([^)\n]{3,120})\)")
_PLAN_SPONSOR = re.compile(r"\b(?:TTEE|FBO|TRUSTEE)?\s*([A-Z][A-Z&.'’ ]{3,50}?)\s+401\s*\(?K\)?")


# an account-shaped number on a line that names an account / institution ("Toyota Financial Svcs 7020-4418-3361",
# "Traditional IRA 7Q2-418826", "Nelnet (student) 9000418226") — not amounts, dates, phones or references
_ACCT_LINE = re.compile(r"(?i)\b(?:ira|roth|401\s*\(?k\)?|403\s*\(?b\)?|sep|brokerage|checking|savings|share|certificate|cd\b|"
                        r"money\s+market|heloc|mortgage|loan|installment|revolving|auto|student|financial|bank|fcu|credit\s+union|"
                        r"servicing|lending|finance|direct\s+(?:subsidized|unsubsidized|plus)|parent\s+plus|account|acct)\b")
_ACCT_TOKEN = re.compile(r"(?<![\w$.,/:#-])((?=(?:[0-9A-Z-]*?\d){7})[0-9A-Z]{1,9}(?:-[0-9A-Z]{1,12}){0,4})(?![\w.,/%:-])")
_REF_BEFORE = re.compile(r"(?i)(?:ref|trace|trn|txn|conf|confirmation|imad|omad|fed\s+ref|auth|id|invoice|po|order|check|chk|"
                         r"ck|batch|serial|cusip|isin|naics|sic|form|rev|no|npi|nmls|ein|tin|ssn|phone|fax|tel)\.?\s*#?\s*:?\s*$")


def _span(nt: NormText, s: int, e: int, entity: str, score: float, source: str, why: str) -> Span:
    os_, oe = nt.to_original(s, e)
    return Span(os_, oe, entity, score, source, nt.original[os_:oe], why)


def _party_ok(name: str) -> bool:
    words = name.replace(",", " ").split()
    if not words or all(w.upper().strip(".'’") in _NOT_PARTY for w in words):
        return False
    if words[0].upper() in _NOT_PARTY:
        return False
    return any(len(w.strip(".'’")) >= 2 for w in words)


def find_financial(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for rx, src, why in ((_TRANSFER_PARTY, "fin:transfer_party", "person on the other side of a transfer"),
                         (_CHECK_PAYEE, "fin:check_payee", "payee of a check")):
        for m in rx.finditer(t):
            name = m.group(1).rstrip(" .")
            if _party_ok(name) and not _ORG_HINT.search(name):
                yield _span(nt, m.start(1), m.start(1) + len(name), "PERSON", 0.86, src, why)
    for m in _P2P_STAR.finditer(t):
        v = m.group(1).strip()
        if len(v) >= 2 and v.upper() not in _NOT_PARTY:
            ent = "USERNAME" if re.search(r"\d|[._]", v) or " " not in v and v.islower() else "PERSON"
            yield _span(nt, m.start(1), m.start(1) + len(m.group(1).rstrip()), ent, 0.86, "fin:p2p_party",
                        "counterparty of a payment-app transaction")
    for m in _ACH_IND_ID.finditer(t):
        yield _span(nt, *m.span(1), "ID_NUMBER", 0.88, "fin:ach_ind_id", "individual id in an ACH entry")
    for m in _MASK_PREFIX.finditer(t):
        if len(m.group(2)) < 4 and len(m.group(1)) < 6:
            continue  # "12XX" is too short to be an account
        for g in (1, 3):
            if m.group(g) and len(m.group(g)) >= 4:
                yield _span(nt, *m.span(g), "BANK_ACCOUNT", 0.88, "fin:masked_number", "visible digits of a masked account")
    for m in _MASK_RUN.finditer(t):
        yield _span(nt, *m.span(1), "BANK_ACCOUNT", 0.88, "fin:masked_number", "visible digits of a masked account")
    for m in _MASK_SHORT.finditer(t):
        yield _span(nt, *m.span(2), "BANK_ACCOUNT", 0.88, "fin:masked_number", "last digits of an account")
    for m in _MICR.finditer(t):
        if _aba_ok(m.group(1)):
            yield _span(nt, *m.span(1), "ROUTING_NUMBER", 0.97, "fin:micr", "routing number on a check's MICR line")
            yield _span(nt, *m.span(2), "BANK_ACCOUNT", 0.95, "fin:micr", "account number on a check's MICR line")
    for m in _SECURITY_ANSWER.finditer(t):
        g = 1 if m.group(1) else 2
        yield _span(nt, *m.span(g), "PASSWORD", 0.9, "fin:security_answer", "answer to a security question")
    for m in _STATE_ID.finditer(t):
        yield _span(nt, *m.span(1), "ID_NUMBER", 0.88, "fin:state_tax_id", "employer's state tax ID")
    for m in _MERS_MIN.finditer(t):
        yield _span(nt, *m.span(1), "ID_NUMBER", 0.9, "fin:mers_min", "mortgage identification number (MERS MIN)")
    for m in _LOAN_TYPE.finditer(t):
        yield _span(nt, *m.span(1), "BANK_ACCOUNT", 0.9, "fin:loan_number", "loan number")
    for m in _PAREN_HOLDER.finditer(t):
        yield _span(nt, *m.span(1), "PERSON", 0.85, "fin:account_holder", "account holder named next to the account")
    for m in _NAME_BOX.finditer(t):
        v = m.group(1)
        if not _ORG_HINT.search(v):
            yield _span(nt, *m.span(1), "PERSON", 0.9, "kv:fin_name_box", "name entered in a form's name box")
        elif re.match(r"(?i)\s*[a-z]?\s*(?:payer|employer)", t[m.start():m.start(1)]):
            yield _span(nt, *m.span(1), "EMPLOYER", 0.85, "kv:fin_employer_box", "payer / employer named on a tax form")
    for m in _EMPLOYER_BOX.finditer(t):
        yield _span(nt, *m.span(1), "EMPLOYER", 0.88, "kv:fin_employer_box", "employer named on a tax / pay form")
    for m in _PEOPLE_LIST.finditer(t):
        base = m.start(1)
        body = re.split(r"\s{2,}|\(", m.group(1))[0]
        for piece in re.split(r"\s*(?:;|,|&|\band\b|\bAND\b|/)\s*", body):
            nm = _LIST_NAME.fullmatch(piece.strip(" ."))
            if not nm or _ORG_HINT.search(piece) or not _party_ok(piece):
                continue
            s0 = base + body.find(piece.strip(" ."))
            yield _span(nt, s0, s0 + len(piece.strip(" .")), "PERSON", 0.9, "kv:fin_people_list",
                        "person named in an owner / alias list")
    for m in _OFX_TAG.finditer(t):
        tag, val = m.group(1).upper(), m.group(2).rstrip()
        ent = {"ACCTID": "BANK_ACCOUNT", "ACCTKEY": "BANK_ACCOUNT", "BANKID": "ROUTING_NUMBER", "BRANCHID": "ID_NUMBER",
               "USERID": "USERNAME", "USERPASS": "PASSWORD", "PAYEEID": "ID_NUMBER"}.get(tag)
        if ent:
            yield _span(nt, m.start(2), m.start(2) + len(val), ent, 0.95, "fin:ofx", f"OFX <{tag}> field")
    for m in _QIF_PAYEE.finditer(t):
        v = m.group(1).strip()
        if _party_ok(v) and not _ORG_HINT.search(v) and re.fullmatch(r"[A-Za-z'’. -]{3,40}", v):
            # payees are often shops; a person-shaped payee is shown for review, not pre-selected
            yield _span(nt, m.start(1), m.start(1) + len(v), "PERSON", 0.45, "fin:qif_payee", "payee in a QIF register")
    for m in _MT940_ACCOUNT.finditer(t):
        yield _span(nt, *m.span(1), "BANK_ACCOUNT", 0.95, "fin:mt940", "account in a SWIFT MT940 statement")
    yield from _round2(nt)
    yield from find_account_lines(nt)
    for m in _CREDIT_SCORE.finditer(t):
        yield _span(nt, *m.span(1), "FINANCIAL_INFO", 0.85, "fin:credit_score", "credit score")
    for m in _STATUS.finditer(t):
        yield _span(nt, *m.span(), "FINANCIAL_INFO", 0.8, "fin:financial_status", "income / net worth statement")
    for rx, src in ((_ORDER_OF, "fin:check_payee"), (_ENDORSE, "fin:endorsement")):
        for m in rx.finditer(t):
            v = m.group(1)
            if not _ORG_HINT.search(v) and _party_ok(v):
                yield _span(nt, *m.span(1), "PERSON", 0.86, src, "payee / endorser of a check")


def _aba_ok(n: str) -> bool:
    if len(n) != 9 or not n.isdigit():
        return False
    d = [int(c) for c in n]
    return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10 == 0


def is_company_name_field(text: str, start: int) -> bool:
    """ "ORIG CO NAME:ACME LOGISTICS" — the value of an ACH company-name field is a business, not a person."""
    return bool(_ACH_CO_NAME.search(text[max(0, start - 22):start]))


def _round2(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for m in _X_DASH.finditer(t):
        g = 1 if m.group(1) else 2
        yield _span(nt, *m.span(g), "BANK_ACCOUNT", 0.86, "fin:masked_number", "last digits of an account")
    for m in _DOTS.finditer(t):
        if sum(c.isdigit() for c in m.group(1)) >= 2:
            yield _span(nt, *m.span(1), "BANK_ACCOUNT", 0.85, "fin:masked_number", "last digits of an account")
    for m in _CARD_TXN.finditer(t):
        yield _span(nt, *m.span(1), "CREDIT_CARD", 0.85, "fin:card_last4", "last digits of a card")
    for m in _ENDING_ANY.finditer(t):
        if not _NOT_ACCT_ENDING.search(t[max(0, m.start() - 25):m.start()]) and not re.match(r"(?:19|20)\d\d$", m.group(1)):
            yield _span(nt, *m.span(1), "BANK_ACCOUNT", 0.82, "fin:masked_number", "last digits of an account")
    for m in _MASK_GROUPS.finditer(t):
        v = m.group(1)
        digits, masks = sum(c.isdigit() for c in v), sum(c in "Xx*•" for c in v)
        if digits >= 4 and masks >= 2 and len(v.replace(" ", "").replace("-", "")) >= 8 and not re.search(r"[A-WYZa-wyz]", v):
            ent = "CREDIT_CARD" if len(re.sub(r"[ -]", "", v)) in (15, 16) and v[0] in "3456" else "BANK_ACCOUNT"
            yield _span(nt, *m.span(1), ent, 0.86, "fin:masked_number", "masked account / card number")
    for rx in (_MICR_ANY,):
        for m in rx.finditer(t):
            if _aba_ok(m.group(1)):
                yield _span(nt, *m.span(1), "ROUTING_NUMBER", 0.96, "fin:micr", "routing number on a check's MICR line")
                acct = m.group(2).rstrip(" -")
                yield _span(nt, m.start(2), m.start(2) + len(acct), "BANK_ACCOUNT", 0.94, "fin:micr",
                            "account number on a check's MICR line")
    for rx, why in ((_BOFD, "routing number in a deposit stamp"), (_RT, "routing number")):
        for m in rx.finditer(t):
            if _aba_ok(m.group(1)):
                yield _span(nt, *m.span(1), "ROUTING_NUMBER", 0.93, "fin:routing", why)
    for m in _CASHTAG.finditer(t):
        if not re.fullmatch(r"\$(?:USD|CAD|EUR|GBP|AUD|MXN|USDC|USDT|BTC|ETH|SOL)", m.group(1), re.I):
            yield _span(nt, *m.span(1), "USERNAME", 0.9, "fin:cashtag", "Cash App $cashtag")
    for m in _SIGN_IN_AS.finditer(t):
        yield _span(nt, *m.span(1), "USERNAME", 0.86, "fin:handle", "user name / handle")
    for m in _QUOTED_HANDLE.finditer(t):
        g = 1 if m.group(1) else 2
        v = m.group(g)
        if re.search(r"[\d._]", v) or v.islower():
            yield _span(nt, *m.span(g), "USERNAME", 0.86, "fin:handle", "user name / handle")
    for m in _ENS.finditer(t):
        yield _span(nt, *m.span(1), "USERNAME", 0.88, "fin:ens", "crypto (ENS) name")
    for rx in (_IP_PIN, _CODE_SAID, _SPELLED_CODE, _SPACED_PIN, _PASSPHRASE):
        for m in rx.finditer(t):
            yield _span(nt, *m.span(1), "PASSWORD", 0.88, "fin:secret", "PIN / code / password")
    for m in _PASSWORD_SAID.finditer(t):
        g = 1 if m.group(1) else 2
        yield _span(nt, *m.span(g), "PASSWORD", 0.88, "fin:secret", "password")
    for m in _COURT_NO.finditer(t):
        v = m.group(1).rstrip(" -")
        if sum(c.isdigit() for c in v) >= 4:
            yield _span(nt, m.start(1), m.start(1) + len(v), "CASE_NUMBER", 0.88, "fin:court_case", "court case number")
    for m in _IND_NAME.finditer(t):
        v = m.group(1).rstrip(" ,.")
        if _party_ok(v) and not _ORG_HINT.search(v):
            yield _span(nt, m.start(1), m.start(1) + len(v), "PERSON", 0.88, "kv:fin_ach_name", "individual name in an ACH entry")
    for m in _WIRE_PARTY.finditer(t):
        v = m.group(1).rstrip()
        if _party_ok(v) and not _ORG_HINT.search(v):
            yield _span(nt, m.start(1), m.start(1) + len(v), "PERSON", 0.85, "kv:fin_wire_party", "wire beneficiary / originator")
    for m in _STUDENT.finditer(t):
        yield _span(nt, *m.span(1), "PERSON", 0.85, "kv:fin_student", "student named on a payment")
    for m in _IN_RE.finditer(t):
        for g in (1, 2):
            if m.group(g):
                yield _span(nt, *m.span(g), "PERSON", 0.92, "kv:fin_caption", "party named in a case caption")
    for m in _MINOR_INITIALS.finditer(t):
        g = 1 if m.group(1) else 2
        yield _span(nt, *m.span(g), "MINOR", 0.85, "rule:initials", "a minor referred to by initials")
    for m in _FOR_CHILD.finditer(t):
        for g in (1, 2):
            if m.group(g) and m.group(g).upper() not in _NOT_PARTY:
                yield _span(nt, *m.span(g), "PERSON", 0.8, "kv:fin_beneficiary", "child named as a beneficiary")
    for m in _EMPLOYER_NO_COLON.finditer(t):
        yield _span(nt, *m.span(1), "EMPLOYER", 0.82, "fin:employer", "employer")
    for m in _GROUP_EMPLOYER.finditer(t):
        v = m.group(1).rstrip()
        if not re.match(r"(?i)(?:no|number|#|id)\b", v):
            yield _span(nt, m.start(1), m.start(1) + len(v), "EMPLOYER", 0.8, "fin:employer", "employer group on a health plan")
    for m in _VOE.finditer(t):
        base = m.start(1)
        for piece in re.finditer(r"[^/;,]+", m.group(1)):
            v = piece.group().strip()
            if len(v) >= 3:
                s0 = base + piece.start() + (len(piece.group()) - len(piece.group().lstrip()))
                yield _span(nt, s0, s0 + len(v), "EMPLOYER", 0.85, "fin:employer", "employer being verified")
    for m in _PLAN_SPONSOR.finditer(t):
        v = m.group(1).strip()
        if len(v.split()) >= 2 and not re.match(r"(?:TTEE|FBO|TRUSTEE|ROLLOVER|TRADITIONAL|ROTH|SOLO|SAFE\s+HARBOR)\b", v):
            s0 = m.start(1) + (len(m.group(1)) - len(m.group(1).lstrip()))
            yield _span(nt, s0, s0 + len(v), "EMPLOYER", 0.8, "fin:employer", "employer sponsoring a retirement plan")


def find_account_lines(nt: NormText) -> Iterator[Span]:
    t = nt.text
    pos = 0
    for line in t.split("\n"):
        if _ACCT_LINE.search(line):
            for m in _ACCT_TOKEN.finditer(line):
                v = m.group(1)
                d = sum(c.isdigit() for c in v)
                if d < 7 or re.fullmatch(r"(?:19|20)\d{6}", v) or _aba_ok(v) and len(v) == 9 or \
                        re.fullmatch(r"0\d{3,7}-\d{4,8}", v):
                    continue  # dates written 20261007, routing numbers (found elsewhere)
                if _REF_BEFORE.search(line[max(0, m.start() - 14):m.start()]):
                    continue
                yield _span(nt, pos + m.start(1), pos + m.end(1), "BANK_ACCOUNT", 0.8, "fin:account_line",
                            "account number listed with its institution")
        pos += len(line) + 1
