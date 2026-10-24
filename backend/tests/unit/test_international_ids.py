"""National IDs from other countries (gaps found by the Microsoft Presidio cross-check), and look-alike words."""
import pytest

from tests.conftest import covers


@pytest.mark.parametrize("text,value", [
    ("Singapore contact NRIC S1234567D was provided.", "S1234567D"),
    ("FIN: G1234567X (work pass holder)", "G1234567X"),
    ("Australian TFN 123 456 782 noted.", "123 456 782"),
    ("Tax file number: 123 456 782", "123 456 782"),
    ("PESEL 44051401359 listed in the Polish record.", "44051401359"),
    ("Patient BSN 123456782.", "123456782"),
    ("Codice fiscale RSSMRA85T10A562S", "RSSMRA85T10A562S"),
    ("NIE X1234567L on the lease.", "X1234567L"),
    ("NIF: 12345678Z", "12345678Z"),
    ("CPR number 010190-1234", "010190-1234"),
    ("Steuer-ID 12 345 678 901", "12 345 678 901"),
    ("Personnummer 19121212-1212", "19121212-1212"),
])
def test_national_ids(rules, text, value):
    spans = rules(text)
    assert covers(spans, value, text), [(s.entity, s.text) for s in spans]
    # "FIN" is also a hospital financial / encounter number, labelled MRN; either way it is redacted
    assert any(s.entity in ("NATIONAL_ID", "MRN") and value in s.text for s in spans)


@pytest.mark.parametrize("text", [
    "CPR was started at 10:42 and continued for 2 cycles.",
    "CPR 30:2 compressions, 2 rounds of epinephrine.",
    "CPR: 120 compressions per minute.",
    "The fin of the shark was injured.",
    "We will nie stop.",
    "Press PAN to rotate the view.",
    "The BSN team met on 4/12.",
    "Pain at the fin-shaped scar, 3 cm.",
])
def test_look_alikes_not_redacted(rules, text):
    assert not [s for s in rules(text) if s.entity == "NATIONAL_ID"]
