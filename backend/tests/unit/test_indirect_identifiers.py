"""Indirect identifiers written in prose: places tied to a person, roles that single someone out, and
physical descriptions (quasi.py / descriptors.py)."""
import pytest

from tests.conftest import covers


@pytest.mark.parametrize("text,value", [
    ("She drinks most nights at the Gull & Barrel on Harbor Way after her shift.", "the Gull & Barrel on Harbor Way"),
    ("The rear bay of Petrak's Auto Glass on Broadway, behind the old Kmart building, held the car.",
     "Petrak's Auto Glass on Broadway, behind the old Kmart building"),
    ("Sundays she stays at her aunt's townhouse at the Riverside high-rise on S. Grand St, near the bridge.",
     "her aunt's townhouse at the Riverside high-rise on S. Grand St"),
    ("He lives out at the old Velasquez place, last trailer past the Pinon turnoff, green roof.",
     "the old Velasquez place, last trailer past the Pinon turnoff, green roof"),
    ("I go to my Monday night grief group at Westside Methodist and to my brother's house.",
     "my Monday night grief group at Westside Methodist"),
    ("He made the deposit at the Elmwood branch by his gym.", "Elmwood branch by his gym"),
    ("Clerk at store #212 at the SW corner of Grand & Fifth", "store #212 at the SW corner of Grand & Fifth"),
    ("His truck sat in the lot of the Speedway at Burke Road and Hollis for an hour.",
     "the lot of the Speedway at Burke Road and Hollis"),
    ("I saw his van in the back row of the Kroger lot again.", "the Kroger lot"),
    ("Her boat is kept at slip 14 at the Alton marina.", "slip 14 at the Alton marina"),
    ("Branch: Fairview - Lincoln Ave #0315\n", "Fairview - Lincoln Ave #0315"),
    ("He rents the back room over the shoe repair on Delmar and eats at the diner.",
     "the back room over the shoe repair on Delmar"),
    ("They live in the green rambler three houses down from the Lakeview VFW now.",
     "the green rambler three houses down from the Lakeview VFW"),
    ("Exchanges happen at the food court by the fountain at Westgate Mall on Sundays.",
     "the food court by the fountain at Westgate Mall"),
    ("He plays dominoes at the café with the red awning across from the mosque most nights.",
     "the café with the red awning across from the mosque"),
    ("Mail goes c/o General Delivery, Port Isabel post office.", "General Delivery, Port Isabel post office"),
    ("She never misses the 7 a.m. Polish Mass at St. Stanislaus Kostka on Ash Street.",
     "the 7 a.m. Polish Mass at St. Stanislaus Kostka on Ash Street"),
    ("July rent unit 7C by the pool", "unit 7C by the pool"),
])
def test_indirect_locations(rules, text, value):
    spans = [s for s in rules(text) if s.entity in ("INDIRECT_LOCATION", "ADDRESS", "ORGANIZATION", "EMPLOYER")]
    assert covers(spans, value, text), [(s.entity, s.text) for s in spans]


@pytest.mark.parametrize("text,value", [
    ("Moved her to Ms. Okafor's room. She is the only Tagalog-speaking financial counselor on the north campus.",
     "the only Tagalog-speaking financial counselor on the north campus"),
    ("He's the -- he's the third-shift lead, only guy licensed on the boom lift.",
     "the third-shift lead, only guy licensed on the boom lift"),
    ("He was one of the two overnight crane\noperators at the Pier 9 terminal, per the union list.",
     "one of the two overnight crane\noperators at the Pier 9 terminal"),
    ("Employer hit: Mercy Regional -- overnight patient transporter, ED.", "overnight patient transporter, ED"),
    ("Occupation: RN, 2nd shift PICU charge nurse\n", "RN, 2nd shift PICU charge nurse"),
    ("Student works the 5 a.m. shift as the only student lifeguard at the campus pool.",
     "the 5 a.m. shift as the only student lifeguard at the campus pool"),
    ("Guarantor works nights running the loading crew at the Cargill elevator; call after 3.",
     "nights running the loading crew at the Cargill elevator"),
    ("Witness: the decedent's live-in caregiver for six years.", "decedent's live-in caregiver"),
    ("Husband is the PT guy who helped my dad after his surgery.", "the PT guy who helped my dad after his surgery"),
    ("She is in Mrs. Lindqvist's 3rd grade class this year.", "Mrs. Lindqvist's 3rd grade class"),
    ("Tell her she is our only bilingual (Hmong) SLP.\nNext line: x", "our only bilingual (Hmong) SLP"),
    ("Statement from my next-door neighbor about the dog.", "my next-door neighbor"),
    ("A prior complaint came from the UPS driver who covers that cul-de-sac.",
     "the UPS driver who covers that cul-de-sac"),
    ("He drives as the Saturday van driver for New Hope Fellowship.", "the Saturday van driver for New Hope Fellowship"),
    ("The retired Pratt machinist across the street saw it.", "The retired Pratt machinist across the street"),
    ("Called by the Rocking R foreman after he was found.", "the Rocking R foreman"),
    ("Her closest support is her nephew, a dispatcher at the Kearney yard.",
     "her nephew, a dispatcher at the Kearney yard"),
    ("We interviewed the children's paternal grandmother and the mother's new husband.",
     "the children's paternal grandmother"),
    ("We interviewed the children's paternal grandmother and the mother's new husband.", "the mother's new husband"),
    ("She drops off her 3-year-old at the sitter.", "her 3-year-old"),
    ("The manager's cousin who works the grill at night was there.",
     "The manager's cousin who works the grill at night"),
    ("EMPLOYMENT\n  OCCUPATION: OVERNIGHT STOCKER, AISLE 9\n", "OVERNIGHT STOCKER, AISLE 9"),
    ("Relationship:  my old squad leader from 3rd Brigade\n", "my old squad leader from 3rd Brigade"),
])
def test_indirect_roles(rules, text, value):
    spans = [s for s in rules(text) if s.entity in ("INDIRECT_ROLE", "EMPLOYER", "INDIRECT_LOCATION", "PERSON")]
    assert covers(spans, value, text), [(s.entity, s.text) for s in spans]


@pytest.mark.parametrize("text,value", [
    ("She described him as \"a young white guy, skinny, with his hair up in a bun.\"",
     "a young white guy, skinny, with his hair up in a bun"),
    ("Passenger was a woman with long bleached-blonde hair.", "long bleached-blonde hair"),
    ("Description: 5'10\", about 190 lbs, shaved head, red beard, a scar through his left eyebrow\n",
     "5'10\", about 190 lbs, shaved head, red beard, a scar through his left eyebrow"),
    ("CLMT:  A young boy, red hair, had a ring in his nose. His tag said Cody.",
     "A young boy, red hair, had a ring in his nose"),
    ("He's like six foot, skinny, he has a beard and a tattoo of a hawk on his neck, and he has a scar on his chin.",
     "a tattoo of a hawk on his neck, and he has a scar on his chin"),
    ("He's missing the tip of his right index finger.", "missing the tip of his right index finger"),
    ("You can't miss him: a gray handlebar mustache.", "a gray handlebar mustache"),
    ("Since the surgery she walks with a limp on her left side.", "walks with a limp on her left side"),
    ("RP said the man had a small anchor tat on his wrist.", "a small anchor tat on his wrist"),
    ("SCARS / MARKS / TATTOOS (SMT)\n  SMT-1   TAT R FARM \"LUPE\"\n  SMT-2   SC L CHEEK 1 IN\n",
     "TAT R FARM \"LUPE\""),
    ("Identifying features:\n  - Tattoo R calf, koi fish, color\n  - Gold crown on lower R molar\n",
     "Tattoo R calf, koi fish, color"),
    ("Teasing about the large port-wine birthmark on her neck continues.", "the large port-wine birthmark on her neck"),
])
def test_physical_descriptions(rules, text, value):
    spans = [s for s in rules(text) if s.entity == "PHYSICAL_DESCRIPTOR"]
    assert covers(spans, value, text), [(s.entity, s.text) for s in spans]


def test_long_body_marks_table_keeps_its_heading():
    from obscura.detection.text.base import NormText
    from obscura.detection.text.descriptors import find_appearance
    rows = "".join(f"  {part:<18}{desc}\n" for part, desc in [
        ("L chest", "eagle design, black ink, approx 4 in"), ("R side of neck", "\"Mia\" in script, red/black"),
        ("Both knuckles", "\"EAST\" (R hand) \"SIDE\" (L hand)"), ("L forearm", "teardrop and \"713\", faded"),
        ("Abdomen", "7 in healed vertical scar (stab wound 2015)"), ("L temple", "healed entry scar, round, 1 cm"),
        ("Upper teeth", "gold crown upper left incisor")])
    text = "SECTION C -- SCARS / MARKS / TATTOOS\n  Location          Description\n" + rows
    found = [s.text for s in find_appearance(NormText(text))]
    assert "gold crown upper left incisor" in found


@pytest.mark.parametrize("text", [
    "The only way to reach the nurse was the call button.",
    "Patient is the only one at home with her husband.",
    "We met the driver who was traveling westbound.",
    "She moved to my cousin's house in Santa Rosa for two months.",
    "U.S. CITIZENSHIP AND IMMIGRATION SERVICES\n\nIn the Matter of: R. M.",
    "The sole authorized member is listed as G. M. Holt.",
    "He works days at the plant and nights at home.",
    "Works full time as a dental hygienist at Lakeside Family Dental.",
    "She was the restrained driver of a silver 2016 Nissan Altima.",
    "Patient attends physical therapy at a clinic on Northside Drive.",
    "VITALS 19:16 BP 152/90 HR 102",
    "I walk with a cane since the accident.",
    "Son's father, Kyle Hale, lives in Spokane.",
    "Client advised of the agency's position on future care.",
])
def test_generic_phrases_are_not_indirect_identifiers(rules, text):
    spans = [s for s in rules(text) if s.entity in ("INDIRECT_ROLE", "INDIRECT_LOCATION", "PHYSICAL_DESCRIPTOR")]
    assert spans == [], [(s.entity, s.text) for s in spans]
