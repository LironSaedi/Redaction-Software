"""Indirect identifiers — the McDonald's-on-Bank-Street problem."""
import itertools

import pytest

from tests.conftest import found

BRANDS = ["McDonald's", "Walgreens", "Shell", "7-Eleven", "Starbucks", "Waffle House", "Dollar General", "H-E-B", "CVS",
          "Home Depot", "Taco Bell", "Circle K", "Whataburger", "Walmart"]
STREETS = ["Bank Street", "Main St", "5th Avenue", "Elm Ave", "Route 9", "Lamar Blvd", "Oak Street", "Martin Luther King Jr Blvd"]
PREPS = ["on", "at", "near", "by", "across from", "behind", "next to", "off"]


@pytest.mark.parametrize("brand,street,prep", list(itertools.product(BRANDS, STREETS[:4], PREPS[:4])))
def test_business_on_street(rules, brand, street, prep):
    text = f"It happened at the {brand} {prep} {street} around midnight."
    spans = rules(text)
    assert any(s.entity == "INDIRECT_LOCATION" and brand in s.text and street.split()[0] in s.text for s in spans), found(spans)


@pytest.mark.parametrize("text", ["the corner of Bank Street and Elm Avenue", "the intersection of Main and 5th",
                                  "at the corner of Lamar Blvd & Parmer Lane", "Oak Street and Pine Road",
                                  "the junction of Route 9 and Elm St"])
def test_intersections(rules, text):
    assert any(s.entity == "INDIRECT_LOCATION" for s in rules(f"The crash was at {text}.")), found(rules(text))


@pytest.mark.parametrize("text,street", [("she lives on Pecan Street", "Pecan Street"),
                                         ("my mother lives over on Oak Street", "Oak Street"),
                                         ("his house is near Willow Lane", "Willow Lane")])
def test_lives_on(rules, text, street):
    assert street in [s.text for s in rules(text)], found(rules(text))


@pytest.mark.parametrize("text", ["the Sunset Ridge Apartments", "Pinecrest Apartments", "Lucky Star Motel", "Joe's Bar & Grill",
                                  "First Baptist Church", "Oakwood Mobile Home Park", "the Blue Moon Tavern"])
def test_named_venues(rules, text):
    assert any(s.entity == "INDIRECT_LOCATION" for s in rules(f"He stays at {text} most nights.")), found(rules(text))


@pytest.mark.parametrize("text", ["Walgreens #4471", "CVS Pharmacy #2997", "HEB #612", "Shell station #22"])
def test_numbered_stores(rules, text):
    assert any(s.entity == "INDIRECT_LOCATION" for s in rules(text)), found(rules(text))


@pytest.mark.parametrize("text", ["MCDONALD'S F6055 MINNEAPOLIS MN", "SHELL OIL 4310 ORLANDO FL", "WALGREENS #2650 KILGORE TX"])
def test_card_merchant_lines(rules, text):
    # a chain store and its town on a card statement is offered for review, not redacted on its own
    spans = rules(f"03/14  Card Purchase {text} Card 2621  $12.00", include_suggestions=True)
    loc = [s for s in spans if s.entity == "INDIRECT_LOCATION"]
    assert loc and not any(s.meta.get("selected") for s in loc), found(spans)


@pytest.mark.parametrize("text", ["apartment 4B", "Apt. 12", "the Pinecrest Apartments, unit 213", "she stays in room 214 at the motel"])
def test_units(rules, text):
    assert any(s.entity == "INDIRECT_LOCATION" for s in rules(text)), found(rules(text))


@pytest.mark.parametrize("text", ["Unit 1 struck Unit 2 in the rear.", "Driver of Unit 1 stated", "the Home Depot. Unit 1 driver"])
def test_crash_units_not_locations(rules, text):
    assert not [s for s in rules(text) if s.entity == "INDIRECT_LOCATION" and s.text.lower().startswith("unit")], found(rules(text))


ROLES_SELECTED = ["the night manager at the Shell station", "the only cashier at the Dollar General",
                  "the overnight clerk at the Motel 6", "the head coach of the Tigers", "her 7-year-old daughter",
                  "the victim's estranged husband", "his twin brother", "the manager there", "Johnson's estranged wife",
                  "the sole female deputy", "the general manager of Fiesta Mart"]


@pytest.mark.parametrize("text", ROLES_SELECTED)
def test_identifying_roles(rules, text):
    assert any(s.entity == "INDIRECT_ROLE" for s in rules(f"We spoke to {text} yesterday.")), found(rules(text))


# (a named person's relative — "Johnson's employer" — is a suggestion: the name itself is what gets redacted)
@pytest.mark.parametrize("text", ["her husband", "my mother", "the driver of Unit 2", "the patient", "your children", "our kids",
                                  "Johnson's employer", "the passenger in Vehicle 1"])
def test_generic_roles_are_suggestions_only(rules, text):
    assert not [s for s in rules(f"Then {text} left.") if s.entity == "INDIRECT_ROLE"], found(rules(text))


@pytest.mark.parametrize("text,emp", [("She works at Acme Logistics LLC as a driver", "Acme Logistics LLC"),
                                      ("employed as a HVAC technician at Amazon Fulfillment Center DFW7", "Amazon Fulfillment Center DFW7"),
                                      ("Employer: QuikTrip Corporation", "QuikTrip Corporation"),
                                      ("he was fired by Summit Roofing & Construction", "Summit Roofing & Construction"),
                                      ("Payroll Direct Dep ACME LOGISTICS LLC PPD ID: 123", "ACME LOGISTICS LLC")])
def test_employers(rules, text, emp):
    assert emp in [s.text for s in rules(text) if s.entity == "EMPLOYER"], found(rules(text))


def test_hr_letterhead(rules):
    assert "Brightline Staffing Inc." in [s.text for s in rules("Brightline Staffing Inc.\nHuman Resources Department\n")]


@pytest.mark.parametrize("text", ["Oak Hill Elementary School", "Westlake High School", "University of Texas at Austin",
                                  "Austin Community College", "St. Mary's Academy", "Lincoln Middle School"])
def test_schools(rules, text):
    assert any(s.entity == "SCHOOL" for s in rules(f"The kids attend {text}.")), found(rules(text))


@pytest.mark.parametrize("text", ["a silver 2017 Honda Accord", "white Ford F-150", "a red 2015 Chevy Silverado with a dented tailgate",
                                  "the black 2020 Tesla Model 3", "2019 Toyota Camry"])
def test_vehicles(rules, text):
    assert any(s.entity == "VEHICLE_DESCRIPTION" for s in rules(f"He drove {text}.", entities={"VEHICLE_DESCRIPTION"}))


@pytest.mark.parametrize("text", ["a tattoo of a scorpion on his neck", "a teardrop tattoo under the left eye",
                                  "a large scar across her chin", "a port-wine stain on his cheek", "gold teeth"])
def test_physical(rules, text):
    assert any(s.entity == "PHYSICAL_DESCRIPTOR" for s in rules(f"The suspect has {text}.")), found(rules(text))


@pytest.mark.parametrize("text", ["It was really scary.", "surgical scar is healing well", "scar tissue noted at L4-5"])
def test_physical_negatives(rules, text):
    assert not [s for s in rules(text) if s.entity == "PHYSICAL_DESCRIPTOR"], found(rules(text))


def test_combination_risk_boost(rules):
    spans = rules("The night clerk at the Motel 6 on Route 9, a 34-year-old Hispanic female with a rose tattoo on her wrist, called.",
                  profile="strict")
    indirect = [s for s in spans if s.entity in ("INDIRECT_LOCATION", "INDIRECT_ROLE", "PHYSICAL_DESCRIPTOR", "DEMOGRAPHIC")]
    assert len(indirect) >= 3
    assert any("combination" in s.explanation for s in indirect)
