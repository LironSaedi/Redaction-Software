"""Spoken PII as a speech recogniser writes it (recorded statements, 911 calls, body-cam audio, voicemail).

Each case is a transcript line in the forms Whisper produces — digits grouped arbitrarily, numbers as words,
letters spelled out, "dot" / "at" emails — and the value that must end up inside a redaction."""
import pytest

from tests.conftest import covers, found


@pytest.fixture()
def spoken(rules):
    def run(text, **kw):
        kw.setdefault("transcript", True)
        return rules(text, **kw)
    return run


CASES = [
    # --- SSN ---
    ("SSN", "My social is 523-71-9921.", "523-71-9921"),
    ("SSN", "My social security number is 523 71 9921.", "523 71 9921"),
    ("SSN", "Social security number, 523, 71, 9921.", "523, 71, 9921"),
    ("SSN", "My social is 523719921.", "523719921"),
    ("SSN", "It's five two three seven one nine nine two one, that's my social.", "five two three seven one nine nine two one"),
    ("SSN", "My social security number is 523 -719921.", "523 -719921"),
    ("SSN", "SSN 523-71-9921, date of birth 11/2/1979.", "523-71-9921"),
    ("SSN", "The last four of my social are 9921.", "9921"),
    ("SSN", "Last four digits of her social security number are 4416.", "4416"),
    ("SSN", "Can you confirm your social? Yeah, 590-27-4416.", "590-27-4416"),
    # --- phones ---
    ("PHONE", "You can reach me at 512-398-0047.", "512-398-0047"),
    ("PHONE", "My cell is (512) 398-0047.", "(512) 398-0047"),
    ("PHONE", "Call me back at 512 398 0047.", "512 398 0047"),
    ("PHONE", "My number is 5123980047.", "5123980047"),
    ("PHONE", "My phone number is five one two, three nine eight, zero zero four seven.", "five one two, three nine eight, zero zero four seven"),
    ("PHONE", "Her cell phone is 210-455-0912.", "210-455-0912"),
    ("PHONE", "The callback number is 1-800-318-2245.", "1-800-318-2245"),
    ("PHONE", "Text me at 737-302-6614 when you get there.", "737-302-6614"),
    ("PHONE", "My work number is 512.836.2290.", "512.836.2290"),
    ("PHONE", "Home phone 398-0047.", "398-0047"),
    # --- cards / banking ---
    ("CREDIT_CARD", "My card number is 4111 1111 1111 1111.", "4111 1111 1111 1111"),
    ("CREDIT_CARD", "The card was 4111-1111-1111-1111, expiration 12/27.", "4111-1111-1111-1111"),
    ("CREDIT_CARD", "Visa 4 1 1 1 1111 1111 1111.", "4 1 1 1 1111 1111 1111"),
    ("CVV", "And the security code on the back is 123.", "123"),
    ("BANK_ACCOUNT", "My account number is 7720 0418 0471.", "7720 0418 0471"),
    ("BANK_ACCOUNT", "The checking account ending in 3318.", "3318"),
    ("ROUTING_NUMBER", "The routing number is 132874926.", "132874926"),
    ("BANK_ACCOUNT", "Account number 884100233.", "884100233"),
    # --- licences, plates, vehicles ---
    ("LICENSE_PLATE", "The other driver's plate was SFD4417.", "SFD4417"),
    ("LICENSE_PLATE", "His license plate number is S F D 4 4 1 7.", "S F D 4 4 1 7"),
    ("LICENSE_PLATE", "The plate is SFD 4417, it's a vanity plate.", "SFD 4417"),
    ("LICENSE_PLATE", "Texas plate 4PK8813.", "4PK8813"),
    ("LICENSE_PLATE", "License plate: TX 4PK8813.", "4PK8813"),
    ("DRIVERS_LICENSE", "My driver's license number is 40921187.", "40921187"),
    ("DRIVERS_LICENSE", "DL number 40921187, Texas.", "40921187"),
    ("DRIVERS_LICENSE", "Driver's license is TX 36120554.", "36120554"),
    ("VIN", "The VIN is 1HGCM82633A004352.", "1HGCM82633A004352"),
    # --- dates of birth / age ---
    ("DATE_OF_BIRTH", "My date of birth is November 2nd, 1979.", "November 2nd, 1979"),
    ("DATE_OF_BIRTH", "Date of birth 11/2/1979.", "11/2/1979"),
    ("DATE_OF_BIRTH", "I was born on March 3rd, 1985.", "March 3rd, 1985"),
    ("DATE_OF_BIRTH", "DOB is 04/30/1961.", "04/30/1961"),
    ("DATE_OF_BIRTH", "Her birthday is January 22, 2018.", "January 22, 2018"),
    # --- addresses ---
    ("ADDRESS", "I live at 3318 Wagon Trail Road in Lockhart.", "3318 Wagon Trail Road"),
    ("ADDRESS", "My address is 4410 South 1st Street, apartment 318.", "4410 South 1st Street"),
    ("ADDRESS", "We're at 1302 Maple Drive, Austin, Texas 78745.", "1302 Maple Drive"),
    ("ADDRESS", "It's 7420 Callaghan Road, apartment 12B.", "7420 Callaghan Road"),
    ("ADDRESS", "Send it to 1507 Kestrel Hollow Drive, Pflugerville.", "1507 Kestrel Hollow Drive"),
    ("ADDRESS", "Mail goes to P.O. Box 20418, Austin, Texas.", "P.O. Box 20418"),
    # --- names ---
    ("PERSON", "My name is Rosalind Pham.", "Rosalind Pham"),
    ("PERSON", "This is Officer Jennifer Castaneda with APD.", "Jennifer Castaneda"),
    ("PERSON", "Hi, this is Detective Mark Villalobos.", "Mark Villalobos"),
    ("PERSON", "My wife, Tammy, and my youngest, Colt.", "Tammy"),
    ("PERSON", "My wife, Tammy, and my youngest, Colt.", "Colt"),
    ("PERSON", "Last name P-A-R-K.", "P-A-R-K"),
    ("PERSON", "Rosalind Pham. P-H-A-M.", "P-H-A-M"),
    ("PERSON", "Most people call me Henry.", "Henry"),
    ("PERSON", "I spoke with Mr. Wells after the crash.", "Wells"),
    ("PERSON", "I, Hunter Wells, swear this is true.", "Hunter Wells"),
    ("PERSON", "Dr. Szymanski told me to rest.", "Szymanski"),
    ("PERSON", "Her daughter Kaylee is eight.", "Kaylee"),
    # --- email / online ---
    ("EMAIL", "My email is john.smith@gmail.com.", "john.smith@gmail.com"),
    ("EMAIL", "Email me at john dot smith at gmail dot com.", "john dot smith at gmail dot com"),
    ("EMAIL", "It's rpham1961@yahoo.com.", "rpham1961@yahoo.com"),
    ("USERNAME", "My Instagram is @mariaruiz_atx.", "@mariaruiz_atx"),
    ("USERNAME", "Venmo me at @hunter-wells-79.", "@hunter-wells-79"),
    # --- medical / insurance / case ids ---
    ("MEDICARE_ID", "My Medicare number is 1EG4-TE5-MK73.", "1EG4-TE5-MK73"),
    ("HEALTH_PLAN_ID", "Member ID XOD884417203.", "XOD884417203"),
    ("CLAIM_NUMBER", "The claim number is CLM-2023-0045871.", "CLM-2023-0045871"),
    ("POLICY_NUMBER", "Policy number 9934-221-07.", "9934-221-07"),
    ("MRN", "Medical record number 00483921.", "00483921"),
    ("CASE_NUMBER", "Case number D-1-GN-25-002918.", "D-1-GN-25-002918"),
    ("PASSWORD", "The code for her door lock is 4471.", "4471"),
    ("PASSWORD", "My PIN is 8842.", "8842"),
    ("PASSWORD", "The gate code is 1985.", "1985"),
    # --- sensitive content ---
    ("MEDICAL_CONDITION", "I was diagnosed with type 2 diabetes last year.", "type 2 diabetes"),
    ("MENTAL_HEALTH", "I've been treated for bipolar disorder since 2015.", "bipolar disorder"),
    ("SUBSTANCE_USE", "I'm on methadone through the clinic.", "methadone"),
    ("SEXUAL_REPRODUCTIVE_HEALTH", "She found out she was HIV positive.", "HIV positive"),
    ("MEDICATION", "They gave me oxycodone for the pain.", "oxycodone"),
    ("INJURY", "I had a herniated disc at L4-L5.", "herniated disc"),
    # --- indirect ---
    ("INDIRECT_LOCATION", "I work at the McDonald's on Bank Street.", "the McDonald's on Bank Street"),
    ("INDIRECT_LOCATION", "It happened at the Shell station on Lamar.", "the Shell station on Lamar"),
    ("INDIRECT_LOCATION", "We do the lot on East Sixth by the brewery.", "the lot on East Sixth by the brewery"),
    ("INDIRECT_LOCATION", "I'm in 12C, next door to them in the apartment building.", "12C"),
    ("EMPLOYER", "I drive for Swiftline Freight.", "Swiftline Freight"),
    ("EMPLOYER", "She's a nurse at St. David's Medical Center.", "St. David's Medical Center"),
    ("EMPLOYER", "I own a food truck. Seoul Food ATX.", "Seoul Food ATX"),
    ("INDIRECT_ROLE", "The manager there knows me by name, she's the night manager.", "the night manager"),
    ("INDIRECT_ROLE", "My 8-year-old daughter was in the back seat.", "My 8-year-old daughter"),
    ("SCHOOL", "My son goes to Westwood Hills Elementary.", "Westwood Hills Elementary"),
    ("VEHICLE_DESCRIPTION", "He drives a gray 2019 Ford F-150.", "gray 2019 Ford F-150"),
    ("PHYSICAL_DESCRIPTOR", "He has a scorpion tattoo on his neck.", "scorpion tattoo"),
]


OFF_BY_DEFAULT = {"CASE_NUMBER", "MEDICAL_CONDITION", "MENTAL_HEALTH", "SUBSTANCE_USE", "SEXUAL_REPRODUCTIVE_HEALTH",
                  "MEDICATION", "INJURY", "VEHICLE_DESCRIPTION"}


@pytest.mark.parametrize("entity,text,value", CASES, ids=[f"{i:03d}-{c[0]}" for i, c in enumerate(CASES)])
def test_spoken_pii_is_redacted(spoken, entity, text, value):
    spans = spoken(text, profile="strict") if entity in OFF_BY_DEFAULT else spoken(text)
    assert covers(spans, value, text), found(spans)


NEGATIVES = [
    "It was about 4:30 in the afternoon.",
    "I waited maybe 45 minutes for the ambulance.",
    "I was going 35 miles an hour.",
    "The light was green, I had the arrow.",
    "He was about 20 feet away from me.",
    "We were on Interstate 35 northbound.",
    "It's like a 10 out of 10 pain.",
    "I've worked there for 12 years.",
    "We have 3 kids and 2 dogs.",
    "The bill was 1,250 dollars.",
    "Page 14, line 6.",
    "Uh, I think it was 2023, maybe 2022.",
    "Turn to exhibit 12.",
    "Okay. Yes, ma'am. No, sir.",
    "The temperature was 101 degrees.",
]


@pytest.mark.parametrize("text", NEGATIVES)
def test_spoken_non_identifiers_left_alone(spoken, text):
    spans = [s for s in spoken(text) if s.entity not in ("DATE", "MONEY", "AGE")]
    assert not spans, found(spans)
