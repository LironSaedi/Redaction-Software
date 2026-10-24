"""Label-driven detection for forms, tables and records.

Most identifiers in real documents (MRNs, claim numbers, policy numbers, driver's licenses, plates)
have no checksum and no fixed shape — they are only recognisable because a label sits next to them:
``Claim #: 0398-22-1187``. This module finds every label, then assigns each nearby value to the
*nearest* preceding label on the same line (so ``Claim #: A1  Policy #: B2`` is split correctly), and
falls back to a table header on the line above.

It also handles key/value fields whose values are names, addresses and dates (``Patient: DOE, JANE``).
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from . import validators as V
from .base import LO, UP, NormText, Span, _ocr_word, line_bounds

_SEP = r"[\s:#.\-=()/]*"
_NO = r"(?:\s*(?:no\.?|num(?:ber)?\.?|nu(?:rn|m)ber|nbr\.?|#|id\.?|code))?"
_NOR = r"\s*(?:no\.?|num(?:ber)?\.?|nbr\.?|#|id\.?)"  # required number marker for ambiguous words


@dataclass(frozen=True)
class Label:
    entity: str
    rx: re.Pattern
    shape: str = "id"  # which value token shape to accept


def _L(entity: str, pattern: str, shape: str = "id") -> Label:
    return Label(entity, re.compile(r"(?i)(?<![a-z])(?:" + pattern + r")(?![a-z])"), shape)


# Order matters only for documentation; assignment is by proximity, longer labels win ties.
ID_LABELS: list[Label] = [
    _L("SSN", r"ssn|s\.s\.n\.?|ss\s*#|ss\s*no\.?|soc(?:ial)?\.?\s*sec(?:urity)?\.?" + _NO + r"|social\s*(?:#|no\.?)"
       r"|taxpayer\s*id(?:entification)?(?:\s*(?:no\.?|number|#))?",
       "ssn"),
    _L("ITIN", r"itin", "ssn"),
    _L("EIN", r"f?ein|tax\s*(?:id|identification)" + _NO + r"|federal\s*(?:tax\s*)?id" + _NO +
       r"|employer\s*identification(?:\s*number)?|tin", "ein"),
    _L("MRN", r"mrn|m\.r\.n\.?|med(?:ical)?\.?\s*rec(?:ord)?s?\.?" + _NO +
       r"|patient\s*(?:id|#|no\.?|number|acct\.?|account)" + _NO + r"|chart" + _NO +
       r"|encounter" + _NOR + r"|enc\.?\s*(?:#|no\.?)|mr\s*#|mr\s*no\.?|e?pcr\s*(?:#|no\.?)?|"
       r"visit\s*(?:id|#|no\.?|number)|fin(?=\s*[:#])\s*(?:#|no\.?)?|hospital\s*(?:#|no\.?|number)"
       r"|guarantor\s*(?:id|#|no\.?|acct\.?|account)" + _NO + r"|statement\s*(?:id|#|no\.?|number)"
       r"|admission\s*(?:id|#|no\.?|number)|unit\s*(?:no\.?|number)\s*\(mrn\)|medical\s*record\s*(?:#|no\.?|number)"),
    _L("HEALTH_PLAN_ID", r"member\s*(?:ids?|#|no\.?|number)|subscriber\s*(?:id|#|no\.?|number)"
       r"|group\s*(?:id|#|no\.?|number)|group(?=\s*:|\s+[A-Z]{0,4}-?\d{4,})|insurance\s*(?:id|#|no\.?|number)|insured'?s?\s*(?:id|i\.d\.)" + _NO +
       r"|plan\s*(?:id|#|no\.?|number)|medicaid" + _NO + r"|beneficiary\s*(?:id|#|no\.?|number)"
       r"|id\s*card\s*(?:#|no\.?|number)|health\s*(?:plan|insurance)\s*(?:id|#|no\.?|number)|rx\s*grp"
       r"|policyholder\s*id|cert(?:ificate)?\s*(?:#|no\.?|number)|member(?=[ :]+[A-Z]{0,4}\d{5,})"
       r"|grp(?=\s*[:#]?\s*[A-Z0-9-]*\d)|cert\.(?=\s+[A-Z0-9])"),
    _L("MEDICARE_ID", r"medicare" + _NO + r"|mbi|hicn|medicare\s*beneficiary\s*(?:id|identifier)"),
    _L("CLAIM_NUMBER", r"claim\s*ref(?:erence|\.)?(?:\s*(?:no\.?|#))?|claim" + _NO + r"|d?wc\s*(?:#|no\.?|claim)|clm\.?\s*(?:#|no\.?)"
       r"|loss\s*(?:#|no\.?|number)|clm(?=\s+[A-Z0-9]{2,}-?[A-Z0-9-]*\d)"),
    _L("ID_NUMBER", r"our\s*file(?:\s*(?:no\.?|#))?|your\s*file(?:\s*(?:no\.?|#))?|file\s*(?:#|no\.?|number)"
       r"|doc(?:ument)?\s*(?:id|#)|job\s*(?:#|no\.?)|nmls\s*(?:id|#)?|transcription\s*(?:id|#)"
       r"|release\s*(?:id|#|no\.?)|request\s*(?:id|#)|authorization\s*(?:id|#)", "file"),
    _L("ID_NUMBER", r"our\s+(?:reference|ref\.?)\s*(?:no\.?|number|#)?|reference\s*(?:no\.?|number|#)|"
       r"account\s+reference|debtor\s*(?:#|no\.?|number|id)|customer\s*reference|creditor\s+ref\.?|"
       r"(?:escrow|title|closing|settlement)\s+file\s*(?:#|no\.?|number)?|engagement\s*(?:#|no\.?|number)|"
       r"funding\s+agreement\s*(?:#|no\.?|number)?|(?:title|certificate\s+of\s+title)\s+no\.?|quick-?pay\s+code|"
       r"(?:customer\s*)?\(?cif\)?\s*(?:#|no\.?|number)|me(?:m|rn)ber\s*(?:#|no\.?|nu(?:m|rn)ber|id)|"
       r"tri-?merge\s+ref|credit\s+report\s*(?:#|no\.?|ref)|loyalty\s*(?:#|no\.?|number|id)|(?<!-)emp\.?\s*(?=\d{4,})|"
       r"ind(?:ividual)?\s+id|client\s+ledger|plan\s+acct\.?|share\s*(?:#|id)|universal\s+loan\s+identifier|uli\b", "id"),
    _L("POLICY_NUMBER", r"mic\s*(?:#|no\.?)?(?=\s*\d)|pol\.?(?=\s+[A-Z]{1,4}-?\d)|"
       r"(?:service|gap(?:\s+waiver)?|warranty|extended\s+warranty)\s+contract\s*(?:#|no\.?|number)?|"
       r"contract\s*(?:#|no\.?|number)", "id"),
    _L("POLICY_NUMBER", r"policy" + _NO + r"|pol\.?\s*(?:#|no\.?)|policy\s*/\s*group|coverage\s*(?:#|id)"),
    _L("CASE_NUMBER", r"case" + _NO + r"|cause" + _NO + r"|docket" + _NO + r"|index\s*(?:no\.?|number|#)"
       r"|civil\s*action" + _NO + r"|matter\s*(?:#|no\.?|number)|complaint\s*(?:#|no\.?|number)"
       r"|indictment\s*(?:#|no\.?|number)|case\s*:", "case"),
    _L("LAW_ENFORCEMENT_ID", r"badge" + _NO + r"|officer\s*(?:id|#|no\.?|number)|booking" + _NO +
       r"|inmate" + _NO + r"|arrest\s*(?:id|#|no\.?|number)|report\s*(?:id|#|no\.?|number)"
       r"|incident\s*(?:id|#|no\.?|number)|cad" + _NO + r"|oca" + _NO + r"|agency\s*(?:report|case)" + _NO +
       r"|crash\s*report" + _NO + r"|crash\s*(?:id|#|no\.?|number)|accident\s*report" + _NO + r"|citation" + _NO + r"|ticket\s*(?:#|no\.?)"
       r"|so\s*#|s\.o\.\s*#|rd\s*#|(?:link\s*/\s*)?ncic(?:\s*(?:entry|#|no\.?|number))?|offense\s*(?:#|no\.?|number)"
       r"|(?:livescan\s*)?tcn|evidence(?=\s+[A-Z]{0,3}-?\d{2}-\d{4,})|property\s*receipt"
       r"|dps\s*(?:#|no\.?|number)|unit\s*(?:#|id)|warrant" + _NO +
       r"|evidence\s*(?:#|no\.?|item)|property\s*(?:tag|#)|bwc\s*(?:id|#)|employee\s*(?:id|#|no\.?)\s*/\s*badge"),
    # longer forms first in their own entry so "CAD Event:" beats the bare "CAD" alternative above
    _L("LAW_ENFORCEMENT_ID", r"cad\s*event(?:\s*(?:#|no\.?|number))?|event\s*(?:#|no\.?|number)|"
       r"event(?=\s+[A-Z]?\d{4}-\d{3,})|police\s+report|(?:agency|related)\s+(?:[A-Z]{2,5}\s+)?report"),
    _L("DRIVERS_LICENSE", r"driver'?s?\s*licen[cs]e" + _NO + r"|driving\s*licen[cs]e" + _NO +
       r"|dl|d/l|dln|oln|ol\s*#|o\.l\.\s*#|cdl|operator'?s?\s*licen[cs]e" + _NO + r"|licen[cs]e\s*(?:no\.?|number|#)"
       r"|lic\.?\s*(?:no\.?|#)|state\s*id" + _NO + r"|id\s*card\s*(?:no\.?|number)|identification\s*card"
       + _NO + r"|driver\s*lic\.?" + _NO, "dl"),
    # a person's criminal-justice identifiers: state ID, FBI number, corrections numbers
    _L("ID_NUMBER", r"sid\s*(?:#|no\.?)?|fbi\s*(?:#|no\.?|number)|fbi(?=\s*:)|ucn|"
       r"(?:a|t|i|f|c)?doc(?:cs|j)?\s*(?:#|no\.?|number)?(?=\s*\(?#?\s*\d{5,9}\b)|bop\s*(?:#|no\.?|reg(?:ister)?)|"
       r"tdcj\s*(?:#|no\.?)?|cdcr\s*(?:#|no\.?)?"),
    _L("PASSPORT", r"passports?" + _NO, "passport"),
    _L("VIN", r"vin" + _NO + r"|vehicle\s*identification\s*(?:no\.?|number|#)|serial\s*/\s*vin", "vin"),
    _L("LICENSE_PLATE", r"licen[cs]e\s*plate" + _NO + r"|lic\.?\s*plate" + _NO +
       r"|(?<!locking\s)(?<!volar\s)(?<!bone\s)(?<!metal\s)(?<!compression\s)(?<!fixation\s)plate(?:\s*(?:no\.?|#|number)|\s*:)"
       r"|(?<!locking\s)(?<!volar\s)(?<!bone\s)plate(?=\s*\(?\s*[A-Z0-9]{2,4}[- ]?[A-Z0-9]{2,5}\b(?!\s*(?:mL|ml|mg|cc)))"
       r"|tag" + _NO + r"|(?:vehicle\s+)?registration\s*(?:no\.?|#|number|plate)|lp\s*#|lp(?=\s*:)|veh(?:icle)?\s*plate"
       # spoken: "the plate was SFD4417", "plate number is S F D 4 4 1 7"
       r"|(?<!locking\s)(?<!volar\s)(?<!bone\s)plate(?:\s+number)?(?=\s+(?:was|is|reads?|said)\s+[A-Z0-9])", "plate"),
    _L("BANK_ACCOUNT", r"(?:(?:bank|checking|savings|chk|sav|deposit|brokerage|loan|mortgage|escrow|trust|"
       r"iolta|operating|direct\s*deposit)\s*)?(?:account|acct|acc|a/c)\.?" + _NO + r"(?:\s*ending(?:\s*in)?)?"
       r"|loan\s*(?:#|no\.?|number|acct)|loan(?=\s+[A-Z]{0,4}-?\d{6,})|ln(?=\s*#?\s*[A-Z]{0,3}-?\d{6,})|overdraft\s*line"
       r"|clabe|cuenta(?:\s+(?:no\.?|n[uú]mero))?|n[uú]mero\s+de\s+cuenta|bsb\s*/\s*account",
       "account"),
    _L("ROUTING_NUMBER", r"routing" + _NO + r"|aba" + _NO + r"|rtn|r/t|transit" + _NO +
       r"|routing\s*/\s*transit" + _NO, "routing"),
    _L("ROUTING_NUMBER", r"ifsc|sort\s*code|bsb|swift\s*code|bank\s*code", "id"),
    _L("NPI", r"npi" + _NO, "npi"),
    _L("DEA_NUMBER", r"dea" + _NO, "dea"),
    _L("PHONE", r"phone|ph|tel|telephone|cell|cellular|mobile|fax|home\s*phone|work\s*phone|contact\s*(?:no\.?|"
       r"number|#)|pager|day\s*phone|evening\s*phone|alt(?:ernate)?\s*phone", "phone"),
    _L("ZIP_CODE", r"zip|zip\s*code|postal\s*code|zipcode", "zip"),
    _L("PASSWORD", r"password|passwd|pwd|passcode|pin" + _NO + r"|access\s*code|security\s*answer", "secret"),
    _L("USERNAME", r"user\s*name|username|user\s*id|login(?:\s*id)?|screen\s*name|handle|gamertag|"
       r"user(?=\s+[a-z][a-z0-9.]*[_\d.][a-z0-9._-]*)|"
       r"instagram|snapchat|twitter|tiktok|facebook|venmo|cash\s*app|telegram|discord|signal\s*id", "username"),
    _L("DEVICE_ID", r"imei|meid|esn|serial" + _NO + r"|s/n|device\s*id|udid|iccid|mac\s*address|axon|bwc|"
       r"body[- ]?(?:worn\s*)?cam(?:era)?|dash\s*cam|device\s*(?:#|serial|no\.?)|ignition\s+interlock\s+device", "id"),
    _L("NATIONAL_ID", r"sin|social\s*insurance" + _NO + r"|nino|national\s*insurance" + _NO +
       r"|national\s*id(?:entity)?" + _NO + r"|curp|aadhaar|nhs" + _NO + r"|dpi|cui|dni|ine|rfc|c[eé]dula|nin\b|"
       r"tribal\s*(?:enrollment|membership|member|id)\s*(?:#|no\.?|number|card)?|census\s*(?:#|no\.?|number)" + r"|alien\s*(?:#|no\.?|number|reg)"
       r"|a-?number|a\s*#|uscis" + _NO + r"|green\s*card" + _NO + r"|permanent\s+resident\s+card(?:\s*\([^)]{0,10}\))?"
       + _NO + r"|i-551" + _NO + r"|form\s+i-551" + _NO + r"|aadhaar(?:\s*(?:number|no\.?))?|pan(?=\s*[:(]|\s+[A-Z]{5}\d)"
       # found missing by the Presidio cross-check: Singapore NRIC/FIN, Australian TFN, Polish PESEL, Dutch BSN,
       # Italian codice fiscale, Spanish NIF/NIE, French NIR, German Steuer-ID
       r"|nric|fin(?=\s*[:#]?\s*[STFGM]\d{7}[A-Z]\b)|tfn|tax\s*file" + _NO + r"|pesel|bsn|burgerservicenummer|codice\s*fiscale|nif|nie|nir\b"
       r"|steuer-?id(?:entifikationsnummer)?|personnummer|cpr\s*(?:no\.?|number|nummer|#)", "id"),  # not CPR the procedure
    _L("ID_NUMBER", r"employee" + _NOR + r"|student" + _NOR + r"|fleid|ssid|state\s*student\s*id|oba\b|sbn" + r"|customer" + _NOR + r"|client" + _NOR +
       r"|member" + _NOR + r"|account\s*holder\s*id|personnel" + _NOR + r"|payroll" + _NOR + r"|id" + r"(?:\s*no\.?|#)?"
       r"|identification" + _NOR + r"|i\.d\.|(?:state\s*)?bar\s*(?:no\.?|number|#|card|id)|bar\s*roll\s*(?:no\.?|#)"
       r"|(?:csr|ccr|rpr|reporter)\s*(?:no\.?|#|number|license)|(?:pt|dpt|rn|lpn|md|do|np|pa|dc|lcsw|lpc|lmft|cna|emt|"
       r"otr|ot|slp|lmt|psyd|aprn|crna|pharmd|rph)\s*,?\s*"
       r"(?:licen[cs]e|lic\.?)\s*(?:no\.?|#|number)?|professional\s*licen[cs]e" + _NO +
       r"|(?:medical|nursing|pharmacy|board)\s*licen[cs]e" + _NO + r"|certified\s+shorthand\s+reporter\s*(?:no\.?|#)"
       r"|notary\s*(?:id|#|no\.?|commission)" + _NO + r"|commission\s*(?:#|no\.?)|sbn|tbn|bar\s*#|ptin|tcole\s*(?:pid|#)?|"
       r"pid(?=\s*[:#]?\s*\d)|(?:[A-Z]{2}\s+)?lic(?:ense)?\.?\s*(?:#|no\.?)?(?=\s*[A-Z]{0,3}\s?\d{3,})|"
       r"(?:rn|lvn|lpn|lcdc|lcsw|lpc|lmft|np|pa|md|do|dc|pt|ot|emt|chw|cna|rph|pharmd|rdh|chi|cmi)\s*#|"
       r"(?:tx\s+)?cert\.?\s*#|certificate\s*(?:#|no\.?)|nmls\s*(?:#|id)?|cdl\s*#", "id"),
    _L("CVV", r"cvv2?|cvc2?|security\s*code|card\s*code", "cvv"),
]

# Token shapes for the values that follow a label.
_TOK = {
    "id": re.compile(r"(?<![\w-])(?:(?!(?:BIN|PCN|GRP|ID|NO|DOB|SSN|MRN|DL|NPI|DEA|EIN|TIN)\b)[A-Z]{1,4}[ ](?=[A-Z0-9-]*\d))?(?=[A-Za-z0-9-]*\d)[A-Za-z0-9]"
                     r"(?:[A-Za-z0-9]|[-/.](?=[A-Za-z0-9])|[ ](?=[A-Z0-9-]*\d[A-Z0-9-]*(?:[ ,;.)]|$))){2,30}(?![\w])"),
    "ssn": re.compile(r"(?<![\w-])\d{3}[- .]?\d{2}[- .]?\d{4}(?![\w-])|(?<![\w-])[xX*]{3}[- ]?[xX*]{2}[- ]?\d{4}"),
    "ein": re.compile(r"(?<![\w-])\d{2}[- ]?\d{7}(?![\w-])"),
    "case": re.compile(r"(?<![\w-])(?=[A-Za-z0-9:.\-/ ]*\d)[A-Za-z0-9](?:[A-Za-z0-9]|[-:/.](?=[A-Za-z0-9])|"
                       r" (?=[A-Z0-9]{1,6}\b(?![ ]+[a-z])))"r"{2,40}(?![\w])"),
    # an optional issuing-state prefix: "DL: TX 40921187"
    "dl": re.compile(r"(?<![\w'’-])(?:[A-Z]{2}[ ]{1,2}(?=[A-Z]?\d))?(?=[A-Za-z0-9-]*\d{3})[A-Za-z0-9]"
                     r"(?:[A-Za-z0-9]|-(?=[A-Za-z0-9])|[ ](?=\d)){3,22}(?![\w])"),
    "vin": re.compile(r"(?<![\w-])(?=[A-HJ-NPR-Z0-9]*\d)[A-HJ-NPR-Z0-9]{11,17}(?![\w-])"),
    "passport": re.compile(r"(?<![\w'’-])(?=[A-Za-z0-9]*\d{4})[A-Za-z0-9]{6,12}(?![\w-])"),
    "plate": re.compile(r"(?<![\w-])(?:[A-Z0-9][ -]){3,8}[A-Z0-9](?![\w-])|"  # spoken "S F D 4 4 1 7"
                        r"(?<![\w-])(?:(?:[A-Z]{2})[\s:-]+)?(?=[A-Z0-9 -]*[A-Z0-9])[A-Z0-9]{1,4}[- ·]?[A-Z0-9]{1,5}"
                        r"(?:[- ·]\d{1,4})?(?![\w-])"),
    "account": re.compile(r"(?<![\w-])(?:[xX*•#]{2,}[- ]?)?\d(?:[\d]|[- ](?=\d)){3,22}(?![\w-])"
                          r"|(?<![\w-])[xX*•#]{2,}[- ]?\d{3,4}(?![\w-])|(?<![\w-])[A-Z]{1,4}-?\d{4,}(?:-\d+)*(?![\w-])"
                          r"|(?<![\w-])[A-Z]{1,4}(?:-\d{2,}){2,}(?![\w-])"
                          r"|(?<![\w-])\d[A-Z]{1,3}-?\d{4,10}(?![\w-])"  # brokerage style "5WB-12345"
                          r"|(?<![\w-])(?=[A-Z0-9-]*\d{3})[A-Z0-9]{1,6}(?:-[A-Z0-9]{1,10}){1,4}(?![\w-])"),
    "routing": re.compile(r"(?<![\w-])\d{4}[- ]?\d{4}[- ]?\d(?![\w-])"),
    "npi": re.compile(r"(?<![\w-])\d{10}(?![\w-])"),
    "dea": re.compile(r"(?<![\w-])[A-Za-z]{2}\d{7}(?![\w-])"),
    "phone": re.compile(r"(?<![\w-])\+?[\d(][\d\s().-]{5,18}\d(?:\s*(?:x|ext\.?)\s*\d{1,6})?(?![\w-])"),
    "zip": re.compile(r"(?<![\w-])\d{5}(?:-\d{4})?(?![\w-])"),
    "secret": re.compile(r"(?<![\w])[^\s,;]{3,64}"),
    "username": re.compile(r"(?<![\w@])@?[A-Za-z0-9_][A-Za-z0-9_.-]{1,38}[A-Za-z0-9_]"),
    "cvv": re.compile(r"(?<![\w-])\d{3,4}(?![\w-])"),
    "file": re.compile(r"(?<![\w-])(?=[A-Za-z0-9-]*\d)[A-Za-z0-9](?:[A-Za-z0-9]|[-/.](?=[A-Za-z0-9])|[ ](?=\d)){3,30}(?![\w])"),
}

_DATEISH = re.compile(r"^(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}[/.-]\d{1,2}[/.-]\d{1,2})$")
_MONEY = re.compile(r"^\$|^\d{1,3}(?:,\d{3})+(?:\.\d{2})?$|^\d+\.\d{2}$")
_PLACEHOLDER = re.compile(r"(?i)^(?:n/?a|none|unknown|unk|na|tbd|pending|same|self|see\s+above|see\s+attached|"
                          r"redacted|withheld|_+|-+|x+|\?+|nil|null|0+)$")
_STOPWORDS_AFTER = re.compile(r"(?i)^(?:is|was|of|the|and|or|for|to|on|at|in|by|if|known|number|no|date|type|"
                              r"name|status|holder|limit|limits|period|effective|expiration|amount|issued|state|"
                              r"class|provided|listed|below|above|attached|required|information|info)$")


def _value_ok(shape: str, entity: str, val: str) -> tuple[bool, float]:
    """Return (accept, score_adjustment)."""
    v = val.strip()
    if not v or _PLACEHOLDER.match(v) or _MONEY.match(v):
        return False, 0
    if _STOPWORDS_AFTER.match(v):
        return False, 0
    d = V.digits(v)
    if shape not in ("secret", "username", "plate", "dl", "passport") and _DATEISH.match(v):
        return False, 0
    if shape == "ssn":
        return len(d) == 9 or v[:3].lower() in ("xxx", "***"), 0.05 if V.ssn_ok(v) else 0
    if shape == "routing":
        return len(d) == 9, 0.05 if V.aba_routing_ok(v) else -0.2
    if shape == "npi":
        return True, 0.05 if V.npi_ok(v) else -0.25
    if shape == "dea":
        return True, 0.05 if V.dea_ok(v) else -0.2
    if shape == "phone":
        return 7 <= len(d) <= 15, 0
    if shape == "plate":
        core = re.sub(r"^(?:[A-Z]{2})[\s:-]+", "", v)
        an = V.alnum(core)
        if not 2 <= len(an) <= 8:
            return False, 0
        if an.isalpha() and len(an) < 4:
            return False, 0
        if an.isdigit() and len(an) < 3:
            return False, 0
        return True, 0 if any(c.isdigit() for c in an) else -0.15
    if shape == "vin":
        return 11 <= len(v) <= 17 and len(d) >= 3, 0
    if shape == "dl":
        return 5 <= len(V.alnum(v)) <= 20 and len(d) >= 3, 0
    if shape == "passport":
        return 6 <= len(v) <= 12, 0
    if re.fullmatch(r"(\d{4,8})-(\d{4,8})", v) and len(v.split("-")[0]) == len(v.split("-")[1]) and \
            int(v.split("-")[0]) <= int(v.split("-")[1]) and v.startswith("0"):
        return False, 0  # a Bates range ("000232-000410")
    if shape == "account":
        if re.fullmatch(r"(?:19|20)\d\d|\d{3,4}-[A-Z]{1,5}|\d{1,2}-(?:19|20)\d\d|[A-Z]-\d{1,2}", v):
            return False, 0  # a year or a form number ("1099-NEC", "Rev. 1-2024", "W-2")
        return 4 <= len(d) <= 20 or (len(d) >= 3 and v[:1] in "xX*•#"), 0
    if shape == "secret":
        return len(v) >= 3 and v.lower() not in ("required", "protected", "below", "reset", "here"), 0
    if shape == "username":
        return len(v) >= 3 and not v.lower() in ("is", "was", "and", "unsaved", "sms", "mms", "imessage", "none",
                                                 "unknown", "n/a", "deleted", "private"), 0
    if shape in ("id", "case") and any(_ocr_word(w) and re.search(r"[a-z]{2}", w) and set(re.sub(r"\D", "", w)) <= set("01")
                                       for w in v.split()):
        return False, 0  # "Rep0rt N0" — OCR'd words, not an identifier
    if shape == "id":
        if re.fullmatch(r"FL\d{1,2}[A-Z]?", v):
            return False, 0  # UB-04 form locator ("FL54"), not a value
        if len(d) < 2 and entity != "DEVICE_ID":
            return False, 0
        if len(V.alnum(v)) < 4:
            return False, 0
        return True, 0
    return True, 0


@dataclass
class _LabelHit:
    label: Label
    start: int
    end: int
    alt: Label | None = None  # "SSN / DL#": the second label of a joined pair, tried when the first fails


def _find_label_hits(text: str) -> list[_LabelHit]:
    hits: list[_LabelHit] = []
    for lab in ID_LABELS:
        for m in lab.rx.finditer(text):
            hits.append(_LabelHit(lab, m.start(), m.end()))
    # drop labels fully contained in a longer label ("plate" inside "license plate")
    hits.sort(key=lambda h: (h.start, -(h.end - h.start)))
    kept: list[_LabelHit] = []
    for h in hits:
        if any(k.start <= h.start and h.end <= k.end and (k.end - k.start) >= (h.end - h.start) for k in kept):
            continue  # contained in (or identical to) a more specific label already kept
        # "DL/ID #:" — two labels joined by a slash are one label (the first one names the entity)
        if kept and 0 <= h.start - kept[-1].end <= 2 and re.fullmatch(r"\s*[/&]\s*|\s*/", text[kept[-1].end:h.start] or "/"):
            if text[kept[-1].end:h.start].strip() in ("/", "&"):
                alt = h.label if h.label.entity != kept[-1].label.entity else None
                kept[-1] = _LabelHit(kept[-1].label, kept[-1].start, h.end, alt)
                continue
        # a "label" that directly follows another label and runs into an ID ("Claim #: CLM-2023-…") is
        # the start of the value, not a new label
        if kept and h.start - kept[-1].end <= 4 and re.fullmatch(r"[\s:#.=]*", text[kept[-1].end:h.start]) \
                and re.match(r"[-\d]", text[h.end:h.end + 1]):
            continue
        kept.append(h)
    return kept


_GAP_OK = re.compile(r"^[\s:#.\-=()/]*(?:\([A-Za-z0-9 ./-]{1,20}\)[\s:#.\-=/]*)?"
                     r"(?:(?:at|with|from|for)\s+(?:the\s+)?[A-Z][\w'&.-]+(?:\s+[A-Z][\w'&.-]+){0,3}\s+(?=is\b|was\b))?"
                     r"(?:(?:is|was|of|no|number|num|nbr|id|if\s+known|if\s+any|on\s+file|ending(?:\s+in)?|"
                     r"(?:is|was)\s+(?:on\s+(?:the|my)\s+card|listed\s+as|on\s+file\s+as))\b"
                     r"[\s:#.,\-=()/]*){0,3}$", re.I)


_PLATFORMS = (r"facebook|fb|instagram|ig|insta|snapchat|snap|tiktok|twitter|x|threads|discord|telegram|whatsapp|venmo|"
              r"cash\s*app|paypal|zelle|reddit|linkedin|youtube|twitch|kik|signal|messenger|gmail|yahoo|outlook|icloud")


_NAME_COL_HDR = re.compile(r"(?i)(?<![a-z])(?:(?:your\s+|spouse['’]s\s+)?first\s+name(?:\s+and\s+(?:middle\s+)?initial)?|"
                           r"last\s+name|given\s+name|surname|family\s+name)(?![a-z])")
_COL_NAME_VAL = re.compile(rf"[{UP}][{UP}{LO}'’-]+(?:[ ][{UP}][{UP}{LO}'’-]*\.?)?(?![\w])")


def find_column_names(nt: NormText) -> Iterator[Span]:
    """Forms with name columns (Form 1040: "First name and middle initial   Last name"; dependants tables):
    the values sit under the header on the following lines, aligned to the header's column."""
    text = nt.text
    lines = _lines(text)
    for li, (ls, le) in enumerate(lines):
        hdr = text[ls:le]
        cols = []
        for m in _NAME_COL_HDR.finditer(hdr):
            # the header cell may begin before the words "first name" ("If joint return, spouse's first name")
            cell = hdr.rfind("  ", 0, m.start())
            cols.append((0 if cell < 0 else cell + 2, m.start()))
        if not cols:
            continue
        taken = False
        prose = 0
        for lj in range(li + 1, min(li + 7, len(lines))):
            vs, ve = lines[lj]
            row = text[vs:ve]
            if not row.strip():
                if taken:
                    break
                continue
            if re.search(r"(?<![\w'’])[a-z]{2,}(?![\w'’])", row) or _NAME_COL_HDR.search(row):
                if taken:
                    break  # the next header / prose line ends this block of values
                prose += 1
                if prose >= 2:
                    break  # values sit right under their header, not past the form's next paragraphs
                continue
            for cell, c in cols:
                # value starts within the header cell's left part
                m = _COL_NAME_VAL.search(row, max(0, cell - 3))
                if not m or m.start() > c + 5 or (m.start() > 0 and row[m.start() - 1] not in " \t"):
                    continue
                v = m.group()
                if v.lower() in ("none", "n/a", "self", "son", "daughter", "spouse", "child", "yes", "no") or \
                        _ORG_WORDS.search(v) or re.search(r"\d", v):
                    continue
                from .names import HARD_STOP
                if any(w.lower().strip(".") in HARD_STOP for w in v.split()):
                    continue  # "Official Form 106A/B" — a form title, not a name
                taken = True
                yield _mk(nt, vs + m.start(), vs + m.end(), "PERSON", 0.82, "kv:name_column",
                          "value in a first-name / last-name column")


_POLICE_DOC = re.compile(r"(?i)\bpolice\b|\bsheriff|\bP\.?D\.?\b|\bofc\.|\btrooper\b|statement\s+taken\s+by|"
                         r"\bincident\s+report|\barrest(?:ing)?\b")


def _shape_sig(v: str) -> str:
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", v))


def find_labelled_ids(nt: NormText) -> Iterator[Span]:
    text = nt.text
    hits = _find_label_hits(text)
    by_line: dict[int, list[_LabelHit]] = {}
    for h in hits:
        # a label that wraps ("member\n    IDs") belongs to the line it ends on, where its value is
        by_line.setdefault(line_bounds(text, max(h.start, h.end - 1))[0], []).append(h)

    emitted: set[tuple[int, int]] = set()
    for line_start, line_hits in by_line.items():
        _, line_end = line_bounds(text, line_start)
        line_hits.sort(key=lambda h: h.start)
        for i, h in enumerate(line_hits):
            seg_end = line_hits[i + 1].start if i + 1 < len(line_hits) else line_end
            seg_base = h.end
            seg = text[h.end:seg_end]
            if (not seg.strip(" \t:#.,") or _GAP_OK.fullmatch(seg)) and i + 1 == len(line_hits) and line_end + 1 < len(text):
                # label ends its line, value starts the next one ("group\n228174;")
                nxt_e = line_bounds(text, line_end + 1)[1]
                nxt_hits = [x.start for x in by_line.get(line_end + 1, [])]
                seg_base = h.end
                seg = text[h.end:min([nxt_e] + nxt_hits)]
                if not re.match(r"[^\n]*\n[ \t]{0,12}\S", seg):
                    continue
            found = None
            for lab in (h.label, h.alt):
                if lab is None:
                    continue
                m = _TOK[lab.shape].search(seg)
                if not m:
                    continue
                gap = seg[:m.start()]
                if len(gap) > 30 or not _GAP_OK.match(gap):
                    continue
                val = m.group().rstrip(" .-/")
                ok, adj = _value_ok(lab.shape, lab.entity, val)
                if ok:
                    found = lab
                    break
            if found is None:
                continue
            if found is not h.label:
                h = _LabelHit(found, h.start, h.end)
            lab_txt = text[h.start:h.end].lower()
            pre = text[max(0, h.start - 8):h.start].lower()
            if h.label.entity == "PASSWORD" and (re.search(r"with\s*$", pre) or _DATEISH.match(val) or
                                                 re.fullmatch(r"\d{1,2}/\d{1,2}", val)):
                continue
            if h.label.entity in ("PASSWORD", "USERNAME") and re.match(r"[.!?](?![.!?])\s", gap):
                continue  # "… your online banking password.\n  Credit reporting", "… user ID. Your old user ID was"
            if h.label.entity == "BANK_ACCOUNT" and re.search(r"(?i)(?:\bgl|\bg/l|general\s+ledger|ledger)\s*$",
                                                               text[max(0, h.start - 16):h.start]):
                continue  # a general-ledger account code, not a bank account
            # "login from …", "PIN number field": a plain lower-case word is only a value after ":" / "is"
            word = val.rstrip(":;,")
            if _ocr_word(word):  # "password wi11 be sent", "PIN f0r ATM card": OCR'd words
                word = word.lower().replace("0", "o").replace("1", "l").replace("|", "l")
            if h.label.entity in ("PASSWORD", "USERNAME") and word.isalpha() and word.islower() and \
                    not re.search(r"[:=]|\bis\b|\bwas\b", gap):
                continue
            if h.label.entity == "USERNAME" and re.match(r"(?:instagram|snapchat|twitter|tiktok|facebook|venmo|cash\s*app|"
                                                         r"telegram|discord)", lab_txt) and ":" not in gap and \
                    not val.startswith("@") and not re.search(r"\b(?:is|handle|username|name)\b", gap, re.I):
                continue
            if h.label.entity == "ID_NUMBER" and re.search(r"(?:ppd|ccd|web|tel|co|orig|company|trace|ind|txn|"
                                                           r"transaction|ref|confirmation)\s*$", pre):
                continue
            wide = text[max(0, h.start - 30):h.start].lower()
            if h.label.entity in ("ID_NUMBER", "DRIVERS_LICENSE") and (
                    re.search(r"(?:nmlsr?|charter|registration|atm|terminal|merchant|store|batch|branch|fdic|naic|ncua|"
                              r"regulator|agency|licen[cs]e|lic\.|payer|payor|location)\s*(?:id|#|no\.?)?\s*$", wide) or
                    # "RIDGELINE AUTO FINANCE, LLC is licensed by the … Commissioner, license no. 1300447-18"
                    re.search(r"(?i)\blicensed\s+(?:by|with)\b[^.\n]*$", text[max(0, h.start - 160):h.start]) or
                    re.match(r"(?:licen[cs]e|lic\.?)", lab_txt) and re.search(
                        r"(?:\b[a-z]{2}|state|escrow|broker|lender|company|agency|organization|business|firm|"
                        r"originator|mlo)\s*$", wide)):
                continue  # a business / professional licence or a terminal, not a personal identifier
            s = seg_base + m.start()
            e = s + len(val)
            emitted.add((s, e))
            score = 0.92 + adj
            if h.label.entity == "ID_NUMBER" and re.fullmatch(r"emp\.?\s*", lab_txt) and re.fullmatch(r"\d{4}", val):
                score = 0.45  # "Emp 1033": a payroll register's four-digit sequence number, offered for review
            if h.label.shape == "file":
                score = 0.45  # a firm's / insurer's own file number: shown to the reviewer, not auto-redacted
                ls_, le_ = text.rfind("\n", 0, h.start) + 1, text.find("\n", e)
                if re.search(r"(?i)\b(?:claim|claimant|insurer|carrier|adjuster|workers'?\s*comp|wc|dli|l\s*&\s*i|wid)\b",
                             text[ls_:le_ if le_ >= 0 else len(text)]):
                    score = 0.8  # "DLI WID / File No.: 2026-118473   Insurer Claim No.: …" — the claimant's file
            if h.label.entity == "LICENSE_PLATE" and re.search(r"(?i)registration", lab_txt) and not re.search(
                    r"(?i)vehicle|car|truck|auto|motor|dmv|plate|vin|tag", text[max(0, h.start - 80):e + 40]):
                continue
            why = f"value of label “{text[h.start:h.end].strip()}”"
            ent = h.label.entity
            if ent == "CASE_NUMBER" and _POLICE_DOC.search(text[:2500]) and not re.search(
                    r"(?i)\b(?:da|court|cause|docket|civil|district|county\s+court)\s*(?:case)?\s*[:#]?\s*$", pre + lab_txt):
                ent = "LAW_ENFORCEMENT_ID"  # "Case #" on a police form is the agency's case number
            if ent == "EIN" and re.match(r"(?i)fein", lab_txt):
                continue  # the EIN pattern reports employer FEINs (one detection, not two)
            yield _mk(nt, s, e, ent, score, f"label:{ent.lower()}", why)
            # more values for the same label: "IDs X and Y", "passports (No. X -- Aanya; No. Y -- Rohan)"
            tok = _TOK[h.label.shape]
            rest_at = e - seg_base
            plural = bool(re.search(r"(?i)(?:s|nos\.?)\W*$", lab_txt.strip(" :#.")))
            sig = _shape_sig(val)
            for _ in range(6):
                cm = re.match(r"(?:\s*(?:,|and|&|/|;|or)\s*)+", seg[rest_at:])
                nm = tok.match(seg, rest_at + cm.end()) if cm else None
                if not nm and plural:
                    nm = next((x for x in tok.finditer(seg, rest_at) if _shape_sig(x.group().rstrip(" .-/")) == sig),
                              None)
                if not nm:
                    break
                v2 = nm.group().rstrip(" .-/")
                if not _value_ok(h.label.shape, h.label.entity, v2)[0] or _shape_sig(v2) != sig and not cm:
                    break
                if (v2.isalpha() and v2.islower()) or (h.label.shape in ("username", "secret") and
                                                       not re.search(r"[@_.\d]", v2)):
                    break  # "(@mariaruiz_atx, inactive)" — a note, not a second handle
                s2 = seg_base + nm.start()
                emitted.add((s2, s2 + len(v2)))
                yield _mk(nt, s2, s2 + len(v2), h.label.entity, score, f"label:{h.label.entity.lower()}", why)
                rest_at = nm.start() + len(v2)

    # question/answer carry-over (depositions, interrogatories): "Q. What is your driver's license number?"
    # followed by "A. It's B96645068."
    for line_start, line_hits in by_line.items():
        _, line_end = line_bounds(text, line_start)
        line = text[line_start:line_end]
        if not (re.match(r"\s*(?:\d{1,2}\s+)?(?:Q[.:]|QUESTION|INTERROGATORY|REQUEST)", line, re.I) or
                (re.match(r"\s*(?:\d{1,2}:\d{2}\s+)?[A-Z]{1,4}:\s", line) and "?" in line)):
            continue
        nxt_s = line_end + 1
        if nxt_s >= len(text):
            continue
        _, nxt_e = line_bounds(text, nxt_s)
        ans = text[nxt_s:nxt_e]
        am = re.match(r"\s*(?:\d{1,2}\s+)?(?:A[.:]|ANSWER:?|RESPONSE:?)\s*", ans, re.I) or \
            re.match(r"\s*(?:\d{1,2}:\d{2}\s+)?[A-Z]{1,4}:\s*", ans)
        if not am:
            continue
        for h in line_hits:
            tm = _TOK[h.label.shape].search(ans, am.end())
            if not tm:
                continue
            val = tm.group().rstrip(" .-/")
            ok, adj = _value_ok(h.label.shape, h.label.entity, val)
            if not ok or (h.label.shape == "secret"):
                continue
            if h.label.shape == "username" and re.fullmatch(_PLATFORMS, val, re.I):
                continue  # "Q. Do you have a Facebook or Instagram? A. Facebook." — the platform, not the handle
            s = nxt_s + tm.start()
            e = s + len(val)
            if (s, e) in emitted:
                continue
            emitted.add((s, e))
            yield _mk(nt, s, e, h.label.entity, 0.86 + adj, f"qa:{h.label.entity.lower()}",
                      f"answer to a question asking for “{text[h.start:h.end].strip()}”")

    # "Q. Who was your supervisor? / A. Donna Smith." — name answers to who/name questions
    _who = (r"\b(?:who\s+(?:is|was|are|were)|whom|what\s*(?:is|'s)\s+(?:his|her|their|your|the)\s+(?:full\s+|first\s+|"
            r"last\s+)?name|full\s+name|name\s+of|names?\b)")
    _gap = r"\n(?:[ \t]*\f?[ \t]*(?:Page\s+\d+)?[ \t]*\n)*[ \t]*(?:\d{1,2}[ \t]+|\d{1,2}:\d{2}[ \t]+)?"
    qa_rx = re.compile(r"(?im)^[ \t]*(?:\d{1,2}[ \t]+)?Q[.:][^\n]*" + _who + r"[^\n]*" + _gap + r"A[.:][ \t]*"
                       r"|^[ \t]*(?:\d{1,2}:\d{2}[ \t]+)?[A-Z]{1,4}:[^\n]*" + _who + r"[^\n]*\?[^\n]*" + _gap + r"[A-Z]{1,4}:[ \t]*")
    for m in qa_rx.finditer(text):
        q_line = text[text.rfind("\n", 0, m.start() + 1) + 1:m.end()]
        if re.search(r"(?i)\b(?:carrier|company|employer|business|bank|insurer|insurance|provider|network|app|school|"
                     r"hospital|clinic|pharmacy|store|restaurant|street|road|city|town|county|plan|program|church|"
                     r"model|make|brand|team|product)\b", q_line.split("\n")[0]):
            continue  # "What's the name of the carrier on that phone? A. Meridian." — not a person

        if re.search(r"(?i)\bnames\b", q_line):
            # a list answer: "Carol is 6, Courtney is 13, Meghan is 13."
            ans_end = text.find("\n", m.end())
            ans_end = len(text) if ans_end < 0 else ans_end
            for nm in re.finditer(rf"(?<![\w'’-])([{UP}][{LO}]+(?:['’-][{UP}]?[{LO}]+)?(?:[ ][{UP}][{LO}]+)?)(?![\w'’-])",
                                  text[m.end():ans_end]):
                w = nm.group(1)
                if w.split()[0].lower() in _FUNCTION_WORDS or w.lower() in ("i", "my", "we", "our", "they", "she", "he",
                                                                             "yes", "no", "and", "the", "both"):
                    continue
                s0 = m.end() + nm.start(1)
                yield _mk(nt, s0, s0 + len(w), "PERSON", 0.85, "qa:person_list", "name given in answer to a names question")
            continue
        rest = text[m.end():text.find("\n", m.end()) if text.find("\n", m.end()) >= 0 else len(text)]
        rest = re.sub(r"^(?:(?:It's|It is|That's|That was|That would be|His name is|Her name is|My name is|I think|"
                      r"Um|Uh|Yes|Yeah|Sure)[,.]?\s+)+", "", rest)
        off = m.end() + (len(text[m.end():m.end() + 400].split("\n")[0]) - len(rest))
        nm = _NAME_VALUE.match(rest)
        if not nm:
            continue
        v = nm.group().rstrip(" ,.")
        if "," in v and len(v.split(",")[0].split()) >= 2:
            v = v.split(",")[0]
        if _NOT_NAME.match(v) or len(v) < 2 or _ORG_WORDS.search(v):
            continue
        words = v.split()
        if any(w.lower().strip(".,") in _FUNCTION_WORDS for w in words):
            continue
        if len(words) == 1 and words[0].lower() in ("no", "yes", "nobody", "none", "i"):
            continue
        yield _mk(nt, off, off + len(v), "PERSON", 0.86, "qa:person", "answer to a who/name question")

    # table headers: a line consisting mostly of labels, values on following lines in the same column
    lines = _lines(text)
    for li, (ls, le) in enumerate(lines):
        header_hits = [h for h in by_line.get(ls, [])]
        line_txt = text[ls:le]
        # a header row: two or more labels, or one label among other column headings ("Patient  DOB  Patient ID")
        if len(header_hits) < 2 and not (header_hits and len(re.findall(r"\S+(?: \S+)*", line_txt)) >= 2 and
                                         re.search(r"\S {2,}\S", line_txt)):
            continue
        covered = sum(h.end - h.start for h in header_hits)
        alpha = sum(c.isalpha() for c in line_txt)
        cells = [c for c in re.split(r" {2,}|\t", line_txt.strip()) if c]
        digits = sum(c.isdigit() for c in line_txt)
        if alpha == 0 or re.search(r"(?<![A-Za-z\d-])\d+(?![A-Za-z\d-])|\d{4,}|\w:\s+\S|\|", line_txt) or \
                digits > 0.15 * (alpha + digits) or (covered / alpha < 0.45 and not (
                len(cells) >= 2 and all(len(c) <= 24 and not re.search(r"[a-z]{2,}\s+[a-z]{2,}\s+[a-z]{2,}", c)
                                        for c in cells))):
            continue
        cols = sorted(((h.start - ls, h) for h in header_hits), key=lambda x: x[0])
        # every heading of the row is a column, labelled or not ("Plan Claim No.  DOS  Provider  CPT"): a value
        # belongs to the heading nearest it, so the CPT column is not read as more claim numbers
        hdr_cells = [(hm.start(), hm.end()) for hm in re.finditer(r"\S+(?: \S+)*", line_txt)]
        for lj in range(li + 1, min(li + 15, len(lines))):
            vs, ve = lines[lj]
            row = text[vs:ve]
            if re.fullmatch(r"[ \t\-=_|+:]*", row):
                continue  # blank or a ruled separator ("----------  --------") under the header
            if not re.search(r"\d", row):
                break
            for m in re.finditer(r"\S+(?: \S+)?", row):
                col = m.start()
                tok = m.group()
                best = min(cols, key=lambda c: abs(c[0] - col))
                cell = min(hdr_cells, key=lambda c: min(abs(c[0] - col), abs(c[1] - (col + len(tok)))))
                if not cell[0] <= best[0] < cell[1] and not any(cell[0] <= c[0] < cell[1] for c in cols):
                    continue  # under a heading that is not an ID label
                best = next((c for c in cols if cell[0] <= c[0] < cell[1]), best)
                lab = best[1].label
                if lab.entity == "BANK_ACCOUNT" and re.search(r"(?i)(?:\bgl|\bg/l|general\s+ledger|ledger)\s*$",
                                                               text[max(0, best[1].start - 16):best[1].start]):
                    continue  # "GL ACCOUNT  6010-10": a general-ledger code
                if lab.shape == "file" or lab.entity in ("DEVICE_ID", "ID_NUMBER") or (
                        lab.entity in ("LAW_ENFORCEMENT_ID", "CASE_NUMBER") and len(re.sub(r"\D", "", tok)) < 5):
                    continue  # generic columns are too ambiguous to assign positionally
                tm = _TOK[lab.shape].fullmatch(tok) or _TOK[lab.shape].search(tok)
                if not tm:
                    continue
                val = tm.group()
                ok, adj = _value_ok(lab.shape, lab.entity, val)
                if not ok or lab.shape == "username" and val.isalpha() and val.islower():
                    continue  # "since" under an "(FSA ID)" heading — a word, not a handle
                s = vs + m.start() + tm.start()
                e = s + len(val)
                if (s, e) in emitted:
                    continue
                emitted.add((s, e))
                yield _mk(nt, s, e, lab.entity, 0.78 + adj, f"table:{lab.entity.lower()}",
                          f"value under table column “{text[best[1].start:best[1].end].strip()}”")


def _lines(text: str) -> list[tuple[int, int]]:
    out, pos = [], 0
    for part in text.split("\n"):
        out.append((pos, pos + len(part)))
        pos += len(part) + 1
    return out


def _mk(nt: NormText, s: int, e: int, entity: str, score: float, source: str, why: str) -> Span:
    os_, oe = nt.to_original(s, e)
    return Span(os_, oe, entity, min(score, 0.99), source, nt.original[os_:oe], why)


# ---------------------------------------------------------------------------------------------
# Key/value fields whose values are names, addresses or dates
# ---------------------------------------------------------------------------------------------

PERSON_LABELS = re.compile(
    r"(?im)(?<![a-z])(?:(?:full|legal|first|last|middle|maiden|print(?:ed)?|patient'?s?|client'?s?|insured'?s?|"
    r"employee'?s?|applicant'?s?|claimant'?s?|member'?s?|subscriber'?s?|parent'?s?|guardian'?s?|"
    r"spouse'?s?|child'?s?|father'?s?|mother'?s?|witness'?s?|driver'?s?|owner'?s?|victim'?s?|suspect'?s?|"
    r"decedent'?s?|tenant'?s?|account\s*holder'?s?|policy\s*holder'?s?|cardholder'?s?|beneficiary'?s?|"
    r"responsible\s*party'?s?|guarantor'?s?|contact|physician'?s?|doctor'?s?|provider'?s?|nurse'?s?|"
    r"therapist'?s?|officer'?s?|adjuster'?s?|attorney'?s?|signer'?s?|notary'?s?|referring|attending|"
    r"ordering|treating|primary\s*care)\s*name"
    r"|name\s*of\s*(?:patient|insured|claimant|driver|owner|witness|victim|employee|applicant|parent|"
    r"guardian|deceased|decedent|minor|child|spouse|physician|provider|officer|adjuster|attorney)"
    r"|(?:patient|client|claimant|insured|plaintiff|plaintiffs|defendant|defendants|petitioner|respondent|"
    r"appellant|appellee|witness|driver|owner|registered\s*owner|passenger|pedestrian|victim|suspect|"
    r"complainant|reporting\s*party|rp|guardian|parent|parent/guardian|spouse|emergency\s*contact|"
    r"next\s*of\s*kin|nok|beneficiary|employee|applicant|decedent|deceased|minor|child|mother|father|"
    r"taxpayer|borrower|co-?borrower|co-?signer|co-?applicant|joint\s*(?:owner|account\s*holder|debtor)|debtor|"
    r"obligor|obligee|remitter|trustee|executor|executrix|personal\s*representative|grantor|settlor|custodian|"
    r"resident|tenant|landlord|subscriber|policyholder|policy\s*holder|member|responsible\s*party|guarantor|"
    r"contact\s*person|attending(?:\s*physician)?|physician|referring\s*physician|provider|rendering\s*provider|"
    r"pcp|surgeon|therapist|treating\s*doctor|adjuster|claims?\s*adjuster|officer|investigating\s*officer|"
    r"reporting\s*officer|deputy|trooper|interpreter|translator|notary|signed|signature|signed\s*by|"
    r"printed\s*name|print\s*name|name|full\s*name|legal\s*name|aka|a\.k\.a\.|alias|nickname|"
    r"attn|attention|to|from|cc|bcc|re|patient/client|employer\s*contact|supervisor|manager|witnessed\s*by|"
    r"prepared\s*by|reviewed\s*by|dictated\s*by|electronically\s*signed\s*by|authenticated\s*by|"
    r"transcribed\s*by|approved\s*by|ordered\s*by|seen\s*by|referred\s*by|accompanied\s*by|"
    r"verified\s*by|requested\s*by|insured\s*driver|claimant\s*driver|operator|caller|reporting\s*person|"
    r"your\s*insured|our\s*client|insured\s*name|owner/lessee|driver/owner|lessee|co-?owner|deponent|affiant|"
    r"declarant|grantor|grantee|borrower|co-?borrower|payee|remitter|drawer|recipient|sender|patient\s*/\s*resident|"
    r"completed\s*by|filled\s*out\s*by|submitted\s*by|received\s*by|taken\s*by|interviewed\s*by|examined\s*by|"
    r"treated\s*by|intake\s*by|entered\s*by|recorded\s*by|reported\s*by|investigated\s*by|served\s*by|"
    r"also\s*present|present|for\s*the\s*plaintiffs?|for\s*the\s*defendants?|for\s*plaintiffs?|for\s*defendants?|"
    r"other\s*names?\s*used|maiden\s*name|previous\s*name|former\s*name|formerly\s*known\s*as|f/k/a|n/k/a|"
    r"d/b/a|alias(?:es)?|known\s*as|parent/guardian|legal\s*guardian|caregiver|case\s*manager|social\s*worker|"
    r"therapist\s*name|counselor|psychologist|psychiatrist|referring\s*provider|pcp\s*name|primary\s*physician|"
    r"account\s*holder|card\s*holder|cardholder|policy\s*owner|named\s*insured|"
    # chart / flowsheet roles: "Nurse: Rachel Tomczak, RN", "Prescriber: …", "Administered by: …", "Pt: …"
    r"nurse|rn|lpn|cna|charge\s*nurse|prescriber|prescribing\s*(?:physician|provider)|administered\s*by|given\s*by|"
    r"pt|pt\s*name|resident\s*physician|fellow|intern|technician|tech|technologist|phlebotomist|pharmacist|"
    r"dispensed\s*by|collected\s*by|performed\s*by|read\s*by|interpreted\s*by|consultant|consulting\s*physician|"
    r"dependent|dependents?\s*name|"
    r"insured'?s?\s*name|claimant'?s?\s*name|employee\s*name|supervisor\s*name|manager\s*name|"
    r"emergency\s*contact\s*name|contact\s*name|witness\s*\d|passenger\s*\d|occupant\s*\d?|child\s*\d|"
    r"dependent\s*\d?|minor\s*\d?|son|daughter|parent\s*\d|beneficiary\s*\d)"
    r")(?:/[A-Za-z ]{1,20})?\s*(?:\([^)\n]{0,40}\))?\)?\s*[:]\s*")

_NAME_VALUE = re.compile(
    r"(?:(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Rev|Hon|Sgt|Det|Lt|Capt|Ofc|Officer|Deputy|Trooper)\.?\s+)?"
    rf"(?:[{UP}][{UP}{LO}'’\-]+|[{UP}]\.)(?:,?[ \t]{{1,2}}(?:[{UP}][{UP}{LO}'’\-]+|[{UP}]\.?|(?:de|da|del|della|van|von|der|"
    rf"le|la|du|bin|ibn|al|el|st\.|los|las|den|ter|ten)(?=[ \t]+(?:[{UP}]|(?:la|le|der|den|los|las)\b)))){{0,5}}"
    r"(?:,?[ \t]{1,2}(?:Jr|Sr|II|III|IV|V|MD|M\.D|DO|D\.O|RN|NP|PA-C|PA|PhD|Esq|DC|DPT|PT|LCSW|CRNA|DDS|DMD)\.?)*")
_NOT_NAME = re.compile(r"(?i)^(?:n/?a|none|unknown|same|self|yes|no|male|female|other|see\s.*|pending|unk|"
                       r"parent|guardian|spouse|husband|wife|mother|father|son|daughter|child|sibling|friend|"
                       r"employer|attorney|legal\s+guardian|power\s+of\s+attorney|poa|relative|"
                       r"refused|declined|deceased|single|married|divorced|widowed|patient|insured|claimant|"
                       r"plaintiff|defendant|minor|child|the|this|that|state|county|city|department|"
                       r"hospital|clinic|center|company|inc|llc|corp|insurance|bank|court|united\s+states|"
                       r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|regarding|re|subject)$")
_ORG_WORDS = re.compile(r"(?i)\b(?:inc|llc|l\.l\.c|corp|corporation|company|co\.|insurance|mutual|hospital|clinic|"
                        r"medical|health|healthcare|group|associates|partners|bank|court|county|"
                        r"department|dept|university|college|school|services|systems|pharmacy|"
                        r"laboratory|law|firm|pllc|p\.a\.|lp|llp|office|agency|police|sheriff|"
                        r"authority|district|foundation|holdings|enterprises|motors|automotive|industries|international|"
                        r"bureau|commission|ministry)\b")
# words that can be surnames ("Hope Church", "Rose Banks") — only organisational in 3+ word values
_WEAK_ORG_WORDS = re.compile(r"(?i)\b(?:center|centre|church|state|city|trust|fund|labs?|imaging|radiology|therapy|"
                             r"rehab(?:ilitation)?|orthopedics?|chiropractic|fire|ems|transit|banks?)\b")
_EMAIL_HDR_LABELS = {"to", "from", "cc", "bcc"}
# labels that open a turn in a call / deposition transcript
_SPEAKER_LABELS = {"caller", "operator", "witness", "deponent", "interpreter", "translator", "reporting person"}


_FUNCTION_WORDS = {"your", "our", "my", "his", "her", "their", "its", "the", "a", "an", "this", "that", "these",
                   "those", "insured", "client", "patient", "claimant", "plaintiff", "defendant", "same", "as", "above",
                   "see", "attached", "unknown", "none", "not", "applicable"}


_LABEL_MOD = (r"Home|Cell|Work|Mobile|Date|Visit|Patient|Emergency|Policy|Member|Group|Claim|Account|Acct|Zip|Postal|"
              r"Social|Security|Phone|Fax|E-?mail|Marital|Insurance|Primary|Secondary|Contact|Driver'?s|License|"
              r"Plate|Case|Badge|Report|Employer|Job|Middle|First|Last|Full|Birth|Place|Mailing|Street|Tax|Federal|"
              r"Medical|Record|Chart|Health|Plan|Subscriber|Guarantor|Responsible|Next|Of|Date of|Type|Unit|Seat")
_NEXT_LABEL = re.compile(rf"\s+(?:(?:{_LABEL_MOD})\s+){{0,2}}[A-Z][A-Za-z'’-]*\s?(?:#|No\.|ID|Number|TIN|SSN|EIN|ITIN|DOB|"
                         rf"Name)?\s?:\s|\s{{3,}}")


def cut_at_next_label(value: str) -> str:
    """OCR collapses the gap between form fields; stop a value where the next "Label:" begins."""
    m = _NEXT_LABEL.search(value)
    return value[:m.start()] if m else value


def _clean_name_value(line_rest: str) -> str | None:
    m = _NAME_VALUE.match(cut_at_next_label(line_rest))
    if not m:
        return None
    v = m.group().rstrip(" ,.")
    # "DESHAWN M ABERNATHY  DBA ABERNATHY MOBILE DETAILING": the trade name after "DBA" is a business
    v = re.split(r"\s+(?:DBA|D/B/A|dba|d/b/a)(?![\w/])", v)[0].rstrip(" ,.")
    # "Richard Santiago, Injury Severity…": a comma only belongs to the name in LAST, FIRST form
    if "," in v:
        before, _, after = v.partition(",")
        if len(before.split()) >= 2 and not re.match(r"\s*(?:Jr|Sr|II|III|IV|MD|M\.D|DO|RN|NP|PA|PhD|Esq)\b", after):
            v = before
    # a following form label ("JOHNSON, MARY A   MRN: ...") is not part of the name
    lab = _find_label_hits(v)
    if lab:
        v = v[:lab[0].start].rstrip(" ,.")
    if _NOT_NAME.match(v) or len(v) < 2:
        return None
    words = [w for w in re.split(r"[\s,]+", v) if w]
    if len(words) > 7:
        return None
    if all(len(w.strip(".")) <= 1 for w in words):
        return None
    if any(w.lower().strip(".,") in _FUNCTION_WORDS for w in words if len(w.strip(".,")) > 1):
        return None
    from .names import HARD_STOP, SURNAME_WORDS
    from .negatives import LEGAL_ROLES, OCCUPATION_WORDS
    lows = [w.lower().strip(".,") for w in words]
    if any(w in HARD_STOP and w not in SURNAME_WORDS for w in lows if len(w) > 2):
        return None  # "LETTER OF PROTECTION", "EMPLOYMENT AND WAGE VERIFICATION"
    if all(w in OCCUPATION_WORDS or w in LEGAL_ROLES for w in lows):
        return None
    return v


def find_kv_people(nt: NormText) -> Iterator[Span]:
    """Values after person labels: ``Patient: DOE, JANE A``; ``Insured Driver: Marcus T. Reyes``."""
    text = nt.text
    for m in PERSON_LABELS.finditer(text):
        label = m.group().strip(" :").lower()
        rest_start = m.end()
        line_end = text.find("\n", rest_start)
        line_end = len(text) if line_end < 0 else line_end
        rest = text[rest_start:line_end]
        # value can sit on the next line when the label ends the line ("Patient Name:\nJANE DOE")
        if not rest.strip() and line_end < len(text):
            nxt_end = text.find("\n", line_end + 1)
            nxt_end = len(text) if nxt_end < 0 else nxt_end
            rest_start = line_end + 1
            rest = text[rest_start:nxt_end]
        lead = len(rest) - len(rest.lstrip())
        if label in _EMAIL_HDR_LABELS:
            # email headers: names before <addresses>, comma/semicolon separated
            for nm in re.finditer(rf"(?:\"?([{UP}][{UP}{LO}'’\-]+(?:\s+(?:[{UP}][{UP}{LO}.'’\-]+|de|da|del|la|van|von|der|bin|al)){{1,4}})\"?\s*<)", rest):
                s = rest_start + nm.start(1)
                yield _mk(nt, s, s + len(nm.group(1)), "PERSON", 0.93, "kv:email_header", f"name in {label}: header")
            continue
        if label in ("re", "attn", "attention"):
            v = _clean_name_value(rest[lead:])
            if not v or len(v.split()) < 2:
                continue
        else:
            v = _clean_name_value(rest[lead:])
        if not v:
            continue
        if _ORG_WORDS.search(v) or (_WEAK_ORG_WORDS.search(v) and len(v.split()) >= 3):
            continue
        after = text[rest_start + lead + len(v):rest_start + lead + len(v) + 18]
        # a name field holds a name, not a sentence: "CALLER: Thank you.", "THE WITNESS: He also told me",
        # "[operator: OCR misread on MICR", "Re: Subpoena Duces Tecum dated …"
        if len(v.split()) == 1 and re.match(r"[ \t]+(?!(?:and|or|v|vs|et|aka|nka|fka|de|da|del|la|van|von)\b)[a-z]", after):
            continue
        if label in ("re", "attn", "attention") and re.match(
                r"[ \t]+(?:dated|filed|served|issued|signed|received|sent|of|for|from|on|to|with|regarding)\b", after):
            continue
        if label in _SPEAKER_LABELS and len(v.split()) == 1 and re.match(r"[.!?]+[ \t]+\S", after) and (
                m.group().strip(" :").isupper() or re.search(r"[\]\d][ \t]*$", text[max(0, m.start() - 4):m.start()])):
            continue  # "[00:00:26] CALLER: Chorizo. C-H-O-R-I-Z-O." — a transcript turn, not a name field
        if re.match(r"\s+of\s+[A-Z]", after):
            continue  # "Requested by: NH Bureau of Elderly & Adult Services"
        if re.match(r"\s*(?:&\s+[A-Z]|,?\s+(?:LLP|LLC|Inc|P\.C\.|PLLC|P\.A\.|Law\b|Group\b))", after):
            continue  # "Brown & Kessler LLP"
        if label in ("name", "to", "from", "re", "signature", "signed") and len(v.split()) < 2:
            continue
        s = rest_start + lead
        e = s + len(v)
        # drop a leading honorific / title from the redaction box
        hm = re.match(r"(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Rev|Hon|Sgt|Det|Lt|Capt|Ofc|Officer|Deputy|Trooper)\.?\s+", v)
        if hm:
            s += hm.end()
        cm = re.search(r"(?:,?\s+(?:Jr|Sr|II|III|IV|MD|M\.D|DO|D\.O|RN|NP|PA-C|PA|PhD|Esq|DC|DPT|PT|LCSW|CRNA|"
                       r"DDS|DMD)\.?)+$", text[s:e])
        if cm and cm.group().strip(" ,.") not in ("Jr", "Sr", "II", "III", "IV"):
            e = s + cm.start()
        if re.search(r"(?i)\b(?:co(?:mpany)?|business|merchant|bank|employer|firm|store|vendor|payee\s+bank)\s*$",
                     text[max(0, m.start() - 14):m.start()]):
            continue  # "ORIG CO NAME:ACME LOGISTICS", "Business name:" — an organisation, not a person
        yield _mk(nt, s, e, "PERSON", 0.93, "kv:person", f"value of “{m.group().strip(' :')}” field")


_ADDRESS_LABEL = re.compile(r"(?im)(?<![a-z])(?:(?:home|mailing|street|residential|residence|billing|"
                            r"physical|permanent|current|previous|prior|patient|client|insured|employer|"
                            r"owner'?s?|driver'?s?|witness|victim|incident|loss|service)\s*address"
                            r"|address(?:\s*line\s*[12])?|addr\.?|residence|resides\s+at|lives\s+at|"
                            r"street|domicile|location\s+of\s+(?:incident|accident|loss|crash|occurrence))"
                            r"\s*(?:\(s\))?\s*[:]\s*")
_CITY_STATE_ZIP = re.compile(r"^[ \t]*[A-Z][A-Za-z.' -]{1,40},?\s+(?:[A-Z]{2}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)\.?"
                             r"\s+\d{5}(?:-\d{4})?[ \t]*$")


def find_kv_addresses(nt: NormText) -> Iterator[Span]:
    text = nt.text
    for m in _ADDRESS_LABEL.finditer(text):
        s = m.end()
        e = text.find("\n", s)
        e = len(text) if e < 0 else e
        # stop at a following label on the same line (e.g. "Address: 1 Elm St   Phone: ...")
        e = s + len(cut_at_next_label(text[s:e]))
        val = text[s:e].strip()
        if re.match(r"(?i)(?:same|sa(?:rn|m)e)\s+as\b", val):
            continue  # "Address: same as Signer 1" (OCR "sarne as") — a pointer, not an address
        if not val or not re.search(r"\d|P\.?\s?O\.?\s*Box|box", val, re.I) or _PLACEHOLDER.match(val):
            if not val and e < len(text):  # label at end of line, value on the next line
                ns = e + 1
                ne = text.find("\n", ns)
                ne = len(text) if ne < 0 else ne
                if re.search(r"\d", text[ns:ne]):
                    s, e = ns, ne
                    val = text[s:e].strip()
                else:
                    continue
            else:
                continue
        lead = len(text[s:e]) - len(text[s:e].lstrip())
        s += lead
        e = s + len(val)
        # absorb a following "City, ST 12345" line
        if e < len(text) and text[e:e + 1] == "\n":
            ne = text.find("\n", e + 1)
            ne = len(text) if ne < 0 else ne
            if _CITY_STATE_ZIP.match(text[e + 1:ne]):
                e = ne
        yield _mk(nt, s, e, "ADDRESS", 0.93, "kv:address", f"value of “{m.group().strip(' :')}” field")


ALL_LABEL_FINDERS = [find_column_names, find_labelled_ids, find_kv_people, find_kv_addresses]
