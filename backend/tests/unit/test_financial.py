"""Financial documents: statements, tax forms, pay stubs, loans, credit reports, checks, wires.

Each case lists values that must be covered by a redaction, and values that must stay visible (form numbers,
line labels, CUSIPs, tickers, OMB numbers, company ACH ids, rates).
"""
import pytest

from tests.conftest import covers

CASES = {
    # ---- bank statements: transaction descriptions name people ---------------------------------------------
    "zelle_to": ("03/04  ZELLE TO MARIA GOMEZ ON 03/04 REF #PP0ABC1234            -250.00", ["MARIA GOMEZ"], []),
    "zelle_from": ("03/07  Zelle payment from KEVIN O'BRIEN Conf# 9f8e7d         1,200.00", ["KEVIN O'BRIEN"], []),
    "venmo": ("03/09  VENMO *JSMITH1987 NEW YORK NY                          -45.00", ["JSMITH1987"], []),
    "cashapp": ("03/11  CASH APP*TANYA R*4417 OAKLAND CA                          -60.00", ["TANYA R"], []),
    "online_transfer": ("03/12  ONLINE TRANSFER TO DAVID CHEN XXXXXX8812 REF #IB0Q2W        -500.00",
                        ["DAVID CHEN", "8812"], []),
    "ach_ind_name": ("ORIG CO NAME:ACME LOGISTICS ORIG ID:1234567890 DESC DATE:030425 CO ENTRY DESCR:PAYROLL "
                     "SEC:PPD TRACE#:021000020123456 EED:250305 IND ID:000045771 IND NAME:REYES, ANTHONY J",
                     ["REYES, ANTHONY J", "000045771"], []),
    "check_paid": ("03/15  CHECK 1042 PAID TO R. OKAFOR                                 -300.00", ["R. OKAFOR"], []),
    "transfer_from_sav": ("03/18  DEP TFR FROM SAV xxxxx4417                                   200.00", ["4417"], []),
    "account_header": ("Primary Account Number: 4831 0072 9915\nRouting Number: 021000021", ["4831 0072 9915", "021000021"], []),
    "acct_ending": ("Your Everyday Checking (acct ending 4417) earned $0.12 in interest.", ["4417"], []),
    "acct_x_dash": ("Transfers to Savings x-8812 are free.", ["8812"], []),
    "acct_dots": ("Account ...7731 was overdrawn twice.", ["7731"], []),
    # ---- card statements ------------------------------------------------------------------------------------
    "coupon": ("PAYMENT COUPON  Account Number 4147 2024 1098 5521  Amount Enclosed $____", ["4147 2024 1098 5521"], []),
    "card_last4": ("Card ending in 5521  New Balance $1,284.10  Minimum Payment Due $35.00", ["5521"], []),
    "card_masked": ("Card number: XXXX XXXX XXXX 5521   Exp 09/28", ["5521", "09/28"], []),
    # ---- checks / MICR --------------------------------------------------------------------------------------
    "micr_symbols": ("⑆021000021⑆ 4831007299⑈ 1042", ["021000021", "4831007299"], []),
    "micr_ocr": ("A021000021A 4831007299C 1042", ["021000021", "4831007299"], []),
    "micr_plain": ("Routing 021000021   Account 4831007299   Check 1042", ["021000021", "4831007299"], []),
    # ---- tax forms ------------------------------------------------------------------------------------------
    "w2_ssn": ("a Employee's social security number\n    412-55-0198\nOMB No. 1545-0008", ["412-55-0198"],
               ["1545-0008"]),
    "w2_ein": ("b Employer identification number (EIN)\n    47-3920115", ["47-3920115"], []),
    "w2_name": ("e Employee's first name and initial     Last name\n  DANIELA M                             OKONKWO",
                ["DANIELA M", "OKONKWO"], []),
    "w2_state_id": ("15 State  Employer's state ID number\n   TX     30-1234567-8", ["30-1234567-8"], []),
    "1040_dd": ("35b Routing number  021000021   c Type: Checking   d Account number  4831007299",
                ["021000021", "4831007299"], []),
    "1040_dependent": ("(1) First name   Last name     (2) SSN          (3) Relationship\n"
                       "    Mia          Okonkwo           611-22-3344      Daughter",
                       ["Mia", "Okonkwo", "611-22-3344"], []),
    "1099_payer_tin": ("PAYER'S TIN  27-1188420     RECIPIENT'S TIN  ***-**-0198", ["27-1188420", "0198"], []),
    # ---- pay stubs ------------------------------------------------------------------------------------------
    "paystub_ids": ("Employee ID: 004417   Pay Group: BW   SSN: XXX-XX-0198", ["004417", "0198"], []),
    "paystub_dd": ("Direct Deposit  Checking ****7731  $1,450.22   Savings ****2290  $200.00", ["7731", "2290"], []),
    "garnishment": ("Child Support Garnishment  Case# 2024-DR-118842   -312.50", ["2024-DR-118842"], []),
    # ---- loans / mortgage -----------------------------------------------------------------------------------
    "loan_number": ("Loan Number: 7700123456     MIN: 1000123-4567890123-4", ["7700123456", "1000123-4567890123-4"], []),
    "loan_hash": ("Re: Loan # 0049-221783 (FHA Case No. 492-1234567-703)", ["0049-221783", "492-1234567-703"], []),
    "auto_loan_vin": ("Auto loan 88-1192-04 secured by 2021 Honda CR-V VIN 2HKRW2H85MH601234",
                      ["88-1192-04", "2HKRW2H85MH601234"], []),
    "wire": ("Beneficiary: Lakshmi Narayanan  Beneficiary Account: 000123456789  ABA: 026009593\n"
             "Beneficiary Bank: Bank of America N.A.  SWIFT: BOFAUS3N",
             ["Lakshmi Narayanan", "000123456789", "026009593"], []),
    "iban_wire": ("Credit to IBAN DE89 3704 0044 0532 0130 00 (Jonas Albrecht)", ["DE89 3704 0044 0532 0130 00",
                                                                               "Jonas Albrecht"], []),
    # ---- credit report --------------------------------------------------------------------------------------
    "tradeline_masked": ("CAPITAL ONE         Acct# 517805XXXXXX   Revolving   Opened 03/2019   Bal $2,140",
                         ["517805"], []),
    "tradeline_partial": ("SYNCHRONY/AMAZON    Account #: 6045****1188   Status: Pays as agreed", ["6045", "1188"], []),
    "credit_inquiry_ssn": ("Social Security #: XXX-XX-4417   Year of Birth: 1984", ["4417"], []),
    # ---- online banking / fraud disputes --------------------------------------------------------------------
    "security_q": ("Security question: Mother's maiden name? Answer: Kowalski", ["Kowalski"], []),
    "online_user": ("Online Banking User ID: dokonkwo84   Last login from IP 73.158.22.41", ["dokonkwo84", "73.158.22.41"], []),
    "pin": ("Customer verified with debit card PIN 4417 at the branch.", ["4417"], []),
    "member_number": ("Member Number: 0088123   Share ID 01 Savings   Share ID 09 Checking", ["0088123"], []),
}

NEGATIVES = [
    "Form W-2 Wage and Tax Statement 2025   OMB No. 1545-0008   Cat. No. 10134D",
    "Box 12a  D  5,000.00   Box 12b  DD  8,412.00",
    "Line 1z  Add lines 1a through 1h ........ 1z  84,220",
    "APPLE INC  CUSIP 037833100  AAPL  25.000 shares  $5,432.10",
    "VANGUARD 500 INDEX ADMIRAL  VFIAX  CUSIP 922908710",
    "PPD ID: 1234567890 ACH CREDIT IRS TREAS 310 TAX REF",
    "NAICS code 541110   SIC 8111",
    "APR 24.99%   Penalty APR 29.99%   Cash advance APR 29.24%",
    "See IRS Publication 590-A for details. Schedule C (Form 1040) 2025",
    "Page 2 of 6   Statement Period 03/01/2025 - 03/31/2025",
    "Member FDIC. Equal Housing Lender. NMLS #399801",
]


@pytest.mark.parametrize("name", list(CASES))
def test_financial_values_redacted(rules, name):
    text, must, keep = CASES[name]
    spans = rules(text, profile="financial")
    sel = [s for s in spans if s.meta.get("selected", True)]
    missing = [v for v in must if not covers(sel, v, text)]
    assert not missing, (missing, [(s.entity, s.text) for s in sel])
    for v in keep:
        i = text.index(v)
        assert not any(s.start < i + len(v) and i < s.end for s in sel), (v, [(s.entity, s.text) for s in sel])


@pytest.mark.parametrize("text", NEGATIVES)
def test_financial_hard_negatives(rules, text):
    sel = [s for s in rules(text, profile="financial") if s.meta.get("selected", True)
           and s.entity not in ("MONEY", "FINANCIAL_INFO", "ORGANIZATION")]
    assert not sel, [(s.entity, s.text, s.source) for s in sel]


def test_financial_profile_exists():
    from obscura.detection.text.entities import PROFILES, entities_for_profile
    assert "financial" in PROFILES
    ents = entities_for_profile("financial")
    assert {"BANK_ACCOUNT", "ROUTING_NUMBER", "CREDIT_CARD", "SSN", "EIN", "PERSON", "USERNAME", "PASSWORD",
            "IBAN", "CRYPTO_WALLET", "FINANCIAL_INFO", "CASE_NUMBER"} <= ents
    assert "MONEY" not in ents  # amounts stay readable unless the reviewer asks


CASES_2 = {
    "brokerage_alnum": ("Account Number: 5WB-12345   Account Type: Individual TOD", ["5WB-12345"], []),
    "ira_beneficiary": ("Primary Beneficiary: Samuel T. Okonkwo (son) 50%   Contingent: Grace Okonkwo 50%",
                        ["Samuel T. Okonkwo", "Grace Okonkwo"], []),
    "recipient_block": ("RECIPIENT'S name\nDANIELA M OKONKWO\nStreet address (including apt. no.)\n4417 BRIARWOOD LN APT 2C",
                        ["DANIELA M OKONKWO", "4417 BRIARWOOD LN APT 2C"], []),
    "taxpayer_name": ("Taxpayer: Marcus J. Ellery    Spouse: Renata Ellery    Filing status: MFJ", ["Marcus J. Ellery",
                                                                                                 "Renata Ellery"], []),
    "lien_patient_acct": ("Medical lien - Baylor Scott & White, patient acct 88123004, paid at reduced amount $4,100.00",
                          ["88123004"], []),
    "iolta_wire": ("Wire to IOLTA Trust Account #3300418871 at Frost Bank, ABA 114000093", ["3300418871", "114000093"], []),
    "medicare_cpl": ("Medicare conditional payment letter, MBI 1EG4-TE5-MK73, total conditional payments $2,350.11",
                     ["1EG4-TE5-MK73"], []),
    "credit_employer": ("EMPLOYMENT: SAN ANTONIO FOOD BANK - WAREHOUSE LEAD   Reported 06/2023", ["SAN ANTONIO FOOD BANK"], []),
    "prior_address": ("Previous address: 1209 W Magnolia Ave, San Antonio, TX 78201 (reported 2019)",
                      ["1209 W Magnolia Ave, San Antonio, TX 78201"], []),
    "credit_score": ("Your FICO Score 8 is 612 as of 03/02/2025.", ["612"], []),
    "net_worth": ("Petitioner's net worth is approximately $1.2 million, mostly in a 401(k).", ["net worth"], []),
    "crypto": ("Withdrawal to bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh confirmed (2 confirmations).",
               ["bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"], []),
    "card_expiry_cvv": ("Card 4147 2024 1098 5521 exp 09/28 CVV 417", ["4147 2024 1098 5521", "09/28", "417"], []),
    "check_endorse": ("Endorsed: For deposit only to acct 4831007299 — Daniela Okonkwo", ["4831007299", "Daniela Okonkwo"], []),
    "bk_case": ("United States Bankruptcy Court, W.D. Tex.  Case No. 25-50412-cag  Chapter 7", ["25-50412-cag"], []),
    "collection_ref": ("Re: Original creditor SYNCHRONY BANK, our reference no. CL-2291847, balance $1,844.20",
                       ["CL-2291847"], []),
}

NEGATIVES_2 = [
    "SPDR S&P 500 ETF TRUST  SPY  CUSIP 78462F103  12.000 shares",
    "Form 1099-INT (Rev. January 2024)  Cat. No. 14410K  www.irs.gov/Form1099INT",
    "Interest rate 6.875%   APR 7.012%   Points 0.250%",
    "Section 199A dividends  Box 5  0.00",
    "Federal Reserve Bank of Dallas routing symbol  Member FDIC",
]


@pytest.mark.parametrize("name", list(CASES_2))
def test_financial_values_redacted_2(rules, name):
    text, must, keep = CASES_2[name]
    sel = [s for s in rules(text, profile="financial") if s.meta.get("selected", True)]
    missing = [v for v in must if not covers(sel, v, text)]
    assert not missing, (missing, [(s.entity, s.text) for s in sel])


@pytest.mark.parametrize("text", NEGATIVES_2)
def test_financial_hard_negatives_2(rules, text):
    sel = [s for s in rules(text, profile="financial") if s.meta.get("selected", True)
           and s.entity not in ("MONEY", "FINANCIAL_INFO", "ORGANIZATION")]
    assert not sel, [(s.entity, s.text, s.source) for s in sel]


def test_financial_last4_keeps_last_digits(rules):
    text = "Primary Account Number: 4831 0072 9915   SSN 412-55-0198   Card 4147 2024 1098 5521"
    spans = [s for s in rules(text, profile="financial_last4") if s.meta.get("selected", True)]
    parts = {s.entity: s.meta.get("partial") for s in spans}
    assert parts.get("BANK_ACCOUNT") == "last4" and parts.get("SSN") == "last4" and parts.get("CREDIT_CARD") == "last4"


def test_financial_profiles_listed():
    from obscura.detection.text.entities import PROFILES, entities_for_profile
    assert entities_for_profile("financial_last4") == entities_for_profile("financial")
    assert "court" in PROFILES["financial_last4"].lower()


CASES_3 = {
    "mailing_block": ("FROST BANK  PO BOX 1600  SAN ANTONIO TX 78296\n\n    DANIELA M OKONKWO\n    4417 BRIARWOOD LN APT 2C\n"
                      "    SAN ANTONIO TX 78229-1234\n\nStatement Period 03/01/2025 - 03/31/2025",
                      ["DANIELA M OKONKWO", "4417 BRIARWOOD LN APT 2C", "SAN ANTONIO TX 78229-1234"], []),
    "statement_for": ("Statement for: MARCUS J ELLERY   Customer since 2011", ["MARCUS J ELLERY"], []),
    "w2_employer_block": ("c Employer's name, address, and ZIP code\n  ELLERY ROOFING & GUTTERS LLC\n  880 COMMERCE ST\n"
                          "  SAN MARCOS TX 78666", ["ELLERY ROOFING & GUTTERS LLC"], []),
    "aka": ("Also known as: DANI OKONKWO; D M OKONKWO-REYES", ["DANI OKONKWO", "D M OKONKWO-REYES"], []),
    "payer_sole_prop": ("PAYER'S name, street address, city or town, state or province, country, ZIP\n"
                        "  RENATA ELLERY DBA ELLERY BOOKKEEPING\n  12 OAK HOLLOW DR", ["RENATA ELLERY"], []),
    "joint_owners": ("Account Owners: Marcus J. Ellery and Renata Ellery (JTWROS)", ["Marcus J. Ellery", "Renata Ellery"], []),
    "pos_atm_location": ("03/21  ATM WITHDRAWAL 7-ELEVEN #33021 1450 S ZARZAMORA ST SAN ANTONIO TX  -60.00",
                         [], []),
}


@pytest.mark.parametrize("name", list(CASES_3))
def test_financial_values_redacted_3(rules, name):
    text, must, keep = CASES_3[name]
    sel = [s for s in rules(text, profile="financial") if s.meta.get("selected", True)]
    missing = [v for v in must if not covers(sel, v, text)]
    assert not missing, (missing, [(s.entity, s.text) for s in sel])


def test_ofx_download(rules):
    text = ("<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKACCTFROM><BANKID>021000021<ACCTID>4831007299<ACCTTYPE>CHECKING"
            "</BANKACCTFROM><STMTTRN><TRNTYPE>DEBIT<NAME>ZELLE TO MARIA GOMEZ<MEMO>rent</STMTTRN>")
    sel = [s for s in rules(text, profile="financial") if s.meta.get("selected", True)]
    for v in ("021000021", "4831007299", "MARIA GOMEZ"):
        assert covers(sel, v, text), (v, [(s.entity, s.text) for s in sel])
    assert not covers(sel, "CHECKING", text)


def test_mt940(rules):
    text = ":20:STMT2025-03\n:25:DE89370400440532013000\n:28C:00042/001\n:60F:C250301EUR1234,56"
    sel = [s for s in rules(text, profile="financial") if s.meta.get("selected", True)]
    assert covers(sel, "DE89370400440532013000", text)


def test_qif_payee_suggested_not_selected(rules):
    text = "!Type:Bank\nD03/04/2025\nT-250.00\nPMaria Gomez\n^\nD03/05/2025\nT-4.50\nPSTARBUCKS 1123\n^"
    spans = rules(text, profile="financial", include_suggestions=True)
    mg = [s for s in spans if s.text == "Maria Gomez"]
    assert mg and not any("STARBUCKS" in s.text and s.entity == "PERSON" for s in spans)


def test_bank_download_extensions():
    from obscura.processing import KIND_BY_EXT
    assert all(KIND_BY_EXT[e] == "text" for e in ("ofx", "qfx", "qbo", "qif", "mt940"))


CASES_4 = {
    "ln_x_dash": ("09/08  ACH DEBIT RIVERSIDE AUTO FIN AUTOPAY LN x-5521              312.00", ["5521"], []),
    "dots": ("Transfers from Harbor Savings ...6610 and Coastline ...30-11 were reversed.", ["6610", "30-11"], []),
    "card_txn": ("09/05  POS DEBIT GAS N GO 0412 SPRINGDALE AR CARD 6631               41.20", ["6631"], []),
    "ending_generic": ("Signature card on file (Primary: R. Ellery) ... ending 2290", ["2290"], []),
    "ending_year": ("for the fiscal year ending 2025 the account earned interest", [], ["2025"]),
    "spaced_mask": ("ACCT  4147 22XX XXXX 9104   REV CREDIT CARD", ["4147 22XX XXXX 9104"], []),
    "short_prefix_mask": ("ACCT  51XXXXXXXXXX7712   PURCHASED BY COLLECTOR", ["7712"], []),
    "micr_c_a": ("  C021000021A 5530018842C 2207", ["021000021", "5530018842"], []),
    "bofd": ("[BOFD stamp:] PAY ANY BANK >021000021< FOR DEPOSIT", ["021000021"], []),
    "rt_label": ("merchant settlement (First Prairie Bank RT 021000021 acct ...4410)", ["021000021", "4410"], []),
    "cashtag": ("lawyer retainer pt 2,Marcus Ellery ($MarcusE2026)", ["$MarcusE2026"], []),
    "sign_in_as": ("To change, sign in as relleryjr_42 or call us.", ["relleryjr_42"], []),
    "processed_by": ("Processed: 10/14/2026 16:42 by mk.delacroix", ["mk.delacroix"], []),
    "ens": ('the ENS name "harborlight7.eth" resolves to that address', ["harborlight7.eth"], []),
    "ip_pin": ("If you have an Identity Protection PIN, enter it here (see inst.)  662014", ["662014"], []),
    "code_said": ("he asked for the code and I think it was 551208. Then he hung up.", ["551208"], []),
    "spelled_code": ("Six digits... five five one two oh eight.", ["five five one two oh eight"], []),
    "password_said": ("The password will be sent separately and is: Rq!2026-ab#7", ["Rq!2026-ab#7"], []),
    "pw_short": ("Harbor online - user rellery45  pw Tide&Moon1971", ["Tide&Moon1971"], []),
    "ind_name_no_colon": ("CO ID 1251187740 IND NAME ELLERY-BRANDT R", ["ELLERY-BRANDT R"], []),
    "bene_line": ("ACH DEBIT 529 COLLEGE SVGS CONTRIB\n         BENE M ELLERY\n", ["M ELLERY"], []),
    "in_re_marriage": ("RE:  In re the Marriage of Renata L. Ellery and Marcus J. Ellery", ["Renata L. Ellery",
                                                                                         "Marcus J. Ellery"], []),
    "minor_initials": ("Passenger R.E. (client's grandson, age 9) has a separate claim.", ["R.E."], []),
    "for_child": ("UTMA for Colette and Jasper; 529 for Theo", ["Colette", "Jasper", "Theo"], []),
    "employer_no_colon": ("Cafeteria manager         Employer Pine Ridge County Schools\n", ["Pine Ridge County Schools"], []),
    "group_employer": ("  Group:        HARBOR CITY TRANSIT AUTH  Group No. 0098214-A", ["HARBOR CITY TRANSIT AUTH"], []),
    "voe": ("Verification of Employment (Harbor Medical Center / Pine Outfitters)  $50.00",
            ["Harbor Medical Center", "Pine Outfitters"], []),
    "court_no": ("Court of Common Pleas of Harbor County, No. 2026-C-4418", ["2026-C-4418"], []),
    "gen_sess": ("Rutledge Co. Gen. Sess. No. 26-GS-1170", ["26-GS-1170"], []),
    "account_line": ("Installment     Harbor Financial Svcs       7020-5518-3361          $21,880", ["7020-5518-3361"], []),
    "clabe": ("CLABE: 012 180 99678 4917965", ["012 180 99678 4917965"], []),
    "ocr_state": ("  3318 SE CLINT0N ST APT 4\n  P0RTLAND 0R 97202-1544\n", ["P0RTLAND 0R 97202-1544"], []),
    "signature_slash": ("Spouse's signature  /s/ Renata L. Ellery   Date 03/02/2026", ["/s/ Renata L. Ellery"], []),
}

NEGATIVES_4 = [
    "ATM ID 4471 CARD WITHDRAWAL FEE WAIVED",
    "Loan Originator Organization NMLSR ID# 2210448   State License ID# L-188204",
    "Third Quarter 2026: July 1, 2026 - September 30, 2026",
    "Form 1099-NEC (Rev. 1-2024)   Copy B For Recipient",
    "slip-and-fall at Kroger #0447 in Murfreesboro",
    "Castellanos & Rourke operating -- fees",
]


@pytest.mark.parametrize("name", list(CASES_4))
def test_financial_values_redacted_4(rules, name):
    text, must, keep = CASES_4[name]
    sel = [s for s in rules(text, profile="financial", ocr_text=name.startswith("ocr")) if s.meta.get("selected", True)]
    missing = [v for v in must if not covers(sel, v, text)]
    assert not missing, (missing, [(s.entity, s.text) for s in sel])
    for v in keep:
        i = text.index(v)
        assert not any(s.start < i + len(v) and i < s.end for s in sel), (v, [(s.entity, s.text) for s in sel])


@pytest.mark.parametrize("text", NEGATIVES_4)
def test_financial_hard_negatives_4(rules, text):
    sel = [s for s in rules(text, profile="financial") if s.meta.get("selected", True)
           and s.entity in ("BANK_ACCOUNT", "ID_NUMBER", "CREDIT_CARD", "PERSON", "DRIVERS_LICENSE")]
    assert not sel, [(s.entity, s.text, s.source) for s in sel]


# ---- precision on financial records: words, columns and companies that are not personal data ---------------------
from obscura.detection.text import ner as _ner  # noqa: E402
from obscura.detection.text.base import Span as _Span  # noqa: E402


@pytest.fixture
def fake_ner(monkeypatch):
    """Rules plus canned NER output: ``run(text, [(value, "ner:gliner:person", 0.95), ...])``. Each value is found
    in the text and handed to the engine as if spaCy / GLiNER had reported it, so model-driven filters can be
    tested without loading the models."""
    from obscura.config import settings
    from obscura.detection.text.engine import AnalyzeOptions, TextAnalyzer

    monkeypatch.setattr(settings, "spacy_model", settings.spacy_model or "fake")
    monkeypatch.setattr(settings, "gliner_model", settings.gliner_model or "fake")
    ents = {"PERSON": "PERSON", "person": "PERSON", "street address": "ADDRESS", "employer": "EMPLOYER", "date of birth": "DATE_OF_BIRTH",
            "first name": "PERSON", "last name": "PERSON"}

    def run(text, found, **kw):
        out = []
        for value, source, score in found:
            i = text.index(value)
            out.append(_Span(i, i + len(value), ents[source.split(":")[-1]], score, source, value, "fake NER"))
        monkeypatch.setattr(_ner, "spacy_entities", lambda t: [s for s in out if "spacy" in s.source])
        monkeypatch.setattr(_ner, "gliner_entities", lambda t, labels=None: [s for s in out if "gliner" in s.source])
        kw.setdefault("include_suggestions", False)
        return TextAnalyzer().analyze(text, AnalyzeOptions(profile="financial", **kw))
    return run


def _sel(spans):
    return [s for s in spans if s.meta.get("selected", True)]


def _hits(spans, text, value, entities=None):
    i = text.index(value)
    return [(s.entity, s.text) for s in _sel(spans) if s.start < i + len(value) and i < s.end and
            (entities is None or s.entity in entities)]


# text, value that must stay visible, entity types it must not be redacted as
NOT_PERSONAL = {
    # transcript turns and notes after a speaker / role label are speech, not a name field
    "caller_turn": ("[00:01:12] AGENT: Can I help?\n[00:01:15] CALLER: Thank you. I lost my card.", "Thank", {"PERSON"}),
    "witness_turn": ("14        THE WITNESS: He also said the check bounced.", "He", {"PERSON"}),
    "operator_note": ("[operator: MICR misread on item 2 -- values corrected by hand]", "MICR", {"PERSON"}),
    "re_document": ("Re:   Subpoena Duces Tecum dated March 3, 2026", "Subpoena Duces Tecum", {"PERSON"}),
    "requested_by_agency": ("Requested by: VT Bureau of Consumer Protection", "VT Bureau", {"PERSON"}),
    "recipient_tin_label": ("Recipient:      DANA K MORROW-VEGA CUST  Recipient's TIN: XXX-XX-4471",
                            "Recipient's", {"PERSON"}),
    "dba_trade_name": ("Applicant: DARNELL T OKAFOR  DBA OKAFOR LAWN CARE\nApplicant TIN: 85-1234567",
                       "LAWN CARE", {"PERSON"}),
    # table headings and form titles
    "principal_interest": ("Date        Amount   Principal  Interest    Fees     Balance\n"
                           "03/01/2026  609.16   510.37     98.79       0.00     15,025.29", "Interest", {"PERSON"}),
    "official_form": (" Debtor 2           Ben          Lee\n (Spouse, if filing) First Name  Last Name\n"
                      " United States Bankruptcy Court for the: District of Vermont\n Case number  2:26-bk-00118\n\n"
                      "Official Form 106A/B\n", "Official Form", {"PERSON"}),
    "defined_term": ('Business Legal Name ("Borrower")            DBA or Tradename', "Borrower", {"PERSON"}),
    # a column of CPT codes beside a claim-number column
    "cpt_column": (" Claim No.        DOS        Provider              CPT     Billed\n"
                   " ---------        --------   ---------------       -----   ------\n"
                   " 26101Q00417      02/14/26   Harbor Imaging        72125   812.00", "72125", {"CLAIM_NUMBER"}),
    # organisations' identifiers
    "payer_id": ("Harbor Health Plan  Commercial PPO     Payer ID 61190", "61190", {"ID_NUMBER"}),
    "lender_location_id": ("Lender: Pine Valley Bank   SBA Lender Location ID: 512204", "512204", {"ID_NUMBER"}),
    "licensed_by": ("PINE VALLEY AUTO FINANCE, LLC is licensed by the Vermont Department of Financial Regulation, "
                    "license no. 2200417-09.", "2200417-09", {"ID_NUMBER", "DRIVERS_LICENSE"}),
    # card-statement venues and financial vocabulary
    "statement_venue": ("09/18  09/19    SQ *ROSIES NAIL STUDIO Burlington VT      $64.00", "ROSIES NAIL STUDIO",
                        {"INDIRECT_LOCATION"}),
    "merchant_brand": ("09/05  POS DEBIT SHEETZ 0412 ALTOONA PA CARD 5106              41.20", "SHEETZ",
                       {"INDIRECT_LOCATION"}),
    "price_market_header": ("Symbol  CUSIP         Quantity     Price    Market Value     Cost Basis", "Market",
                            {"INDIRECT_LOCATION"}),
    "money_market": ("Money Market          Harbor Online Savings         $ 12,880.12", "Money Market",
                     {"INDIRECT_LOCATION"}),
    "bond_fund": ("VANGUARD TOTAL BOND MARKET ETF   BND     921937835", "BOND MARKET", {"INDIRECT_LOCATION"}),
    "ocr_notary": ("    | WALTER P. GRIMM, Notary Pub1ic                 |", "Pub1ic", {"INDIRECT_LOCATION"}),
    "business_suite": ("Bill to: Northgate Family Dental, PLLC  Lakeview Dental, Ste 310   Invoice Date 09/30/2026",
                       "Ste 310", {"INDIRECT_LOCATION"}),
    # address shapes that are not addresses
    "credit_grid": ("04/2010  06/2016    95,000        0       0   I1  PAID/CLOSED - MORTGAGE", "0   I1", {"ADDRESS"}),
    "real_estate_line": (" 04  Real Estate Commission (B) Summit Realty               $  560.00", "Real Estate",
                         {"ADDRESS"}),
    "us_reports": ("See Sereboff v. Mid Atlantic Medical Services, Inc., 547 U.S. 356 (2006).", "547 U.S. 356",
                   {"ADDRESS"}),
    # dates that are not birth dates
    "born_before": ("Age/Blindness   You: [ ] Were born before January 2, 1961  [ ] Are blind", "January 2, 1961",
                    {"DATE_OF_BIRTH"}),
    "as_of_date": ("  Rosa Lind -- DOB 02/17/2016 (9 at 12/31/25), 4th grade", "12/31/25", {"DATE_OF_BIRTH"}),
    "zero_amount": ("  6 Foreign tax paid  $ 0.00", "$ 0.00", {"FINANCIAL_INFO"}),
}


@pytest.mark.parametrize("name", list(NOT_PERSONAL))
def test_financial_not_personal(rules, name):
    text, value, entities = NOT_PERSONAL[name]
    spans = rules(text, profile="financial")
    assert not _hits(spans, text, value, entities), _hits(spans, text, value)


# the fixes above must not cost these
STILL_FOUND = {
    "caller_name_field": ("Caller: Maria Gonzalez   Callback: (802) 555-0148", "Maria Gonzalez"),
    "recipient_name": ("Recipient:      DANA K MORROW-VEGA CUST  Recipient's TIN: XXX-XX-4471", "DANA K MORROW-VEGA"),
    "dba_owner": ("Applicant: DARNELL T OKAFOR  DBA OKAFOR LAWN CARE\nApplicant TIN: 85-1234567", "DARNELL T OKAFOR"),
    "claim_column": (" Claim No.        DOS        Provider              CPT     Billed\n"
                     " ---------        --------   ---------------       -----   ------\n"
                     " 26101Q00417      02/14/26   Harbor Imaging        72125   812.00", "26101Q00417"),
    "employee_id": ("Employee name: Rosa Lind          Employee ID: HBR-118044", "HBR-118044"),
    "dob_first": ("  Rosa Lind -- DOB 02/17/2016 (9 at 12/31/25), 4th grade", "02/17/2016"),
    "apartment": ("Mailing address: 14 Elm St Apt 4B, Burlington VT 05401", "14 Elm St Apt 4B"),
}


@pytest.mark.parametrize("name", list(STILL_FOUND))
def test_financial_still_found(rules, name):
    text, value = STILL_FOUND[name]
    sel = _sel(rules(text, profile="financial"))
    assert covers(sel, value, text), [(s.entity, s.text) for s in sel]


def test_two_mailing_blocks_side_by_side(rules):
    text = ("  MARCUS T ELLERY                         Co-Borrower\n"
            "  2614 CEDAR RIDGE TRL\n  ROUND ROCK TX 78681\n")
    spans = rules(text, profile="financial")
    assert covers(_sel(spans), "MARCUS T ELLERY", text)
    assert not _hits(spans, text, "Co-Borrower", {"PERSON"})


def test_payroll_register_sequence_number_is_a_suggestion(rules):
    text = "TERMINATION  Emp 1032  HALVORSEN, BAO T   Last day worked 10/09/2026"
    spans = rules(text, profile="financial", include_suggestions=True)
    emp = [s for s in spans if s.text == "1032"]
    assert emp and not any(s.meta.get("selected") for s in emp)
    assert covers(_sel(spans), "HALVORSEN, BAO T", text)


def test_role_word_not_pulled_into_a_name(rules):
    text = ("Primary beneficiary: Nora L. Ross\n"
            "  Contingent NORA L ROSS (minor)               Granddaughter\n")
    sel = _sel(rules(text, profile="financial"))
    assert covers(sel, "NORA L ROSS", text)
    i = text.index("Contingent")
    assert not any(s.start <= i < s.end for s in sel), [(s.entity, s.text) for s in sel]


NER_NOT_PERSONAL = {
    # job titles that GLiNER reads as people
    "shop_foreman": ("      Shop Foreman                         DD CHK ****6610", [("Shop Foreman", "ner:gliner:person", 0.94)]),
    "owner_president": ("      Owner/President (officer wages)", [("Owner/President", "ner:gliner:person", 0.8)]),
    "cut_off_title": ("Position or Title  Senior Data Engineer, Claims Systems",
                      [("Senior Data", "ner:gliner:person", 0.96)]),
    "title_over_break": ("Darnell P. Whitfield, CSRP\nSenior Recovery Specialist, ext. 4417",
                         [("CSRP\nSenior Recovery Specialist", "ner:gliner:person", 0.64)]),
    "spouse_occupation": ("Spouse's occupation  DRONE SURVEYOR", [("DRONE", "ner:gliner:person", 0.97)]),
    "branch_mgr": ('Note by P. Hess, Branch Mgr: "customer states divorce pending"',
                   [("Branch Mgr", "ner:gliner:person", 0.98)]),
    # places and businesses
    "city_state": ("08/18/2026 06:05  PHOENIX AZ    Arrived at delivery facility", [("PHOENIX AZ", "ner:spacy:PERSON", 0.96)]),
    "trade_name": ("Principal business: ABERNATHY MOBILE DETAILING", [("ABERNATHY MOBILE DETAILING", "ner:spacy:PERSON", 0.95)]),
    "possessive_store": ("09/13  09/15    LOU MALNATI'S #19 NAPERVILLE IL        $48.10",
                         [("LOU MALNATI", "ner:gliner:first name", 0.99)]),
    "company_alone": ("Lienholder: Ridgeline Auto Finance, LLC\nYou must keep collision coverage naming Ridgeline as loss "
                      "payee.", [("Ridgeline", "ner:gliner:first name", 0.93)]),
    "case_style_company": ("Gateway Arch Recovery Services, LLC is a debt collector. See Abernethy v. Gateway Arch, "
                           "E.D. Mo. No. 4:26-cv-01188.", []),
}


@pytest.mark.parametrize("name", list(NER_NOT_PERSONAL))
def test_ner_people_that_are_not_people(fake_ner, name):
    text, found = NER_NOT_PERSONAL[name]
    spans = fake_ner(text, found)
    values = [v for v, _, _ in found] or ["Gateway Arch, E.D."[:12]]
    for v in values:
        hit = _hits(spans, text, v if v in text else "Gateway Arch", {"PERSON", "MINOR"})
        assert not hit, hit


def test_firm_named_after_a_person(fake_ner):
    text = ("Husband: Garrett M. Hollis. Corporate records for Hollis Comfort Air, Inc. were subpoenaed.\n"
            "Mr. Hollis signed every check; Hollis Comfort Air's 2025 return deducted them.")
    spans = fake_ner(text, [("Garrett M. Hollis", "ner:spacy:PERSON", 0.97)])
    sel = _sel(spans)
    assert covers(sel, "Garrett M. Hollis", text)
    i = text.index("Mr. Hollis") + 4
    assert any(s.entity == "PERSON" and s.start <= i < s.end for s in sel)  # the man is still redacted
    j = text.index("Hollis Comfort Air's")
    assert not any(s.entity == "PERSON" and s.start <= j < s.end for s in sel)  # the company is not


def test_ocr_form_label_is_not_an_employer(fake_ner):
    text = "f Ernployee's address and ZIP code\n   14 Elm St, Burlington VT 05401"
    spans = fake_ner(text, [("Ernployee", "ner:gliner:employer", 0.77)])
    assert not _hits(spans, text, "Ernployee", {"EMPLOYER"})


@pytest.mark.parametrize("text,value", [
    ("Next interest payment 12/31/2099. Moody's: N/A.", "12/31/2099"),
    ("certify that the Applicant was in operation on February 15, 2020, and has not closed", "February 15, 2020"),
])
def test_ner_dates_that_are_not_birth_dates(fake_ner, text, value):
    spans = fake_ner(text, [(value, "ner:gliner:date of birth", 0.97)])
    assert not _hits(spans, text, value, {"DATE_OF_BIRTH"})


def test_store_numbers_from_ner(fake_ner):
    text = ("Debtor slipped at Kroger #0447 in Murfreesboro.\n"
            "09/21  09/22    SPEEDWAY 4417 NAPERVILLE IL                $23.86\n"
            "02/14/2025  A-1 card ...8826  Swann Ave Jewelers -- engraving")
    spans = fake_ner(text, [("Kroger #0447", "ner:gliner:street address", 0.98),
                            ("SPEEDWAY 4417", "ner:gliner:street address", 0.97),
                            ("8826  Swann Ave", "ner:gliner:street address", 0.85)])
    assert not _hits(spans, text, "Kroger #0447", {"ADDRESS"})
    assert not _hits(spans, text, "SPEEDWAY 4417", {"ADDRESS", "INDIRECT_LOCATION"})
    assert not _hits(spans, text, "Swann Ave", {"ADDRESS"})


def test_european_street_from_ner_is_kept(fake_ner):
    text = "  HILDEGARD BAUMGARTNER\n  LINDENSTRASSE 14\n  79098 FREIBURG IM BREISGAU\n  GERMANY"
    spans = fake_ner(text, [("LINDENSTRASSE 14", "ner:gliner:street address", 0.97)])
    assert covers(_sel(spans), "LINDENSTRASSE 14", text)


NOT_PERSONAL_2 = {
    "gl_account_column": ("DEPARTMENT SUMMARY          HEADCOUNT        GROSS             NET          GL ACCOUNT\n"
                          "  10 OFFICE                       2      7,615.38        5,978.26        6010-20\n",
                          "6010-20", {"BANK_ACCOUNT"}),
    "item_log_sequence": (" Seq#      Posted      Acct           Item          Amount\n"
                          " -------   ---------   ------------   -----------   ---------\n"
                          ' 77120334  04/01/26    ...5521        Ck 1188       4,200.00   "deposit only acct 7800 3364 12"\n',
                          "77120334", {"BANK_ACCOUNT"}),
    "subscriber_code": ("  LAKESHORE AUTO CREDIT CORP   SUB CODE 8812-0447   LOAN # LAC-2026-118804", "8812-0447",
                        {"BANK_ACCOUNT"}),
    "bank_in_parens": ("Deposit to      acct ending 4418 (Harbor Community Bank)", "Harbor Community Bank", {"PERSON"}),
    "cashtag_label": ("Account holder: JORDAN WELLS    $Cashtag: $JWellsTile    Profile", "$Cashtag", {"USERNAME"}),
    "password_ends_sentence": ("We will never ask for your online banking password.\n  Credit reporting: we report to "
                               "all three bureaus.", "Credit", {"PASSWORD"}),
    "user_id_ends_sentence": ("We reset your user ID. Your old user ID was retired.", "Your", {"USERNAME"}),
    "ocr_will": ("The CD is encrypted. The password wi11 be sent under separate cover.", "wi11", {"PASSWORD"}),
    "ocr_for": ("    PIN f0r ATM card - see the envelope", "f0r", {"PASSWORD"}),
    "pin_set_flag": ("Telephone banking PIN set: Y  (PIN not displayed)", "set", {"PASSWORD"}),
    "deposit_not_deputy": ("    08/01  $1,200.00  MOBILE DEP CHK #2041 AKINOLA, FOLAKE", "2041", {"LAW_ENFORCEMENT_ID"}),
    "grant_not_school": ("  Washington College Grant (WCG)             $2,500", "Washington College", {"SCHOOL"}),
    "crypto_amounts": ("2026-07-21 22:05:16 MST,Bitcoin Withdrawal,BTC,-0.01300000,-0.00002100,-0.01302100,BTC",
                       "-0.01300000,-0.00002100", {"GPS"}),
    "ocr_same_as": ("Signer 2:  Dana L. Kowalczyk\nAddress:   sarne as Signer 1\nPhone:     (484) 555-0199",
                    "sarne as Signer 1", {"ADDRESS"}),
}


@pytest.mark.parametrize("name", list(NOT_PERSONAL_2))
def test_financial_not_personal_2(rules, name):
    text, value, entities = NOT_PERSONAL_2[name]
    spans = rules(text, profile="financial", ocr_text=name.startswith("ocr"))
    assert not _hits(spans, text, value, entities), _hits(spans, text, value)


STILL_FOUND_2 = {
    "cashtag_value": ("Account holder: JORDAN WELLS    $Cashtag: $JWellsTile    Profile", "$JWellsTile"),
    "user_id_dot_leaders": ("User ID ................. 2384710945716224811\nLegal name on file ...... JORDAN WELLS",
                            "2384710945716224811"),
    "username_in_row": ("  StudentAid.gov account  username RosaL2008   (FSA ID)\n  State of legal residence VT, since "
                        "06/2012", "RosaL2008"),
    "deputy_badge": ("Assisting: Deputy Ruiz #4412 took the report.", "4412"),
    "school_attended": ("She is a sophomore at Lilac City College and lives on campus.", "Lilac City College"),
    "password_value": ("The password will be sent separately and is: Rq!2026-ab#7", "Rq!2026-ab#7"),
}


@pytest.mark.parametrize("name", list(STILL_FOUND_2))
def test_financial_still_found_2(rules, name):
    text, value = STILL_FOUND_2[name]
    sel = _sel(rules(text, profile="financial"))
    assert covers(sel, value, text), [(s.entity, s.text) for s in sel]


def test_words_under_a_username_heading_are_not_usernames(rules):
    text = ("  Applicant  StudentAid.gov username   (FSA ID)\n"
            "  State of legal residence VT, since 06/2012\n")
    spans = rules(text, profile="financial")
    assert not _hits(spans, text, "since", {"USERNAME"}) and not _hits(spans, text, "legal", {"USERNAME"})


@pytest.mark.parametrize("text,found,value,entities", [
    ("Spouse's occupation  DRONE SURVEYOR", [("DRONE SURVEYOR", "ner:gliner:person", 0.94)], "DRONE", {"PERSON"}),
    ("Su cuenta termina en 7965. Necesito el dinero.", [("Necesito el", "ner:spacy:PERSON", 0.92)], "Necesito",
     {"PERSON"}),
    ("You: [ ] Were born before January 2, 1961  [ ] Are blind", [("January 2, 1961", "ner:gliner:date of birth", 0.99)],
     "January 2, 1961", {"DATE_OF_BIRTH"}),
    ("HAWK/FACS+: SSN ISSUED 1995-1996, STATE: PR.", [("1995-1996", "ner:gliner:date of birth", 0.85)], "1995-1996",
     {"DATE_OF_BIRTH"}),
])
def test_ner_findings_rejected(fake_ner, text, found, value, entities):
    assert not _hits(fake_ner(text, found), text, value, entities)


def test_ocr_birth_date_from_ner_is_kept(fake_ner):
    text = "Name:  Joaquin E. Barela          D0B:  1l/03/1992          SSN:  5O8-44-l297"
    spans = fake_ner(text, [("1l/03/1992", "ner:gliner:date of birth", 0.9)], ocr_text=True)
    assert covers(_sel(spans), "1l/03/1992", text)


def test_re_line_name_before_lower_case_word_is_kept(rules):
    text = "Re:   Kevin Tran account ending 4417 -- dispute of 09/14 charge"
    assert covers(_sel(rules(text, profile="financial")), "Kevin Tran", text)


def test_owner_named_in_business_name_is_kept(fake_ner):
    text = "John Smith Plumbing, LLC (owner John Smith) deposited the check; John Smith signed it."
    spans = fake_ner(text, [("John Smith", "ner:spacy:PERSON", 0.9)])
    i = text.index("owner John Smith") + 6
    assert any(s.entity == "PERSON" and s.start <= i < s.end for s in _sel(spans))


def test_county_is_not_a_company(fake_ner):
    text = "Judge Mary Ellen Tobin of Travis Co. signed the order; Tobin later recused."
    spans = fake_ner(text, [("Mary Ellen Tobin", "ner:spacy:PERSON", 0.95)])
    assert covers(_sel(spans), "Mary Ellen Tobin", text)
