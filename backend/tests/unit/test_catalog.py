"""Every entity a detector can emit exists in the catalog; profiles and codes are consistent."""
import re
from pathlib import Path

import pytest

from obscura.detection.text.entities import ENTITIES, EXEMPTION_CODES, PROFILES, entities_for_profile

SRC = Path(__file__).resolve().parents[2] / "obscura"


def emitted_entities():
    names = set()
    for p in (SRC / "detection" / "text").glob("*.py"):
        if p.name == "second_opinion.py":  # Presidio's own type names; their mapping is checked below
            continue
        for m in re.finditer(r'"([A-Z][A-Z_]{2,})"', p.read_text()):
            names.add(m.group(1))
    return names


def test_detectors_only_emit_known_entities():
    known = set(ENTITIES) | {"FACE", "LICENSE_PLATE", "PERSON_BODY", "VEHICLE", "SCREEN", "DOCUMENT_REGION"}
    suspicious = {n for n in emitted_entities() if n.isupper() and "_" in n and n not in known}
    # a handful of uppercase constants are not entities (e.g. ID_SHAPES); everything else must be catalogued
    allowed_non_entities = {"PAGE_SEP", "TEXT_PRESERVE_LIGATURES", "TEXT_PRESERVE_WHITESPACE", "SENSITIVE_CONTENT_ENTITIES",
                            "MEDIABOX_CLIP", "NON_NAME_WORDS", "ID_SHAPES", "UPPER_SUFFIXES", "WEAK_SUFFIXES"}
    assert not (suspicious - allowed_non_entities), suspicious - allowed_non_entities


def test_presidio_types_map_to_known_entities():
    from obscura.detection.text.second_opinion import ENTITY_MAP
    assert set(ENTITY_MAP.values()) <= set(ENTITIES)
    assert ENTITY_MAP["US_SSN"] == "SSN" and ENTITY_MAP["CREDIT_CARD"] == "CREDIT_CARD"


@pytest.mark.parametrize("key", list(ENTITIES))
def test_entity_well_formed(key):
    e = ENTITIES[key]
    assert e.key == key and e.label and e.description and e.category in ("PII", "PHI", "PCI", "LEGAL", "INDIRECT", "CUSTOM", "VISUAL")
    assert e.exemption in EXEMPTION_CODES


def test_default_profile_contains_core_identifiers():
    std = entities_for_profile("standard")
    for k in ("PERSON", "SSN", "PHONE", "EMAIL", "ADDRESS", "DATE_OF_BIRTH", "CREDIT_CARD", "BANK_ACCOUNT", "MRN",
              "DRIVERS_LICENSE", "LICENSE_PLATE", "INDIRECT_LOCATION", "MINOR"):
        assert k in std


def test_hipaa_profile_covers_18_identifiers():
    h = entities_for_profile("hipaa")
    for k in ("PERSON", "ADDRESS", "DATE", "PHONE", "EMAIL", "SSN", "MRN", "HEALTH_PLAN_ID", "BANK_ACCOUNT", "DRIVERS_LICENSE",
              "VIN", "LICENSE_PLATE", "DEVICE_ID", "URL", "IP_ADDRESS", "BIOMETRIC", "ID_NUMBER", "ZIP_CODE", "AGE"):
        assert k in h, k


def test_frcp_profile_is_minimal():
    assert entities_for_profile("frcp_5_2") == {"SSN", "ITIN", "EIN", "BANK_ACCOUNT", "CREDIT_CARD", "IBAN",
                                                "DATE_OF_BIRTH", "MINOR"}


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        entities_for_profile("nope")
