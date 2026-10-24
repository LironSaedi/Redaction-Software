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
