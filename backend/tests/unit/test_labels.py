"""Form labels, tables, key/value fields and deposition Q&A."""
import pytest

from tests.conftest import found


def ents(spans, entity):
    return [s.text for s in spans if s.entity == entity]


LABELLED = [
    ("MRN", "MRN: 00483921", "00483921"), ("MRN", "Medical Record #: E123456789", "E123456789"),
    ("MRN", "Chart #: MR3566087", "MR3566087"), ("MRN", "Patient ID: 4839-221", "4839-221"),
    ("MRN", "Encounter #: 99887766", "99887766"), ("MRN", "Patient Account No. 7781229", "7781229"),
    ("BANK_ACCOUNT", "Acct# 488542540", "488542540"), ("MRN", "FIN #: 30019922", "30019922"),
    ("HEALTH_PLAN_ID", "Member ID: XWH203428225", "XWH203428225"), ("HEALTH_PLAN_ID", "Group #: 620801", "620801"),
    ("HEALTH_PLAN_ID", "Subscriber ID: W640644385", "W640644385"), ("HEALTH_PLAN_ID", "Medicaid #: 517782341", "517782341"),
    ("HEALTH_PLAN_ID", "(Member W640644385)", "W640644385"), ("HEALTH_PLAN_ID", "Insured's I.D. Number: AB1234567", "AB1234567"),
    ("CLAIM_NUMBER", "Claim #: CLM-2023-0048392", "CLM-2023-0048392"), ("CLAIM_NUMBER", "Claim No. 0398-22-1187", "0398-22-1187"),
    ("CLAIM_NUMBER", "Claim Ref: LA-4839201-01", "LA-4839201-01"), ("CLAIM_NUMBER", "claim number 2023WC448210", "2023WC448210"),
    ("POLICY_NUMBER", "Policy No.: TX-AUTO-4839201", "TX-AUTO-4839201"), ("POLICY_NUMBER", "Policy #: PAP 0045821930", "PAP 0045821930"),
    ("POLICY_NUMBER", "Fin. Resp. Policy #: 5194446-51", "5194446-51"),
    ("CASE_NUMBER", "Cause No. D-1-GN-23-004521", "D-1-GN-23-004521"), ("CASE_NUMBER", "Case Number: 2023-CA-004821", "2023-CA-004821"),
    ("LAW_ENFORCEMENT_ID", "Badge #: 4412", "4412"), ("LAW_ENFORCEMENT_ID", "Booking No. 23-001877", "23-001877"),
    ("LAW_ENFORCEMENT_ID", "Incident #: APD-2023-004582", "APD-2023-004582"), ("LAW_ENFORCEMENT_ID", "Crash ID: 19384756", "19384756"),
    ("LAW_ENFORCEMENT_ID", "Citation # C48392011", "C48392011"),
    ("DRIVERS_LICENSE", "DL#: 48392011", "48392011"), ("DRIVERS_LICENSE", "Driver's License No. S530-123-45-678-0", "S530-123-45-678-0"),
    ("DRIVERS_LICENSE", "DL/ID #: B96645068", "B96645068"), ("DRIVERS_LICENSE", "OLN: Y95367994", "Y95367994"),
    ("PASSPORT", "Passport No. 548392011", "548392011"), ("PASSPORT", "passport number C03005988", "C03005988"),
    ("LICENSE_PLATE", "License Plate #: R452XBG", "R452XBG"), ("LICENSE_PLATE", "Plate: TX KLM-4821", "TX KLM-4821"),
    ("LICENSE_PLATE", "Tag No. ABC 1234", "ABC 1234"), ("LICENSE_PLATE", "(plate WG2-F805)", "WG2-F805"),
    ("BANK_ACCOUNT", "Account No.: 483920117", "483920117"), ("BANK_ACCOUNT", "Checking Acct # 0047-7711-22", "0047-7711-22"),
    ("BANK_ACCOUNT", "account ending 0859", "0859"), ("BANK_ACCOUNT", "Trust account (IOLTA) #: 4839201177", "4839201177"),
    ("ROUTING_NUMBER", "ABA Routing: 021000021", "021000021"), ("ROUTING_NUMBER", "Routing # 026009593", "026009593"),
    ("PHONE", "Cell: 5125550187", "5125550187"), ("PHONE", "Fax: 512.555.0144", "512.555.0144"),
    ("PASSWORD", "Password: Welcome123!", "Welcome123!"), ("PASSWORD", "PIN: 4821", "4821"),
    ("USERNAME", "Username: jdoe_1985", "jdoe_1985"), ("USERNAME", "Instagram: @jdoe85", "@jdoe85"),
    ("DEVICE_ID", "Serial No.: C02XG3JHJGH5", "C02XG3JHJGH5"), ("NATIONAL_ID", "A-Number: A123456789", "A123456789"),
    ("ID_NUMBER", "Employee ID: E764349", "E764349"), ("ID_NUMBER", "State Bar No. 24039988", "24039988"),
    ("ID_NUMBER", "PT, DPT   License #: 8874", "8874"), ("ID_NUMBER", "Student ID: 20194477", "20194477"),
    ("ZIP_CODE", "Zip: 78745", "78745"), ("CVV", "Security code: 482", "482"),
    ("SSN", "taxpayer id 523-71-9921", "523-71-9921"), ("NPI", "NPI: 1245319599", "1245319599"),
]


@pytest.mark.parametrize("entity,text,value", LABELLED)
def test_label_value(rules, entity, text, value):
    spans = rules(text, profile="strict")
    assert any(s.text == value for s in spans), (entity, found(spans))


@pytest.mark.parametrize("entity,text,value", LABELLED)
def test_label_value_typed(rules, entity, text, value):
    spans = rules(text, profile="strict")
    assert any(s.text == value and s.entity == entity for s in spans) or \
        any(s.text == value and entity in s.meta.get("alt_entities", []) for s in spans), (entity, found(spans))


def test_two_labels_one_line(rules):
    spans = rules("Claim #: A1-99887   Policy #: B2-55443", profile="strict")
    assert ents(spans, "CLAIM_NUMBER") == ["A1-99887"] and ents(spans, "POLICY_NUMBER") == ["B2-55443"]


def test_table_header(rules):
    text = "Claim Number      Policy Number      Member ID\nCLM-4839201       POL-77182          XWH1234567\n"
    spans = rules(text, profile="strict")
    for v in ("CLM-4839201", "POL-77182", "XWH1234567"):
        assert any(s.text == v for s in spans), (v, found(spans))


@pytest.mark.parametrize("q,a,entity,value", [
    ("What is your driver's license number?", "It's B96645068.", "DRIVERS_LICENSE", "B96645068"),
    ("And the plate on your vehicle?", "LXR-4521. It's a truck.", "LICENSE_PLATE", "LXR-4521"),
    ("What is your phone number?", "512-555-0187.", "PHONE", "512-555-0187"),
    ("Who was your supervisor?", "Donna Smith.", "PERSON", "Donna Smith"),
    ("Please state your full name for the record.", "Richard Brett Santiago", "PERSON", "Richard Brett Santiago"),
    ("Who is your counselor?", "Tiffany Rodriguez-Smith.", "PERSON", "Tiffany Rodriguez-Smith"),
])
def test_deposition_qa(rules, q, a, entity, value):
    text = f"12   Q.  {q}\n13   A.  {a}\n14   Q.  Okay."
    spans = rules(text, profile="strict")
    assert any(s.text == value for s in spans), found(spans)


def test_qa_names_list(rules):
    text = "3   Q.  What are your children's names and ages?\n4   A.  Carol is 6, Courtney is 13, Meghan is 13."
    vals = {s.text for s in rules(text)}
    assert {"Carol", "Courtney", "Meghan"} <= vals


def test_qa_across_page_break(rules):
    text = "25   Q.  What are your children's names and ages?\n\n\f   Page 5\n 1   A.  Laurent is 10, Leticia is 1."
    vals = {s.text for s in rules(text)}
    assert {"Laurent", "Leticia"} <= vals


PEOPLE_FIELDS = [
    "Patient: JOHNSON, MARY A", "Patient Name: Mary A. Johnson", "Client: Julie Brooks", "Insured: Kevin O'Brien",
    "Plaintiff: Grace Hill", "Defendant: Mauricio Rodríquez", "Witness: Robert White", "Emergency Contact: Victor Hernandez",
    "Guardian: Hope Church", "Driver Name (Last, First, Middle): NAVARRO, TRINIDAD E", "Owner/Lessee: Trinidad Navarro",
    "Unit 2, Seat 11 (driver): Richard Santiago", "Completed by: Donna Smith", "Intake by: Darika Krishnan",
    "ALSO PRESENT: Jacob Carlson", "Other names used: Julie Rosales", "Attending Physician: Dr. Will Hunter",
    "Signed: Noémi Valette", "Subscriber: Erica Hernandez", "Your Insured: Paris Hilton", "Our Client: Sunny Day",
    "Electronically signed by: Priya Venkataraman", "Next of Kin: Oluwaseun Adeyemi", "Adjuster: Keith Rhodes",
    "Investigating Officer: Daniel Ruiz", "Account Holder: Ji-woo Park", "Interpreter: Nguyen Thi Lan",
]


@pytest.mark.parametrize("text", PEOPLE_FIELDS)
def test_kv_people(rules, text):
    name = text.split(":", 1)[1].strip().replace("Dr. ", "")
    spans = rules(text)
    assert any(s.entity == "PERSON" and s.text == name for s in spans), found(spans)


@pytest.mark.parametrize("text", ["Patient: N/A", "Relationship: Self", "Name: Unknown", "Spouse: None", "Guardian: Parent",
                                  "Patient: see above", "Client: Insured", "Re: Your Insured"])
def test_kv_people_placeholders(rules, text):
    assert not [s for s in rules(text) if s.entity == "PERSON"], found(rules(text))


@pytest.mark.parametrize("text,val", [
    ("Employer: QuikTrip Corporation Occupation: forklift operator", "QuikTrip Corporation"),
    ("Subscriber: Erica Hernandez Relationship: Self", "Erica Hernandez"),
    ("Address: 11900 N Elm Ave Unit 171 Home Phone: (206)790-9593", "11900 N Elm Ave Unit 171"),
])
def test_ocr_collapsed_fields_stop_at_next_label(rules, text, val):
    assert val in [s.text for s in rules(text)], found(rules(text))


@pytest.mark.parametrize("text", ["Address: 4417 Oakridge Dr, Apt 3B\nAustin, TX 78745", "Home Address: PO Box 4471, Tulsa, OK 74103",
                                  "Residence: 99 W. 5th St., Ste 200", "Mailing Address:\n1600 Pennsylvania Ave NW"])
def test_kv_address(rules, text):
    assert [s for s in rules(text) if s.entity == "ADDRESS"], found(rules(text))


@pytest.mark.parametrize("text", ["Claim #: N/A", "Policy #: pending", "Member ID: see card", "MRN: ________", "DL#: none",
                                  "Policy Limits: $25,000", "Claim Status: Open", "Account Type: Checking"])
def test_label_placeholders_ignored(rules, text):
    spans = [s for s in rules(text, profile="strict") if s.entity not in ("MONEY",)]
    assert not spans, found(spans)


def test_firm_file_numbers_are_suggestions(rules):
    from obscura.detection.text.engine import AnalyzeOptions, TextAnalyzer
    out = TextAnalyzer().analyze("Our File No.: 25-0318-PI", AnalyzeOptions(use_spacy=False, use_gliner=False,
                                                                          include_suggestions=True))
    f = [s for s in out if s.text == "25-0318-PI"]
    assert f and not f[0].meta["selected"]


@pytest.mark.parametrize("text", ["volar locking plate. EBL 50 mL", "Plt 238", "Removal of volar plate   20680",
                                  "Firm Reg. No. 1188"])
def test_medical_plate_words_not_plates(rules, text):
    assert not [s for s in rules(text) if s.entity == "LICENSE_PLATE"], found(rules(text))
