"""Rules added from the independent held-out review: OCR clean-up, transcripts, wrapped labels, name columns,
location phrases, and the public-name / form-vocabulary negatives that keep precision up."""
import re

import pytest

from obscura.detection.text.base import NormText, blank_line_numbers, ocr_clean_variant, ocr_digit_variant
from obscura.detection.text.engine import TextAnalyzer
from obscura.detection.text.entities import entities_for_profile
from obscura.detection.text.negatives import is_not_a_person
from tests.conftest import covers, found


# ---- OCR clean-up ----------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,clean", [
    ("(cell) 2l0-455-09l2", "(cell) 210-455-0912"),
    ("Banking 1-8OO-3l8-2245 *", "Banking 1-800-318-2245 *"),
    ("Account Number:   884l-OO2-3318", "Account Number:   8841-002-3318"),
    ("45l2 AVENUE F", "4512 AVENUE F"),
    ("T0 CHK ...O47l", "T0 CHK ...0471"),
    ("P.0. Box 2O418", "P.0. Box 20418"),
    ("Statement Period: O4/Ol/2O25 - O4/3O/2O25", "Statement Period: 04/01/2025 - 04/30/2025"),
    ("AUSTlN TX 7875l-23O4", "AUSTIN TX 78751-2304"),
    ("CAPITAL HlLL BUSlNESS CHECKlNG", "CAPITAL HILL BUSINESS CHECKING"),
    ("LAKESH0RE GEN lNS CLAlM PMT LG25Ol223O4l8", "LAKESHORE GEN INS CLAIM PMT LG25012230418"),
    ("My name is R0salind Thi Pham", "My name is Rosalind Thi Pham"),
    ("a 1itt1e gir1 Li1y wh0 is 3", "a little girl Lily who is 3"),
    ("Witness: M. D0y1e #3390", "Witness: M. Doyle #3390"),
    ("by Det. Vi11al0b0s", "by Det. Villalobos"),
    ("her d00r\n1ock", "her door\nlock"),
    ("SE0UL F00D ATX LLC", "SEOUL FOOD ATX LLC"),
    ("HYUN W00 PARK", "HYUN WOO PARK"),
    ("the wa11 and my ce11", "the wall and my cell"),
    ("Apt l2C, Pinecrest", "Apt 12C, Pinecrest"),
    ("My S5N / DL# is TX 0l99 4527", "My SSN / DL# is TX 0199 4527"),
    ("He drives a big gray F0rd truck 0n Main", "He drives a big gray Ford truck on Main"),
])
def test_ocr_clean_variant(raw, clean):
    out = ocr_clean_variant(raw)
    assert out == clean
    assert len(out) == len(raw)


@pytest.mark.parametrize("code", ["B12", "COVID19", "A04418277", "SFD-0117", "HCE884410217-02", "bluejay55",
                                  "thuyle0109", "G6PD", "4th", "10mg", "XOD884417203", "SRC1912345678",
                                  "AQRPR4417K", "W1", "V1", "S1", "K9", "M1"])
def test_ocr_clean_keeps_real_codes(code):
    text = f"value {code} here"
    assert ocr_clean_variant(text) == text


@pytest.mark.parametrize("text", ["HCE884410217-02 bluejay55", "A04418277 SFD-0117", "XOD884417203 SRC1912345678"])
def test_numeric_runs_do_not_swallow_neighbouring_words(text):
    assert ocr_digit_variant(text) == text


# ---- transcripts -----------------------------------------------------------------------------------

def _depo(lines):
    return "\n".join(f"{i:2d}        {ln}" for i, ln in enumerate(lines, 1)) + "\n"


def test_blank_line_numbers_on_transcripts():
    text = _depo(["Q.   Before Swiftline, where did you work?", "A.   I drove for Caliche Transport out of San",
                  "Marcos and then I started", "at Swiftline in August of '21.", "Q.   Why?", "A.   Money.",
                  "Q.   And then?", "A.   Nothing.", "Q.   Okay.", "A.   Okay."])
    out = blank_line_numbers(text)
    assert len(out) == len(text)
    assert re.search(r"started\n +at Swiftline", out) and not re.search(r"(?m)^ *\d", out)


@pytest.mark.parametrize("text", [
    "1   Office visit   $250\n2   X-ray   $90\n",                 # short numbered table
    "Items:\n1  apples\n3  pears\n7  plums\n2  figs\n9  kiwis\n4  dates\n8  limes\n6  nuts\n",  # not sequential
    "Plain prose without any line numbers at all.\n" * 10,
])
def test_blank_line_numbers_leaves_other_documents(text):
    assert blank_line_numbers(text) == text


def test_wrapped_transcript_phrase_finds_employer(rules):
    text = _depo(["Q.   Where did you work?", "A.   Hill Country Aggregates, two years. I started",
                  "at Swiftline in August of '21.", "Q.   Did Swiftline discipline you?", "A.   No.",
                  "Q.   Okay.", "A.   Okay.", "Q.   Okay.", "A.   Okay."])
    spans = rules(text)
    assert sum(1 for s in spans if s.entity == "EMPLOYER" and s.text == "Swiftline") >= 2


# ---- names ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,name", [
    ('  Name: PHAM, ROSALIND ("ROZ")          DOB: 04/30/1961', "ROZ"),
    ("HP:   First name H-Y-U-N, hyphen, W-O-O. Last name P-A-R-K.", "P-A-R-K"),
    ("HP:   First name H-Y-U-N, hyphen, W-O-O. Last name P-A-R-K.", "H-Y-U-N, hyphen, W-O-O"),
    ("C:   Rosalind Pham. P-H-A-M.", "P-H-A-M"),
    ("later identified as V1 Grace Hill, sitting on the floor", "Grace Hill"),
    ("Form 1040 (2024) -- PARK, HYUN WOO & JI EUN -- SSN", "PARK, HYUN WOO & JI EUN"),
    ("                   )\n 6   D'ANDRE WASHINGTON,            )\n 7        Defendant.               )\n",
     "D'ANDRE WASHINGTON"),
    ("60  Dr. da Rocha DEA FD1034696\n", "da Rocha"),
    ("signed by Dr. de la Cruz today", "de la Cruz"),
    ("Patient: O'BRIEN, SEAN\n", "O'BRIEN, SEAN"),
])
def test_names(rules, text, name):
    assert covers(rules(text), name, text), found(rules(text))


def test_spelled_name_propagates(rules):
    text = "Last name P-A-R-K, spelled out. Later Mr. Park said PARK was right."
    assert sum(1 for s in rules(text) if s.entity == "PERSON" and s.text.lower() == "park") >= 2


@pytest.mark.parametrize("text", ["The F-B-I and the I-R-S were called.", "Grade: A-B-C"])
def test_spelled_letters_need_a_name_cue(rules, text):
    assert not [s for s in rules(text) if s.entity == "PERSON"]


TAX = """Your first name and middle initial       Last name                 Your social security number
HYUN WOO                                 PARK                      584 31 0927
If joint return, spouse's first name     Last name                 Spouse's social security number
JI EUN                                   PARK                      590 27 4416
Home address (number and street)                                    Apt. no.
4512 AVENUE F

Dependents (see instructions):
  (1) First name   Last name    (2) SSN            (3) Relationship   (4) Child tax credit
      DANIEL J     PARK         643-18-2290        SON                [X]
      SEO YEON     PARK         643-19-5571        DAUGHTER           [X]
"""


@pytest.mark.parametrize("name", ["HYUN WOO", "JI EUN", "DANIEL J", "SEO YEON"])
def test_name_columns(rules, name):
    assert covers(rules(TAX), name, TAX)


def test_name_columns_skip_header_lines(rules):
    people = [s.text for s in rules(TAX) if s.entity == "PERSON"]
    assert not any(w in people for w in ("If", "Home", "Last", "City", "SON", "DAUGHTER"))


def test_column_gap_splits_person_and_drops_form_tokens():
    from obscura.detection.text.base import Span
    t = "BANKS, ROSE MARIE   F   70Y   DOB 02/14/1955   MRN H005193"
    parts = TextAnalyzer._split_columns(t, [Span(0, t.find("DOB") + 3, "PERSON", 0.9, "ner:x", "")])
    assert [p.text for p in parts] == ["BANKS, ROSE MARIE"]


def test_column_split_drops_cut_off_words(rules):
    t = "Investigating Officer: Officer Michael Harris   Badge #: 58754   ID: 363361\n"
    assert [s.text for s in rules(t) if s.entity == "PERSON"] == ["Michael Harris"]


@pytest.mark.parametrize("text,word", [
    ("4 mm R. Tinel's at L carpal tunnel: positive", "R. Tinel"),
    ("positive. Phalen's: positive at 40 sec", "Phalen"),
    ("onto eastbound Ben White, her car was struck", "Ben White"),
    ("run, sleep through the night, drive on Ben White", "Ben White"),
    ("Rec'd Stowers demand from R. Kim dated", "Stowers"),
    ("Miranda warnings were read", "Miranda"),
    ("filed a Daubert motion", "Daubert"),
])
def test_public_names_are_not_people(text, word):
    i = text.find(word)
    assert is_not_a_person(text, i, i + len(word))


@pytest.mark.parametrize("text,word", [("I was driving on Ben White's property", "Ben White"),
                                       ("Dr. Thomas's notes", "Thomas"), ("Mr. Allen at the left", "Allen"),
                                       ("Mr. Stowers said hello", "Stowers")])
def test_people_with_public_looking_names_kept(text, word):
    i = text.find(word)
    assert not is_not_a_person(text, i, i + len(word))


def test_place_word_after_known_surname_not_propagated(rules):
    text = "V1 Grace Hill was interviewed.\nSECTOR: PROSPECT HILL SUBSTATION\nMs. Hill declined."
    hills = [s for s in rules(text) if s.entity == "PERSON" and s.text.upper() == "HILL"]
    assert all("SUBSTATION" not in text[s.end:s.end + 12] for s in hills)


def test_role_word_surname_still_propagates(rules):
    text = "Client: Kathleen Ward\nSubject: RE: Settlement offer — Ward claim\nMrs. Ward is a 23-year-old."
    assert sum(1 for s in rules(text) if s.entity == "PERSON" and "Ward" in s.text) >= 3


@pytest.mark.parametrize("word", ["Amma", "Mama", "Abuela", "Grandma"])
def test_kinship_words_not_names(rules, word):
    text = f"I'll take them home to {word} and you'll never see them."
    assert not [s for s in rules(text) if s.entity == "PERSON"]


def test_qa_carrier_answer_not_a_person(rules):
    text = "15        Q.   Who is the carrier on that phone?\n16        A.   Meridian. It's on my wife's plan.\n"
    assert not [s for s in rules(text) if s.entity == "PERSON"]


def test_qa_platform_answer_not_a_username(rules):
    text = "Q.   Do you have a Facebook or Instagram?\nA.   Facebook. It's Hunter Wells.\n"
    assert not [s for s in rules(text) if s.entity == "USERNAME" and s.text == "Facebook"]


def test_qa_names_list_with_apostrophe(rules):
    text = "Q.  What are your children's names and ages?\nA.  Ja'Marcus is 5.\n"
    assert covers(rules(text), "Ja'Marcus", text)


# ---- labels -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,value,entity", [
    ("  DL: TX 40921187\n\nI certify", "40921187", "DRIVERS_LICENSE"),
    ("Driver License: TX 40921187", "40921187", "DRIVERS_LICENSE"),
    ("My SSN / DL# is TX 0199 4527\nMy home", "0199 4527", "DRIVERS_LICENSE"),
    ("Trailer LP: TX 4PK8813\n", "4PK8813", "LICENSE_PLATE"),
    ("(BCBSTX group HCE-11820, member\n    IDs HCE884410217-02 and HCE884410217-03).", "HCE-11820", "HEALTH_PLAN_ID"),
    ("(BCBSTX group HCE-11820, member\n    IDs HCE884410217-02 and HCE884410217-03).", "HCE884410217-02", "HEALTH_PLAN_ID"),
    ("(BCBSTX group HCE-11820, member\n    IDs HCE884410217-02 and HCE884410217-03).", "HCE884410217-03", "HEALTH_PLAN_ID"),
    ("member ID XOD884417203, group\n228174; Guardian", "228174", "HEALTH_PLAN_ID"),
    ("U.S. passports (No. A04418277 -- Aanya; No. A04418278 -- Rohan)", "A04418278", "PASSPORT"),
    ("an Indian Aadhaar\n        number (4471 9902 3318) and PAN", "4471 9902 3318", "NATIONAL_ID"),
    ("Claim #: 0398-22-1187, 0398-22-1188", "0398-22-1188", "CLAIM_NUMBER"),
    ("  D  EIN: 88-1937204\n", "88-1937204", "EIN"),
    ("Permanent resident card (I-551), # SRC1912345678, exp", "SRC1912345678", "NATIONAL_ID"),
    ("The last three numbers of Petitioner's driver's\n    license number are 336.", "336", "DRIVERS_LICENSE"),
    ("The last four digits of her Social Security number are 9921.", "9921", "SSN"),
    ("Export date: 10/01/2025    Exported by: kbrandt\n", "kbrandt", "USERNAME"),
    ("cc: Patient portal (thuyle0109), Gulfgate", "thuyle0109", "USERNAME"),
])
def test_label_values(rules, text, value, entity):
    spans = rules(text)
    assert any(s.entity == entity and value in s.text for s in spans), found(spans)


@pytest.mark.parametrize("text", ["TikTok (@mariaruiz_atx, inactive);", "printed by hand", "Portal: enrolled",
                                  "Policy:\n\nThe policy covers"])
def test_label_values_not_overreached(rules, text):
    spans = rules(text)
    assert not any(s.text in ("inactive", "hand", "enrolled", "The") for s in spans), found(spans)


@pytest.mark.parametrize("text,value", [("Job # 4471982   Doc ID 20250318-DS-00917", "20250318-DS-00917"),
                                        ("Release ID\nREL-25-00912. Fee paid", "REL-25-00912"),
                                        ("Capital Hill Community Bank NMLS #408812.", "408812")])
def test_document_ids_are_suggestions_only(rules, text, value):
    assert not any(value in s.text for s in rules(text))


def test_ein_on_by_default():
    assert "EIN" in entities_for_profile("standard")


# ---- employers --------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,value", [
    ("A.   I drove for Caliche Transport out of San Marcos", "Caliche Transport"),
    ("HP:   She's an accountant, at Brightline CPA.\n", "Brightline CPA"),
    ("The W-2 of Plaintiff's spouse from Brightline CPA Group LLC is not relevant", "Brightline CPA Group LLC"),
    ("Commercial Motor Vehicle: Y   GVWR 80,000   Carrier: SWIFTLINE FREIGHT LLC   USDOT # 3318852",
     "SWIFTLINE FREIGHT LLC"),
    ("HP:   I own a food truck. Seoul Food ATX. Korean barbecue, tacos.", "Seoul Food ATX"),
    ("  C  Business name: SEOUL FOOD ATX LLC                           D  EIN", "SEOUL FOOD ATX LLC"),
])
def test_employers(rules, text, value):
    assert any(s.entity == "EMPLOYER" and s.text == value for s in rules(text)), found(rules(text))


@pytest.mark.parametrize("text", ["Insurance Carrier: State Farm Mutual\n", "we started at Noon",
                                  "started with Physical Therapy"])
def test_not_employers(rules, text):
    assert not [s for s in rules(text) if s.entity == "EMPLOYER"]


def test_employer_short_name_propagates_but_not_party_caption(rules):
    text = ("SWIFTLINE FREIGHT LLC,        )\n          Defendant.          )\n"
            "A.   I drove for Caliche Transport before that.\nQ.   Why did you leave Caliche?\n")
    spans = rules(text)
    assert any(s.entity == "EMPLOYER" and s.text == "Caliche" for s in spans)
    assert not any(s.entity == "EMPLOYER" and s.text.upper() == "SWIFTLINE" for s in spans)


# ---- places -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,value", [
    ("Works as a bartender (the bar on Cincinnati Ave\n  across from the UTEP lot). Reports",
     "the bar on Cincinnati Ave\n  across from the UTEP lot"),
    ("pt lives alone in a mobile home at the back of the Shady Acres park off FM 150, lot 22.",
     "a mobile home at the back of the Shady Acres park off FM 150, lot 22"),
    ("stopped in traffic on southbound MoPac just past the Far West Blvd exit when struck",
     "southbound MoPac just past the Far West Blvd exit"),
    ("Worked Sat lunch at the Mueller farmers market.", "the Mueller farmers market"),
    ('drinking at "the icehouse on Bandera by the Valero." S1', "the icehouse on Bandera by the Valero"),
    ("Location at time: SHELL STATION NE CORNER, PUMP 6; has dashcam", "SHELL STATION NE CORNER, PUMP 6"),
    ("he was at pump 6 of the Shell station on the\n  northeast corner and that",
     "pump 6 of the Shell station on the\n  northeast corner"),
    ("(Little Sprouts Learning Center on Wurzbach Rd), and the", "Little Sprouts Learning Center on Wurzbach Rd"),
    ("alone at the Cedar Park Recreation Center pool for", "the Cedar Park Recreation Center pool"),
    ("Apt. 318, Austin, TX 78745 (the Villas at Little Texas)", "the Villas at Little Texas"),
    ("his after-school program at the YMCA on Ben White. I", "his after-school program at the YMCA on Ben White"),
    ("coaching my daughter's soccer team at Garrison\nPark. My", "Garrison\nPark"),
    ("I picked up the load at the H-E-B distribution center in San Marcos at 4:00.",
     "H-E-B distribution center in San Marcos"),
    ("I backed into a pole at a Love's in Waco. No injuries.", "Love's in Waco"),
    ("We do the lot on East Sixth by the brewery Thursday", "the lot on East Sixth by the brewery"),
    ("Loss location: E Ben White Blvd @ S Congress Ave, Austin TX", "E Ben White Blvd @ S Congress Ave"),
    ("load from HEB DC San Marcos, ~45", "HEB DC San Marcos"),
    ("son's T-ball game at Dittmar Park, wrist brace visible", "Dittmar Park"),
    ("Mueller Crossing Apartments (job #RB-2307), Building C, 3rd floor east balcony\n",
     "Mueller Crossing Apartments (job #RB-2307), Building C, 3rd floor east balcony"),
    ("and the Saturday art program at the Round Rock Public Library.",
     "the Saturday art program at the Round Rock Public Library"),
    ("it's next door, it's 12B, I'm in 12C. apartment building", "12C"),
    ("Yes, Pinecrest, building 12, upstairs. He's hurting her", "Pinecrest, building 12, upstairs"),
    ("She works at the Walmart in Pflugerville on weekends.", "Walmart in Pflugerville"),
])
def test_location_phrases(rules, text, value):
    assert covers(rules(text), value, text), found(rules(text))


@pytest.mark.parametrize("text", [
    "   3. Trauma clinic -- 2 weeks, repeat CBC.",
    "INFECTIOUS DISEASE / RYAN WHITE CLINIC\n5005 Alameda Ave",
    "Location type: Street/Highway\n  Destination: Capitol",
    "Rdwy Part: Main/Proper Lane   Block #: 100",
    "1507 Kestrel Hollow Dr\n      City/State/ZIP:   Pflugerville",
    "going to\n      Restaurant Depot for supplies.",
    "because of the\nQ4 grill rebuild + van.",
    "I told her about the Women's shelter my church supports",
    "He loves drawing and Minecraft.",
    "Neuro: GCS 15 (E4V5M6), CN II-XII intact",
])
def test_not_identifying_places(rules, text):
    # (a real street address in the same text is fine; the form words / program names must not be flagged)
    spans = rules(text)
    assert not [s for s in spans if s.entity == "INDIRECT_LOCATION" or
                s.entity == "ADDRESS" and not s.text[:1].isdigit()], found(spans)


def test_crash_narrative_travel_road_is_only_a_suggestion(rules):
    text = "Unit 1 (black 2010 Ford F-150) was traveling northbound on Elm Boulevard in the inside lane."
    assert not [s for s in rules(text) if s.entity == "INDIRECT_LOCATION"]


def test_chain_name_alone_not_propagated(rules):
    text = "W1 was at pump 6 of the Shell station on the corner.\n[Shell NE corner -- W1 location]\n"
    spans = [s for s in rules(text) if s.entity == "INDIRECT_LOCATION"]
    assert not any(text[s.start:s.end].startswith("Shell NE") for s in spans)


# ---- relationships, schools ------------------------------------------------------------------------

@pytest.mark.parametrize("text,value", [
    ("Family: Client's 8-year-old daughter, Kaylee, is placed", "Client's 8-year-old daughter"),
    ("Pt's 6 y/o son (Mateo) was in a rear booster", "Pt's 6 y/o son"),
    ("after her ex-boyfriend showed up", "her ex-boyfriend"),
    ("Rohan attends 2nd grade at Westwood Hills\n    Elementary. No other", "Westwood Hills\n    Elementary"),
])
def test_roles_and_schools(rules, text, value):
    assert covers(rules(text), value, text), found(rules(text))


@pytest.mark.parametrize("text", ["standards of practice of the International Academy of Life Care Planners",
                                  "He had a Texas A&M sticker on the truck."])
def test_school_names_that_are_not_attendance(rules, text):
    assert not [s for s in rules(text) if s.entity == "SCHOOL"]


def test_weak_suggestion_does_not_swallow_confident_name(rules):
    text = "later identified as V1 Grace Hill, sitting on the kitchen floor"
    assert ("PERSON", "Grace Hill") in found(rules(text))


# ---- second independent document set (docs2): structured identifiers ---------------------------------------

@pytest.mark.parametrize("text,value,entity", [
    ("Pt verified identity with DOB and last 4 of SSN (7714).", "7714", "SSN"),
    ("12   Q.   And the last four of your Social.\n13   A.   3318.\n", "3318", "SSN"),
    ("- Ana's DOB 02/14/1989, SSN on file ends 6610 -- needed", "6610", "SSN"),
    ("  DL:       IL S236-4410-4068 -- SUSPENDED", "S236-4410-4068", "DRIVERS_LICENSE"),
    ("SSN (last 4): 5521    KY OL#: S06-418-822", "S06-418-822", "DRIVERS_LICENSE"),
    ("the truck's plate (JHK 4471, Ohio) and called", "JHK 4471", "LICENSE_PLATE"),
    ("IL plate CK 74319   VIN 4S4BRBCC5B3361872", "CK 74319", "LICENSE_PLATE"),
    ("Patient payment -- ACH checking ****0918      -1", "****0918", "BANK_ACCOUNT"),
    ("loan # LN-0088140427\n", "LN-0088140427", "BANK_ACCOUNT"),
    ("ACH DEBIT  US SMALL BUS ADMIN  EIDL  LOAN 7720418806   731.00", "7720418806", "BANK_ACCOUNT"),
    ("PIP CLM KAM-26-PA-0442918.", "KAM-26-PA-0442918", "CLAIM_NUMBER"),
    ("door. code is 4471# my brother", "4471#", "PASSWORD"),
    ("Gate code for delivery: *2318. Dog in unit.", "*2318", "PASSWORD"),
    ("the front door's locked, the code is 1-9-7-4 star.", "1-9-7-4 star", "PASSWORD"),
    ("06/28/2026 08:14  jkirkendall  FNOL via app by insured", "jkirkendall", "USERNAME"),
    ("from IP 68.43.117.209  user zaytoon_yousef  device", "zaytoon_yousef", "USERNAME"),
    ('"K-Wolf"             kwolf.mke (Instagram)', "kwolf.mke", "USERNAME"),
    ("SID: AZ19847722     FBI: 488213KD7", "AZ19847722", "ID_NUMBER"),
    ("SID: AZ19847722     FBI: 488213KD7", "488213KD7", "ID_NUMBER"),
    ("Tribal enrollment #: TO-0028815", "TO-0028815", "NATIONAL_ID"),
    ("Inmate was ADOC 248871 for armed", "248871", "ID_NUMBER"),
    ("Student ID:     2009184471        FLEID: FL004418820733", "FL004418820733", "ID_NUMBER"),
    ("Member MCH4471208835  Grp GSU-STU-26", "GSU-STU-26", "HEALTH_PLAN_ID"),
    ("cert. OTRS-G-44107 -- non-probate", "OTRS-G-44107", "HEALTH_PLAN_ID"),
    ("medical record number at Natividad is NMC-0771842. I still", "NMC-0771842", "MRN"),
    ("DOB 08/24/1997. ePCR BCFD-26-1103-0471.", "BCFD-26-1103-0471", "MRN"),
    ("identity document (DPI) number is 2417 63829 0801 and my", "2417 63829 0801", "NATIONAL_ID"),
    ("my Guatemalan passport number is\n   T48812207, issued June 3, 2019.", "T48812207", "PASSPORT"),
    ("1978 Ford F-100, blue, VIN F10GLX44718 (restored)", "F10GLX44718", "VIN"),
    ("FL10 BIRTHDATE 08211984   FL11 SEX F", "08211984", "DATE_OF_BIRTH"),
    ("#219 took a report (KPD 26-011842). Dog's rabies", "KPD 26-011842", "LAW_ENFORCEMENT_ID"),
    ("Police report MNPD 2026-0217733; Hollingsworth cited", "MNPD 2026-0217733", "LAW_ENFORCEMENT_ID"),
    ("BOOKING #: P26-0731-0418     SO #: 411207     SID: AZ19847722", "411207", "LAW_ENFORCEMENT_ID"),
    ("(completed by booking officer C. Ybarra #D4472)", "D4472", "LAW_ENFORCEMENT_ID"),
    ("Officer Daniel Ruelas\n   (#418) took my statement", "418", "LAW_ENFORCEMENT_ID"),
    ("LINK/NCIC entry: KY26DV0441872   Served", "KY26DV0441872", "LAW_ENFORCEMENT_ID"),
    ("Related SAPD report: SAPD-25-187734    CAD Event: E2025-0816-01177\n", "E2025-0816-01177", "LAW_ENFORCEMENT_ID"),
    ("Arresting Officer: CASTANEDA, J #4127     Transporting: DOYLE, M #3390", "3390", "LAW_ENFORCEMENT_ID"),
    ("DPD property receipt DPD-PR-25-118402 -- handgun", "DPD-PR-25-118402", "LAW_ENFORCEMENT_ID"),
    ("seized as evidence by SAPD (tag P25-0816-3301)", "P25-0816-3301", "LAW_ENFORCEMENT_ID"),
    ("FINGERPRINTS: Livescan TCN TX2508170146B -- IDENT HIT", "TX2508170146B", "LAW_ENFORCEMENT_ID"),
])
def test_docs2_identifiers(rules, text, value, entity):
    spans = rules(text)
    assert any(s.entity == entity and value in s.text for s in spans), found(spans)


@pytest.mark.parametrize("text", [
    "For ROI request ROI-25-03391 (requestor: Kim & Abernathy)",
    "UB-04 field FL54 PRIOR PMTS   FL61 GROUP NAME",
    "See PLPROD 000703-000731 (Venmo/Zelle records)",
    "Case/Rep0rt N0. text here",
])
def test_docs2_not_identifiers(rules, text):
    spans = rules(text)
    assert not [s for s in spans if s.entity in ("LAW_ENFORCEMENT_ID", "HEALTH_PLAN_ID", "ID_NUMBER", "USERNAME")
                and s.text in ("ROI-25-03391", "FL54", "FL61", "000703-000731", "Rep0rt N0")], found(spans)


# ---- docs2: names, schools, descriptors ------------------------------------------------------------------

@pytest.mark.parametrize("text,name", [
    ('NAME: ANTONE, MARCUS RAY JR      AKA: "BIG RAY", MARCUS R. ANTONIO\nDOB: 10/02/1980', "BIG RAY"),
    ('his children, Jesse Lee\nHummingbird Jr. ("Junior") and wife Tasha', "Junior"),
    ("grandchildren Kaden,\nAniyah, Wyatt, and Lily; his sister", "Wyatt"),
    ("   Dependents:   2  (Liam, 10; Ciara, 7)    Marital status", "Ciara"),
    ("he's coughing. Dev, Dev, stay with me.", "Dev"),
    ("I was dropping H. off at the car-rider line", "H."),
    ('"J.L.," as everyone knew him, graduated', "J.L."),
    ("6  BUPRENORPHINE-NALOX 8-2 MG FILM     28    14   OKONJO, D (X-waiver)    0   MCD", "OKONJO, D"),
    ("Thanks,\nRay\n", "Ray"),
    ("Hi Monique,\nThe adjuster called.", "Monique"),
])
def test_docs2_names(rules, text, name):
    assert covers(rules(text), name, text), found(rules(text))


@pytest.mark.parametrize("text", [
    "SUSPECT (S1) -- IDENTIFIED, NOT IN CUSTODY\n",
    "02:18:12  TOB CALLER ADVSD PT 29YOM UNC NOT BREATHING, POSS FENTANYL.",
    "clear saliva from Stensen's duct, no parotid injury",
    "Sacroiliac / hip: Patrick's (FABER) test negative",
    "Clinician: Ruth Okafor-Lindqvist, LMHC",
    'GRACE ELIZABETH HILL ("Applicant") files this Application',
    "child tax credit / credit for other dependents (Sch. 8812) ....",
    "was traveling westbound on E Ben White Blvd main lanes",
])
def test_docs2_not_people(rules, text):
    bad = {"IDENTIFIED, NOT", "BREATHING, POSS", "Stensen", "Patrick", "LMHC", "Applicant", "Sch", "Ben White Blvd",
           "Ben White"}
    assert not [s for s in rules(text) if s.entity == "PERSON" and s.text in bad], found(rules(text))


@pytest.mark.parametrize("text,value", [
    ("A.   Perth Amboy High, ninth grade. She used to", "Perth Amboy High"),
    ("he goes to Park Forest Middle. Now Monique", "Park Forest Middle"),
    ("Ruben drives her to Peakview\n     School because", "Peakview\n     School"),
    ("HAWTHORNE RIDGE HIGH SCHOOL  --  4800 NW 39th Avenue", "HAWTHORNE RIDGE HIGH SCHOOL"),
])
def test_docs2_schools(rules, text, value):
    assert covers(rules(text), value, text), found(rules(text))


def test_attends_prayers_is_not_a_school(rules):
    assert not [s for s in rules("Attends Friday prayers at the mosque.") if s.entity == "SCHOOL"]


@pytest.mark.parametrize("text,value", [
    ("the only overnight load dispatcher for\nthe Fife yard. She has", "the only overnight load dispatcher for\nthe Fife yard"),
    ("I'm a unit clerk on the night shift in the Hopkins ED, not a nurse.", "a unit clerk on the night shift in the Hopkins ED"),
    ("Employee was the only RN on 6 North that night certified in CPI de-escalation; per", "the only RN on 6 North that night certified in CPI de-escalation"),
])
def test_docs2_roles(rules, text, value):
    assert covers(rules(text), value, text), found(rules(text))


@pytest.mark.parametrize("text", ["Patient works as a registered nurse at Westside Elementary School and is worried about missing work.",
                                  "Witness Robert White, the night manager at the Starbucks, stated she saw Unit 1 speeding."])
def test_role_phrase_stops_at_the_clause(rules, text):
    roles = [s.text for s in rules(text) if s.entity == "INDIRECT_ROLE"]
    assert all("worried" not in r and "stated" not in r for r in roles), roles


@pytest.mark.parametrize("text,value", [
    ('Mother describes him as heavyset, about 50, gray goatee, "Semper Fi" tattoo on the right calf; he left.',
     'heavyset, about 50, gray goatee, "Semper Fi" tattoo on the right calf'),
    ("SECTION C -- SCARS / MARKS / TATTOOS\n  L forearm         teardrop and \"520\" area code, faded\n",
     'teardrop and "520" area code, faded'),
    ("Skin:   Incidental 3 cm cafe-au-lait macule over the right shoulder.", "3 cm cafe-au-lait macule over the right shoulder"),
    ("the yellow split-level across from the park entrance on Shroyer.", "the yellow split-level across from the park entrance on Shroyer"),
    ("tamales for the church sales at St. Mary's in Walsenburg.", "St. Mary's in Walsenburg"),
])
def test_docs2_descriptors(rules, text, value):
    assert covers(rules(text), value, text), found(rules(text))


def test_generic_exam_appearance_not_flagged(rules):
    text = "MENTAL STATUS EXAMINATION\n  Appearance: thin, unshaven, wearing hospital gown, fair hygiene."
    assert not [s for s in rules(text) if s.entity == "PHYSICAL_DESCRIPTOR"]
