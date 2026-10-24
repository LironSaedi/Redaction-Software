"""Catalog of every entity type Obscura can detect.

The catalog is the single source of truth for labels, grouping, default exemption codes and
which regulatory profiles include each type. The UI, the API and the detectors all read it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntityType:
    key: str
    label: str
    category: str  # PII | PHI | PCI | LEGAL | INDIRECT | CUSTOM
    description: str
    default_on: bool = True
    exemption: str = "(b)(6)"
    hipaa: bool = False  # one of the 18 HIPAA Safe Harbor identifiers
    profiles: frozenset[str] = field(default_factory=frozenset)


_ALL = "standard hipaa foia cjis pci pi_litigation victim_privacy strict"


def _p(s: str) -> frozenset[str]:
    return frozenset(s.split())


ENTITIES: dict[str, EntityType] = {e.key: e for e in [
    # ---- Direct personal identifiers ---------------------------------------------------------
    EntityType("PERSON", "Person name", "PII", "Names of people, including partial and possessive mentions.",
               hipaa=True, profiles=_p("standard hipaa foia cjis pi_litigation victim_privacy strict")),
    EntityType("EMAIL", "Email address", "PII", "Email addresses.", hipaa=True, profiles=_p(_ALL)),
    EntityType("PHONE", "Phone / fax number", "PII", "Telephone and fax numbers (US and international).",
               hipaa=True, profiles=_p(_ALL)),
    EntityType("SSN", "Social Security number", "PII", "US SSNs, including spaced/dotted and partial (last-4) forms.",
               hipaa=True, profiles=_p(_ALL)),
    EntityType("ITIN", "ITIN", "PII", "US Individual Taxpayer Identification Number.", hipaa=True, profiles=_p(_ALL)),
    # a sole proprietor's EIN is as personal as an SSN (and FRCP 5.2 treats every taxpayer ID alike)
    EntityType("EIN", "Employer ID (EIN)", "PII", "US Employer Identification / federal tax ID.",
               profiles=_p("standard pci pi_litigation strict")),
    EntityType("DATE_OF_BIRTH", "Date of birth", "PII", "Dates identified as a birth date.", hipaa=True,
               profiles=_p(_ALL)),
    EntityType("DATE", "Date", "PHI", "Any other calendar date (admission, service, incident).",
               default_on=False, hipaa=True, profiles=_p("hipaa strict")),
    EntityType("AGE", "Age", "PII", "Stated ages (\"45-year-old\", \"age 45\").", default_on=False, hipaa=True,
               profiles=_p("hipaa victim_privacy strict")),
    EntityType("ADDRESS", "Street address", "PII", "Street addresses, PO boxes, unit numbers, city/state/ZIP lines.",
               hipaa=True, profiles=_p(_ALL)),
    EntityType("ZIP_CODE", "ZIP code", "PII", "Stand-alone ZIP / ZIP+4 codes.", default_on=False, hipaa=True,
               profiles=_p("hipaa strict")),
    EntityType("LOCATION", "City / place", "PII", "Cities, counties, neighbourhoods and other geographic names.",
               default_on=False, hipaa=True, profiles=_p("hipaa victim_privacy strict")),
    EntityType("GPS", "GPS coordinates", "PII", "Latitude/longitude pairs.", hipaa=True, profiles=_p(_ALL)),
    EntityType("IP_ADDRESS", "IP address", "PII", "IPv4 and IPv6 addresses.", hipaa=True, profiles=_p(_ALL)),
    EntityType("MAC_ADDRESS", "MAC address", "PII", "Hardware MAC addresses.", hipaa=True, profiles=_p(_ALL)),
    EntityType("URL", "URL", "PII", "Web addresses (personal pages, social profiles).", default_on=False,
               hipaa=True, profiles=_p("hipaa strict")),
    EntityType("USERNAME", "Username / handle", "PII", "Account usernames and social media handles.",
               profiles=_p(_ALL)),
    EntityType("PASSWORD", "Password / PIN", "PCI", "Passwords, passcodes and PINs.", profiles=_p(_ALL)),
    EntityType("DRIVERS_LICENSE", "Driver's license", "PII", "Driver's license / state ID numbers.", hipaa=True,
               profiles=_p(_ALL)),
    EntityType("PASSPORT", "Passport number", "PII", "Passport numbers.", hipaa=True, profiles=_p(_ALL)),
    EntityType("LICENSE_PLATE", "License plate", "PII", "Vehicle registration plates.", hipaa=True,
               profiles=_p(_ALL)),
    EntityType("VIN", "Vehicle ID (VIN)", "PII", "17-character vehicle identification numbers.", hipaa=True,
               profiles=_p(_ALL)),
    EntityType("NATIONAL_ID", "National ID", "PII", "Non-US national IDs (Canadian SIN, UK NINO, etc.).",
               hipaa=True, profiles=_p(_ALL)),
    EntityType("DEVICE_ID", "Device / serial number", "PII", "IMEI and device serial numbers.", hipaa=True,
               profiles=_p("hipaa cjis strict")),
    EntityType("BIOMETRIC", "Biometric identifier", "PII", "References to fingerprints, DNA profiles etc. with IDs.",
               default_on=False, hipaa=True, profiles=_p("hipaa cjis strict")),
    EntityType("SIGNATURE", "Signature", "PII", "Typed or /s/ signatures.", profiles=_p(_ALL)),
    EntityType("ID_NUMBER", "Other ID number", "PII",
               "Any other unique identifying number (employee, student, customer, client IDs).", hipaa=True,
               profiles=_p(_ALL)),

    # ---- Financial / PCI ---------------------------------------------------------------------
    EntityType("CREDIT_CARD", "Payment card number", "PCI", "Credit/debit card numbers (Luhn-validated).",
               hipaa=True, profiles=_p(_ALL)),
    EntityType("CVV", "Card security code", "PCI", "CVV / CVC codes.", profiles=_p(_ALL)),
    EntityType("CARD_EXPIRY", "Card expiry", "PCI", "Card expiration dates.", profiles=_p("pci strict standard")),
    EntityType("BANK_ACCOUNT", "Bank account number", "PCI", "Bank / financial account numbers.", hipaa=True,
               profiles=_p(_ALL)),
    EntityType("ROUTING_NUMBER", "Routing number", "PCI", "ABA routing transit numbers (checksum-validated).",
               profiles=_p(_ALL)),
    EntityType("IBAN", "IBAN", "PCI", "International bank account numbers (mod-97 validated).", hipaa=True,
               profiles=_p(_ALL)),
    EntityType("SWIFT_BIC", "SWIFT / BIC", "PCI", "Bank identifier codes.", default_on=False,
               profiles=_p("pci strict")),
    EntityType("CRYPTO_WALLET", "Crypto wallet", "PCI", "Bitcoin / Ethereum addresses (checksum-validated).",
               profiles=_p(_ALL)),

    # ---- Health / PHI ------------------------------------------------------------------------
    EntityType("MRN", "Medical record number", "PHI", "Medical record / patient / chart / encounter numbers.",
               hipaa=True, profiles=_p(_ALL)),
    EntityType("HEALTH_PLAN_ID", "Health plan / member ID", "PHI", "Insurance member, subscriber and group IDs.",
               hipaa=True, profiles=_p(_ALL)),
    EntityType("MEDICARE_ID", "Medicare (MBI)", "PHI", "Medicare Beneficiary Identifiers.", hipaa=True,
               profiles=_p(_ALL)),
    EntityType("NPI", "Provider NPI", "PHI", "National Provider Identifier (Luhn-validated).", default_on=False,
               profiles=_p("hipaa strict")),
    EntityType("DEA_NUMBER", "DEA number", "PHI", "DEA registration numbers (checksum-validated).",
               default_on=False, profiles=_p("hipaa strict")),
    EntityType("MEDICAL_CONDITION", "Medical condition", "PHI", "Diagnoses, conditions and ICD-10 codes.",
               default_on=False, exemption="(b)(6)", profiles=_p("victim_privacy strict")),
    EntityType("MEDICATION", "Medication", "PHI", "Prescribed drugs.", default_on=False,
               profiles=_p("victim_privacy medical_sensitive strict")),
    EntityType("MEDICAL_PROCEDURE", "Procedure / treatment", "PHI", "Surgeries, procedures, imaging and therapy.",
               default_on=False, profiles=_p("strict")),
    EntityType("LAB_RESULT", "Lab / test result", "PHI", "Lab values and test results (\"HbA1c 7.2%\", \"positive for\").",
               default_on=False, profiles=_p("medical_sensitive strict")),
    EntityType("MENTAL_HEALTH", "Mental health", "PHI", "Psychiatric diagnoses, therapy, suicidal ideation, "
               "psychotherapy notes.", default_on=False, exemption="HIPAA",
               profiles=_p("medical_sensitive victim_privacy gdpr_special strict")),
    EntityType("SUBSTANCE_USE", "Substance use (42 CFR Part 2)", "PHI",
               "Substance-use disorder diagnoses and treatment — federally protected under 42 CFR Part 2.",
               default_on=False, exemption="HIPAA", profiles=_p("medical_sensitive victim_privacy gdpr_special strict")),
    EntityType("SEXUAL_REPRODUCTIVE_HEALTH", "Sexual / reproductive health", "PHI",
               "HIV/STI status, pregnancy, abortion, contraception, fertility.", default_on=False, exemption="HIPAA",
               profiles=_p("medical_sensitive victim_privacy gdpr_special strict")),
    EntityType("GENETIC", "Genetic information", "PHI", "Genetic tests, carrier status, family genetic history (GINA).",
               default_on=False, exemption="HIPAA", profiles=_p("medical_sensitive gdpr_special strict")),
    EntityType("DISABILITY", "Disability", "PHI", "Disability status and accommodations.", default_on=False,
               profiles=_p("medical_sensitive gdpr_special strict")),
    EntityType("INJURY", "Injury", "PHI", "Injuries and body-part trauma (kept visible by default for PI work).",
               default_on=False, profiles=_p("strict")),

    # ---- Legal / law-enforcement --------------------------------------------------------------
    EntityType("CASE_NUMBER", "Case / docket number", "LEGAL", "Court case and docket numbers.", default_on=False,
               exemption="(b)(7)(A)", profiles=_p("cjis strict")),
    EntityType("CLAIM_NUMBER", "Claim number", "LEGAL", "Insurance claim numbers.", hipaa=True,
               profiles=_p("pi_litigation hipaa strict standard")),
    EntityType("POLICY_NUMBER", "Policy number", "LEGAL", "Insurance policy numbers.", hipaa=True,
               profiles=_p("pi_litigation hipaa strict standard")),
    # on by default: names of officers are redacted under the standard profile, so are their badge numbers, and
    # booking / inmate / report numbers lead straight back to the person (switch off for FOIA releases)
    EntityType("LAW_ENFORCEMENT_ID", "Badge / booking / report #", "LEGAL",
               "Officer badge numbers, booking, inmate and incident report numbers.",
               exemption="(b)(7)(C)", profiles=_p("standard cjis pi_litigation victim_privacy strict")),
    EntityType("PRIVILEGED", "Privileged content", "LEGAL",
               "Attorney-client communications and work product (privilege-marked passages).", default_on=False,
               exemption="PRIV", profiles=_p("privilege strict")),
    EntityType("MONEY", "Monetary amount", "LEGAL", "Dollar amounts — settlements, salaries, balances.",
               default_on=False, exemption="(b)(4)", profiles=_p("settlement strict")),
    EntityType("FINANCIAL_INFO", "Income / financial status", "LEGAL",
               "Salary, wages, income, net worth, debts, credit scores.", default_on=False, exemption="(b)(6)",
               profiles=_p("settlement strict")),
    EntityType("CRIMINAL_HISTORY", "Criminal history", "LEGAL", "Arrests, charges, convictions, incarceration.",
               default_on=False, exemption="(b)(7)(C)", profiles=_p("foia victim_privacy strict")),
    EntityType("IMMIGRATION_STATUS", "Immigration status", "LEGAL", "Visa, citizenship, asylum, DACA, deportation.",
               default_on=False, exemption="(b)(6)", profiles=_p("victim_privacy gdpr_special strict")),
    EntityType("MINOR", "Minor's identity", "LEGAL",
               "Names and identifiers of children (FRCP 5.2 requires initials only).", exemption="(b)(6)",
               profiles=_p("standard frcp_5_2 foia victim_privacy strict hipaa")),
    EntityType("SPECIAL_CATEGORY", "Religion / orientation / politics", "LEGAL",
               "GDPR special categories: religious belief, sexual orientation, political or union membership.",
               default_on=False, profiles=_p("gdpr_special strict")),

    # ---- Indirect identifiers (quasi-identifiers) -----------------------------------------------
    EntityType("INDIRECT_LOCATION", "Specific place", "INDIRECT",
               "A business, landmark or intersection specific enough to identify the people there "
               "(\"the McDonald's on Bank Street\").", exemption="(b)(7)(C)",
               profiles=_p("standard foia cjis victim_privacy strict")),
    EntityType("INDIRECT_ROLE", "Role / relationship", "INDIRECT",
               "Roles and relationships that single out a person (\"the night manager\", \"his daughter\").",
               exemption="(b)(7)(C)", profiles=_p("standard foia cjis victim_privacy strict")),
    EntityType("EMPLOYER", "Employer", "INDIRECT", "Where a person works.", exemption="(b)(6)",
               profiles=_p("standard foia cjis victim_privacy strict")),
    EntityType("ORGANIZATION", "Organization", "INDIRECT", "Other organisation names.", default_on=False,
               profiles=_p("strict")),
    EntityType("SCHOOL", "School", "INDIRECT", "Schools and universities attended.", exemption="(b)(6)",
               profiles=_p("standard foia victim_privacy strict")),
    EntityType("PHYSICAL_DESCRIPTOR", "Distinctive feature", "INDIRECT",
               "Tattoos, scars, birthmarks and other distinguishing marks.", exemption="(b)(7)(C)",
               profiles=_p("standard foia cjis victim_privacy strict")),
    EntityType("VEHICLE_DESCRIPTION", "Vehicle description", "INDIRECT",
               "Year/colour/make/model descriptions of a person's vehicle.", default_on=False,
               exemption="(b)(7)(C)", profiles=_p("cjis victim_privacy strict")),
    EntityType("DEMOGRAPHIC", "Demographic descriptor", "INDIRECT",
               "Age + sex/race descriptors (\"34-year-old Hispanic female\").", default_on=False,
               exemption="(b)(7)(C)", profiles=_p("victim_privacy strict")),

    # ---- User-defined ------------------------------------------------------------------------
    EntityType("CUSTOM", "Custom term", "CUSTOM", "Matches from search terms, custom lists, patterns and templates.",
               profiles=_p(_ALL)),
    # pictures inside documents (classified, listed for review, redactable whole)
    EntityType("IMAGE_ID_CARD", "ID / licence / insurance card", "VISUAL",
               "Picture of an ID, driver's licence or insurance card — redacted whole by default.", profiles=_p(_ALL)),
    EntityType("IMAGE_SIGNATURE", "Handwritten signature", "VISUAL", "Picture of a handwritten signature or initials.",
               profiles=_p(_ALL)),
    EntityType("IMAGE_PHOTO_PERSON", "Photo of a person", "VISUAL",
               "Photograph showing people (faces are also redacted individually).", exemption="(b)(7)(C)",
               profiles=_p(_ALL)),
    EntityType("IMAGE_PHOTO", "Photo", "VISUAL", "Scene, vehicle, injury or property photograph.", profiles=_p(_ALL)),
    EntityType("IMAGE_MEDICAL", "Medical image", "VISUAL", "X-ray, CT, MRI or ultrasound image.", hipaa=True,
               profiles=_p(_ALL)),
    EntityType("IMAGE_CHART", "Chart / graph", "VISUAL", "Chart or graph picture (its text is also read and redacted).",
               profiles=_p(_ALL)),
    EntityType("IMAGE_TABLE", "Table / form image", "VISUAL", "Picture of a table or form.", profiles=_p(_ALL)),
    EntityType("IMAGE_SCREENSHOT", "Screenshot", "VISUAL", "Screenshot of texts, a web page or an app.",
               profiles=_p(_ALL)),
    EntityType("IMAGE_DOCUMENT", "Picture of a document", "VISUAL", "Scanned or photographed document inserted as a picture.",
               profiles=_p(_ALL)),
    EntityType("IMAGE_GRAPHIC", "Logo / graphic", "VISUAL", "Logo, icon, stamp or other graphic.", profiles=_p(_ALL)),
]}

CATEGORIES = {
    "VISUAL": "Pictures: photos, exhibits, charts, cards",
    "PII": "Personal identifiers",
    "PHI": "Protected health information",
    "PCI": "Financial / payment data",
    "LEGAL": "Legal & law-enforcement",
    "INDIRECT": "Indirect identifiers",
    "CUSTOM": "Custom rules",
}

PROFILES = {
    "standard": "Standard PII (recommended default)",
    "hipaa": "HIPAA Safe Harbor (all 18 identifiers)",
    "foia": "FOIA / public records — (b)(6), (b)(7)(C)",
    "cjis": "CJIS / law enforcement",
    "pci": "PCI-DSS payment data",
    "pi_litigation": "Personal-injury litigation (medical & claims productions)",
    "victim_privacy": "Victim privacy / Marsy's Law",
    "frcp_5_2": "Court filing privacy (FRCP 5.2 — last-4 / year-only / initials)",
    "medical_sensitive": "Sensitive health (42 CFR Part 2, mental health, HIV, reproductive, genetic)",
    "privilege": "Privilege review (attorney-client / work product)",
    "settlement": "Confidential settlement & financial terms",
    "financial": "Financial records (bank, card, tax, payroll, loan, credit — GLBA)",
    "financial_last4": "Financial records for court filing (keep last 4 digits — FRCP 5.2)",
    "gdpr_special": "GDPR special categories",
    "strict": "Strict — everything",
}

# Partial-redaction rules (FRCP 5.2(a), Fed. R. Crim. P. 49.1, most state court equivalents):
# which characters of a value stay visible.
PARTIAL_RULES = {
    "frcp_5_2": {
        "SSN": "last4", "ITIN": "last4", "EIN": "last4", "BANK_ACCOUNT": "last4", "CREDIT_CARD": "last4",
        "IBAN": "last4", "DATE_OF_BIRTH": "year", "MINOR": "initials",
    },
    # everything the financial profile redacts, but account-style numbers keep their last four digits
    "financial_last4": {
        "SSN": "last4", "ITIN": "last4", "EIN": "last4", "BANK_ACCOUNT": "last4", "CREDIT_CARD": "last4",
        "IBAN": "last4", "DATE_OF_BIRTH": "year", "MINOR": "initials",
    },
}

# FOIA exemption codes and common state equivalents, used to annotate every redaction.
EXEMPTION_CODES = {
    "(b)(1)": "Classified national defense or foreign relations information",
    "(b)(2)": "Internal personnel rules and practices",
    "(b)(3)": "Information exempted by other federal statutes",
    "(b)(4)": "Trade secrets / confidential commercial information",
    "(b)(5)": "Privileged inter- or intra-agency communications",
    "(b)(6)": "Personnel, medical and similar files — clearly unwarranted invasion of privacy",
    "(b)(7)(A)": "Law enforcement — could interfere with enforcement proceedings",
    "(b)(7)(B)": "Law enforcement — would deprive a person of a fair trial",
    "(b)(7)(C)": "Law enforcement — unwarranted invasion of personal privacy",
    "(b)(7)(D)": "Law enforcement — confidential source",
    "(b)(7)(E)": "Law enforcement — techniques and procedures",
    "(b)(7)(F)": "Law enforcement — endanger life or physical safety",
    "(b)(8)": "Financial institution examination reports",
    "(b)(9)": "Geological and geophysical information",
    "HIPAA": "Protected health information — 45 CFR 164.514",
    "FERPA": "Education records — 20 U.S.C. 1232g",
    "PCI": "Cardholder data — PCI-DSS",
    "PRIV": "Attorney-client privilege / work product",
    "MARSY": "Victim privacy — Marsy's Law",
}


def entities_for_profile(profile: str | None) -> set[str]:
    """Entity keys enabled for a profile. ``None``/"default" → every default-on entity."""
    if not profile or profile == "default":
        return {k for k, e in ENTITIES.items() if e.default_on}
    if profile == "strict":
        return set(ENTITIES)
    if profile == "hipaa":
        return {k for k, e in ENTITIES.items() if e.hipaa or "hipaa" in e.profiles}
    if profile == "standard":
        return {k for k, e in ENTITIES.items() if e.default_on}
    if profile == "frcp_5_2":
        return {"SSN", "ITIN", "EIN", "BANK_ACCOUNT", "CREDIT_CARD", "IBAN", "DATE_OF_BIRTH", "MINOR"}
    if profile in ("financial", "financial_last4"):
        # the standard set plus financial status statements ("credit score 712", "net worth") and case numbers
        # (child support, bankruptcy, collections identify the person); amounts stay visible
        return {k for k, e in ENTITIES.items() if e.default_on} | {"FINANCIAL_INFO", "CASE_NUMBER"}
    if profile in ("medical_sensitive", "privilege", "settlement", "gdpr_special"):
        # additive profiles: the standard set plus their own categories
        return {k for k, e in ENTITIES.items() if e.default_on or profile in e.profiles}
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    return {k for k, e in ENTITIES.items() if profile in e.profiles}
