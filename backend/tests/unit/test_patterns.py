"""Pattern recognizers: every supported format must be found; look-alikes must not be."""
import random

import pytest

from obscura.detection.text.base import NormText, ocr_digit_variant
from tests.conftest import covers, found
from tests.corpus import fake


def ents(spans, entity):
    return [s.text for s in spans if s.entity == entity]


# ---- SSN ----------------------------------------------------------------------------------------
SSN_POS = [
    "SSN: 523-71-9921", "Social Security No. 523-71-9921", "SS# 523 71 9921", "soc sec 523.71.9921",
    "SSN 523719921", "Social Security Number: 523719921", "Patient SSN: 523–71–9921", "SSN: 523—71—9921",
    "SSN: 523​-71-9921", "SSN: ５２３-７１-９９２１", "taxpayer id 523-71-9921", "S.S.N. 523-71-9921",
    "her social is 523-71-9921", "SSN:523-71-9921.", "(SSN 523-71-9921)", "SSN XXX-XX-9921", "SSN ***-**-9921",
    "last 4 of SSN: 9921", "SSN ending in 9921", "the last four digits of her social security number are 9921",
    "Seguro social 523-71-9921",
] + [f"SSN {fake.ssn(random.Random(i))}" for i in range(60)] + [f"Employee SSN: {fake.ssn(random.Random(i)).replace('-', '')}" for i in range(20)]


@pytest.mark.parametrize("text", SSN_POS)
def test_ssn_found(rules, text):
    spans = rules(text)
    assert any(s.entity in ("SSN", "ITIN") for s in spans), found(spans)


@pytest.mark.parametrize("text", [
    "Invoice 523-71-99210", "Part No. 523-71-9921-A", "ICD S13.4XXA", "Phone (523) 719-9214", "ZIP 52371-9921",
    "dated 05-23-1971", "order #523719921 shipped", "lot 523 71 9921 9", "CPT 99213 99214 99215",
    "Case 2023-71-9921", "1:23-cv-04567",
])
def test_ssn_lookalikes_not_ssn(rules, text):
    assert not ents(rules(text), "SSN"), found(rules(text))


def test_dashed_ssn_without_context_still_found(rules):
    assert ents(rules("The number 523-71-9921 was on the form."), "SSN")


def test_itin(rules):
    assert ents(rules("ITIN: 912-70-1234"), "ITIN")


# ---- cards ----------------------------------------------------------------------------------------
CARDS = [fake.card(random.Random(100 + i)) for i in range(50)]


@pytest.mark.parametrize("brand,num", CARDS)
def test_cards(rules, brand, num):
    assert ents(rules(f"Paid with {brand} {num} on file"), "CREDIT_CARD")


@pytest.mark.parametrize("text", ["Card: XXXX-XXXX-XXXX-4242", "card **** **** **** 4242", "Visa ending in 4242",
                                  "Mastercard ending 4242", "debit card ending with 4242", "xxxxxxxxxxxx4242 card"])
def test_masked_cards(rules, text):
    assert ents(rules(text), "CREDIT_CARD"), found(rules(text))


@pytest.mark.parametrize("text", ["Tracking 1Z999AA10123456784", "Order 4111 1111 1111 1112", "ISBN 978-3-16-148410-0",
                                  "Account 1234 5678 9012 3456"])
def test_card_negatives(rules, text):
    assert not ents(rules(text), "CREDIT_CARD"), found(rules(text))


def test_cvv_expiry(rules):
    spans = rules("Visa 4111 1111 1111 1111 exp 04/27 CVV 123")
    assert ents(spans, "CVV") == ["123"] and ents(spans, "CARD_EXPIRY") == ["04/27"]


# ---- phones -----------------------------------------------------------------------------------------
PHONES = ["(512) 555-0187", "512-555-0187", "512.555.0187", "512 555 0187", "+1 512 555 0187", "1-512-555-0187",
          "+1 (512) 555-0187", "(512)555-0187", "512-555-0187 ext. 214", "512-555-0187 x22", "+44 20 7946 0958",
          "+52 55 1234 5678", "+91 98765 43210", "Cell: 5125550187", "Phone #: 555-0187", "fax (713) 555-0144"]
PHONES += [fake.Gen(i).phone(random.choice(list(fake.AREA_CODES))) for i in range(40)]


@pytest.mark.parametrize("p", PHONES)
def test_phone_formats(rules, p):
    text = f"Contact: {p}"
    assert covers(rules(text), p.split(" ext")[0].split(" x")[0].replace("Cell: ", "").replace("Phone #: ", "").replace("fax ", ""), text) or ents(rules(text), "PHONE"), found(rules(text))


@pytest.mark.parametrize("text", ["Claim 2023-555-0187-01", "BP 120/80 HR 72", "flexion 45-90 degrees", "$1,234,567.89",
                                  "Rev 10.2.3456", "ISBN 0-306-40615-2", "page 555 line 12", "CPT 72148 99285 97110"])
def test_phone_negatives(rules, text):
    assert not ents(rules(text), "PHONE"), found(rules(text))


# ---- email / url / handles / network ------------------------------------------------------------------
@pytest.mark.parametrize("e", ["mary.j@gmail.com", "o'brien.k@law-firm.co.uk", "first+tag@sub.domain.org",
                               "J.SMITH@HOSPITAL.ORG", "x_y-z123@a.io"] + [fake.Gen(i).email("Ana", "Lopez") for i in range(15)])
def test_emails(rules, e):
    assert ents(rules(f"Email {e} today"), "EMAIL") == [e]


@pytest.mark.parametrize("text", ["john dot smith at gmail dot com", "jsmith [at] yahoo [dot] com", "jane(at)aol.com"])
def test_obfuscated_emails(rules, text):
    assert ents(rules(f"write to {text} please"), "EMAIL"), found(rules(text))


@pytest.mark.parametrize("text", ["Pay online at www.patientportal-pay.com", "look at google.com", "arrived at home.com"])
def test_not_obfuscated_email(rules, text):
    assert not ents(rules(text), "EMAIL")


@pytest.mark.parametrize("ip", ["192.168.10.25", "8.8.8.8", "2001:db8:85a3::8a2e:370:7334", "fe80::1ff:fe23:4567:890a"])
def test_ip(rules, ip):
    assert ents(rules(f"login from {ip} at 3pm"), "IP_ADDRESS") == [ip]


@pytest.mark.parametrize("text", ["version 1.2.3.4", "firmware v 10.0.0.1", "time 12:30:45", "section 4.2.1.3"])
def test_ip_negatives(rules, text):
    assert not ents(rules(text), "IP_ADDRESS")


@pytest.mark.parametrize("mac", ["00:1A:2B:3C:4D:5E", "00-1a-2b-3c-4d-5e", "001A.2B3C.4D5E"])
def test_mac(rules, mac):
    assert ents(rules(f"device MAC {mac}"), "MAC_ADDRESS")


@pytest.mark.parametrize("h", ["@jane_doe", "@mike.t99", "@Rk_1"])
def test_handles(rules, h):
    assert ents(rules(f"Her Instagram is {h} and she posts daily"), "USERNAME")


def test_social_url(rules):
    assert ents(rules("see https://facebook.com/jane.doe.5"), "USERNAME")


# ---- dates / DOB / age -------------------------------------------------------------------------------
DOB_FORMATS = ["01/15/1980", "1/5/80", "1980-01-15", "15/01/1980", "January 15, 1980", "Jan. 15, 1980", "15 January 1980",
               "15th of January, 1980", "15-JAN-1980", "Jan 15 1980", "19800115"]


@pytest.mark.parametrize("d", DOB_FORMATS)
@pytest.mark.parametrize("label", ["DOB:", "Date of Birth:", "D.O.B.", "Birthdate:", "born on", "DOB/Age:"])
def test_dob_formats(rules, d, label):
    if d == "19800115" and label in ("born on",):
        pytest.skip("compact form needs a date label")
    spans = rules(f"{label} {d}")
    assert ents(spans, "DATE_OF_BIRTH"), (label, d, found(spans))


def test_nearest_label_wins(rules):
    spans = rules("DOB: 11/29/1990   Visit Date: 04/21/2022", entities={"DATE_OF_BIRTH", "DATE"})
    assert ents(spans, "DATE_OF_BIRTH") == ["11/29/1990"]
    assert ents(spans, "DATE") == ["04/21/2022"]


def test_visit_date_on_line_below_dob_not_dob(rules):
    spans = rules("DOB: 11/29/1990\nAcct #: 4885425 Visit Date: 04/21/2022", entities={"DATE_OF_BIRTH", "DATE"})
    assert "04/21/2022" not in ents(spans, "DATE_OF_BIRTH")


def test_qa_dob(rules):
    assert ents(rules("10   Q.  And your date of birth?\n11   A.  March 18, 1989."), "DATE_OF_BIRTH")


@pytest.mark.parametrize("bad", ["02/30/1990", "13/13/1990", "00/10/1990", "1990-13-01", "February 30, 1990"])
def test_invalid_dates(rules, bad):
    assert not ents(rules(f"DOB: {bad}", entities={"DATE_OF_BIRTH", "DATE"}), "DATE_OF_BIRTH")


@pytest.mark.parametrize("text", ["a 43-year-old male", "age 43", "Age: 7", "aged 81", "43 y/o", "43yo", "6-month-old infant"])
def test_age(rules, text):
    assert ents(rules(text, entities={"AGE", "DEMOGRAPHIC"}), "AGE") or ents(rules(text, entities={"AGE", "DEMOGRAPHIC"}), "DEMOGRAPHIC")


@pytest.mark.parametrize("text", ["43-year-old Hispanic female", "a 7-year-old boy", "the 34-year-old Black man",
                                  "29 year old Asian woman"])
def test_demographic(rules, text):
    assert ents(rules(text, entities={"DEMOGRAPHIC", "AGE"}), "DEMOGRAPHIC")


# ---- vehicles / banking / crypto / international ------------------------------------------------------------
@pytest.mark.parametrize("i", range(30))
def test_vin_in_text(rules, i):
    make, model, wmi = fake.VEHICLES[i % len(fake.VEHICLES)]
    v = fake.vin(random.Random(i), wmi, 2015)
    assert ents(rules(f"the {make} {model} (VIN {v}) was towed"), "VIN") == [v]


@pytest.mark.parametrize("iban", ["GB82 WEST 1234 5698 7654 32", "DE89370400440532013000", "FR1420041010050500013M02606"])
def test_iban_in_text(rules, iban):
    assert ents(rules(f"wire to IBAN {iban} by Friday"), "IBAN")


@pytest.mark.parametrize("text", ["BTC 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "send to bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
                                  "ETH 0x52908400098527886E0F7030069857D2E4169EE7"])
def test_crypto(rules, text):
    assert ents(rules(text), "CRYPTO_WALLET")


@pytest.mark.parametrize("i", range(20))
def test_mbi(rules, i):
    m = fake.mbi(random.Random(i))
    assert ents(rules(f"Medicare MBI {m}"), "MEDICARE_ID")


def test_dea_with_context(rules):
    d = fake.dea(random.Random(1), "Patel")
    assert ents(rules(f"Dr. Patel DEA {d}", entities={"DEA_NUMBER", "PERSON"}), "DEA_NUMBER") == [d]


def test_npi_requires_context(rules):
    n = fake.npi(random.Random(3))
    assert ents(rules(f"Billing NPI: {n}", entities={"NPI"}), "NPI")
    assert not ents(rules(f"ref {n} filed", entities={"NPI"}), "NPI")


@pytest.mark.parametrize("text,ent", [("UK NI number AB 12 34 56 C", "NATIONAL_ID"), ("SIN: 046 454 286", "NATIONAL_ID"),
                                      ("IMEI 490154203237518", "DEVICE_ID"), ("EIN 59-1234567", "EIN"),
                                      ("GPS 30.267153, -97.743057", "GPS"), ("located at 30°16'2\"N 97°44'35\"W", "GPS")])
def test_misc_ids(rules, text, ent):
    assert ents(rules(text, entities={ent}), ent), found(rules(text, entities={ent}))


@pytest.mark.parametrize("text", ["Case No. 1:23-cv-04567-ALM", "Cause No. 2023-CA-004821", "Docket 4:22-cr-00123"])
def test_case_numbers(rules, text):
    assert ents(rules(text, entities={"CASE_NUMBER"}), "CASE_NUMBER")


# ---- secrets / spoken / transcripts -----------------------------------------------------------------
@pytest.mark.parametrize("text,val", [("my PIN is 4821", "4821"), ("password: hunter2!", "hunter2!"),
                                      ("gate code 1234#", "1234#"), ("passcode = Tr0ub4dor", "Tr0ub4dor"),
                                      ("the alarm code is 9090", "9090")])
def test_secrets(rules, text, val):
    assert val in ents(rules(text), "PASSWORD"), found(rules(text))


@pytest.mark.parametrize("text", ["Card Purchase With Pin 08/14 HEB", "password reset required", "PIN number field",
                                  "Password protected", "login from home"])
def test_secret_negatives(rules, text):
    assert not ents(rules(text), "PASSWORD"), found(rules(text))


@pytest.mark.parametrize("text,ent", [
    ("my social security number is five two three seven one nine nine two one", "SSN"),
    ("call me at five one two five five five zero one eight seven", "PHONE"),
    ("card number four one one one, one one one one, one one one one, one one one one", "CREDIT_CARD"),
])
def test_spoken_numbers(rules, text, ent):
    assert ents(rules(text), ent), found(rules(text))


@pytest.mark.parametrize("text,ent", [("her social security number is 523 -719921 and", "SSN"),
                                      ("phone number is 512 -555 -0187.", "PHONE"),
                                      ("my account number is 4839 2011 77", "BANK_ACCOUNT"),
                                      ("card is 4111 1111 1111 1111", "CREDIT_CARD")])
def test_transcript_numbers(rules, text, ent):
    assert ents(rules(text, transcript=True), ent), found(rules(text, transcript=True))


# ---- normalisation ----------------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["523​-71-9921", "523­-71-9921", "523﻿-71-9921", "５２３-７１-９９２１",
                                 "523‑71‑9921", "523−71−9921"])
def test_normtext_maps_back(raw, rules):
    text = f"SSN: {raw} end"
    spans = rules(text)
    ssn = [s for s in spans if s.entity == "SSN"]
    assert ssn and text[ssn[0].start:ssn[0].end] == raw


@pytest.mark.parametrize("raw,fixed", [("SSN 5Z3-7l-99Z1", "SSN 523-71-9921"), ("Ph: (5l2) 555-O187", "Ph: (512) 555-0187")])
def test_ocr_digit_variant(raw, fixed):
    assert ocr_digit_variant(raw) == fixed


def test_ocr_variant_leaves_words(rules):
    assert ocr_digit_variant("Bob Sims lives at Oslo") == "Bob Sims lives at Oslo"


def test_ocr_mode_finds_confused_ssn(rules):
    assert ents(rules("SSN: 5Z3-7l-99Z1", ocr_text=True), "SSN")
