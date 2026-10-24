"""Long, realistic personal-injury case files with gold-standard PII labels.

Every PII value is written through ``Doc.p(entity, value)`` so its exact offsets are recorded.
Plain text goes through ``Doc.t`` and *hard negatives* (things that look like identifiers but are
not — CPT codes, NDC codes, page numbers, statute citations, ROM degrees, invoice numbers) through
``Doc.n`` so over-redaction can be measured.

Gold conventions
----------------
* honorifics/titles are not part of PERSON spans ("Dr. " + PERSON "Patel")
* every date that is not a DOB is DATE (off in the standard profile, on for HIPAA)
* facility / insurer / law-firm names are ORGANIZATION and marked optional (redacting them is
  neither required nor penalised)
* children are PERSON with ``minor=True``
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from .fake import (BANKS, EMPLOYERS, INSURERS, Address, Gen, Person, card, dea, ein, fmt_date, iban_de, npi)


@dataclass
class Gold:
    start: int
    end: int
    entity: str
    value: str
    optional: bool = False
    minor: bool = False


class Doc:
    def __init__(self, kind: str, title: str):
        self.kind, self.title = kind, title
        self._parts: list[str] = []
        self._len = 0
        self.gold: list[Gold] = []
        self.neg: list[tuple[int, int, str, str]] = []
        self.page_header = None

    def t(self, s: str) -> "Doc":
        self._parts.append(s)
        self._len += len(s)
        return self

    def p(self, entity: str, value: str, optional: bool = False, minor: bool = False) -> "Doc":
        if not value:
            return self
        s = self._len
        self.t(value)
        self.gold.append(Gold(s, self._len, entity, value, optional, minor))
        return self

    def n(self, value: str, kind: str = "control") -> "Doc":
        s = self._len
        self.t(value)
        self.neg.append((s, self._len, kind, value))
        return self

    def nl(self, k: int = 1) -> "Doc":
        return self.t("\n" * k)

    def kv(self, label: str, entity: str | None, value: str, end: str = "\n", optional: bool = False) -> "Doc":
        self.t(f"{label}: ")
        if entity:
            self.p(entity, value, optional)
        else:
            self.t(value)
        return self.t(end)

    def page(self) -> "Doc":
        self.t("\n\f")
        if self.page_header:
            self.page_header(self)
        return self

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "title": self.title, "text": self.text,
                "gold": [g.__dict__ for g in self.gold],
                "negatives": [{"start": s, "end": e, "kind": k, "value": v} for s, e, k, v in self.neg]}


# ---------------------------------------------------------------------------------------------
# Case context
# ---------------------------------------------------------------------------------------------

@dataclass
class Provider:
    facility: str
    address: Address
    phone: str
    fax: str
    npi: str
    tax_id: str
    doctor_first: str
    doctor_last: str
    doctor_npi: str
    specialty: str


@dataclass
class Case:
    g: Gen
    client: Person
    defendant: Person
    witnesses: list[Person]
    officer_first: str
    officer_last: str
    badge: str
    adjuster_first: str
    adjuster_last: str
    adjuster_phone: str
    adjuster_email: str
    insurer: str
    claim_no: str
    policy_no: str
    client_insurer: str
    client_policy: str
    attorney_first: str
    attorney_last: str
    bar_no: str
    firm: str
    firm_address: Address
    firm_phone: str
    firm_fax: str
    firm_email: str
    paralegal_first: str
    paralegal_last: str
    providers: list[Provider]
    incident: date
    incident_time: str
    business: str
    street1: str
    street2: str
    city: str
    state: str
    case_no: str
    court: str
    report_no: str
    crash_id: str
    supervisor_first: str
    supervisor_last: str
    extra: dict = field(default_factory=dict)


FACILITIES = [("St. David's Medical Center", "Emergency Medicine"), ("Memorial Hermann Hospital", "Emergency Medicine"),
              ("Baylor Scott & White Medical Center", "Emergency Medicine"), ("Texas Orthopedic Specialists", "Orthopedic Surgery"),
              ("Lone Star Spine & Pain Institute", "Pain Management"), ("Advanced Physical Therapy of Austin", "Physical Therapy"),
              ("Precision Imaging Center", "Radiology"), ("Capital Chiropractic & Wellness", "Chiropractic"),
              ("NeuroCare Associates", "Neurology"), ("Hill Country Behavioral Health", "Psychology")]
BUSINESSES = ["McDonald's", "Walgreens", "Shell station", "H-E-B", "Whataburger", "7-Eleven", "Starbucks",
              "Home Depot", "Taco Bell", "CVS", "Dollar General", "Waffle House", "Circle K", "Walmart Supercenter"]


def make_case(g: Gen) -> Case:
    r = g.r
    city = g.city()
    client = g.person(city=city, with_family=True, min_age=22, max_age=68)
    defendant = g.person(city=city)
    witnesses = [g.person(city=city) for _ in range(r.randint(1, 3))]
    of, _, ol, _ = g.name()
    af, _, al, _ = g.name()
    atf, _, atl, _ = g.name()
    pf, _, pl, _ = g.name()
    sf, _, sl, _ = g.name()
    providers = []
    for fac, spec in r.sample(FACILITIES, 6):
        df, _, dl, _ = g.name()
        providers.append(Provider(fac, g.address(city), g.phone(city[1]), g.phone(city[1]), npi(r), ein(r), df, dl,
                                  npi(r), spec))
    s1 = f"{r.choice(['Bank', 'Main', 'Elm', 'Lamar', 'Congress', 'Oak', 'Market', 'Church', 'Burnet', 'Cameron'])} " \
         f"{r.choice(['Street', 'Avenue', 'Boulevard', 'Road'])}"
    s2 = f"{r.choice(['5th', '12th', 'Riverside', 'Parmer', 'Maple', 'Washington', 'Airport', 'Cedar'])} " \
         f"{r.choice(['Street', 'Avenue', 'Lane', 'Drive'])}"
    firm_names = [f"{atl} & Associates, PLLC", f"The {atl} Law Firm, P.C.", f"{atl}, {pl} & Partners LLP"]
    return Case(
        g=g, client=client, defendant=defendant, witnesses=witnesses, officer_first=of, officer_last=ol,
        badge=str(r.randint(1000, 99999)), adjuster_first=af, adjuster_last=al, adjuster_phone=g.phone(city[1]),
        adjuster_email=g.email(af, al).split("@")[0] + "@" + r.choice(["statefarm.com", "geico.com", "progressive.com",
                                                                        "allstate.com", "libertymutual.com"]),
        insurer=r.choice(INSURERS), claim_no=g.claim_no(), policy_no=g.policy_no(city[1]),
        client_insurer=r.choice(INSURERS), client_policy=g.policy_no(city[1]),
        attorney_first=atf, attorney_last=atl, bar_no=str(r.randint(10 ** 7, 10 ** 8 - 1)), firm=r.choice(firm_names),
        firm_address=g.address(city), firm_phone=g.phone(city[1]), firm_fax=g.phone(city[1]),
        firm_email=f"{atf[0].lower()}{atl.lower()}@{atl.lower()}law.com".replace("'", "").replace(" ", ""),
        paralegal_first=pf, paralegal_last=pl, providers=providers,
        incident=g.date_between(date(2021, 1, 1), date(2023, 10, 1)),
        incident_time=f"{r.randint(1, 12)}:{r.randint(0, 59):02d} {r.choice(['a.m.', 'p.m.', 'AM', 'PM'])}",
        business=r.choice(BUSINESSES), street1=s1, street2=s2, city=city[0], state=city[1],
        case_no=g.case_no(), court=f"{r.choice(['Travis', 'Harris', 'Dallas', 'Bexar', 'Tarrant', 'Hidalgo'])} County District Court",
        report_no=g.report_no(), crash_id=str(r.randint(10 ** 7, 10 ** 8 - 1)), supervisor_first=sf, supervisor_last=sl)


def _name(d: Doc, first: str, last: str, minor: bool = False, style: str = "full") -> None:
    if style == "last_first":
        d.p("PERSON", f"{last.upper()}, {first.upper()}", minor=minor)
    elif style == "last":
        d.p("PERSON", last, minor=minor)
    elif style == "first":
        d.p("PERSON", first, minor=minor)
    else:
        d.p("PERSON", f"{first} {last}", minor=minor)


def _addr(d: Doc, a: Address, multiline: bool = False) -> None:
    if multiline:
        l1, l2 = a.lines()
        d.p("ADDRESS", f"{l1}\n{l2}")
    else:
        d.p("ADDRESS", a.one_line())


def _date(d: Doc, dt: date, r: random.Random, dob: bool = False, style: str | None = None) -> None:
    d.p("DATE_OF_BIRTH" if dob else "DATE", fmt_date(dt, r, style))


# ---------------------------------------------------------------------------------------------
# 1. Police crash report
# ---------------------------------------------------------------------------------------------

def crash_report(c: Case) -> Doc:
    g, r = c.g, c.g.r
    d = Doc("crash_report", "Texas Peace Officer's Crash Report")
    d.t("TEXAS PEACE OFFICER'S CRASH REPORT (Form CR-3 1/1/23)\n")
    d.t("Crash ID: ").p("LAW_ENFORCEMENT_ID", c.crash_id).t("    Agency Case No.: ").p("LAW_ENFORCEMENT_ID", c.report_no).nl()
    d.t("Reporting Agency: ").p("ORGANIZATION", f"{c.city} Police Department", optional=True).t("    ORI: ").n("TX2270100", "ori").nl()
    d.t("Crash Date: ")
    _date(d, c.incident, r, style="mdy0")
    d.t("   Crash Time: ").t(c.incident_time).t("   County: ").p("LOCATION", c.court.split(" County")[0], optional=True).nl()
    d.t("Location: ").p("INDIRECT_LOCATION", f"the {c.business} at {c.street1} and {c.street2}").nl()
    d.t("Roadway: ").t(c.street1.upper()).t("   Intersecting: ").t(c.street2.upper()).t("   Speed Limit: ").n("35 MPH", "speed").nl()
    d.t("Latitude/Longitude: ").p("GPS", f"{r.uniform(29.2, 32.9):.6f}, {-r.uniform(95.1, 98.9):.6f}").nl(2)
    units = [("1", c.defendant, True), ("2", c.client, False)]
    for unit, p, at_fault in units:
        v = p.vehicle
        d.t(f"UNIT {unit} — MOTOR VEHICLE\n")
        d.kv("Driver Name (Last, First, Middle)", "PERSON", f"{p.last.upper()}, {p.first.upper()} {p.middle[:1].upper()}".strip())
        d.t("Driver Address: ")
        _addr(d, p.address)
        d.nl()
        d.t("DOB: ")
        _date(d, p.dob, r, dob=True, style="mdy0")
        d.t("   Sex: ").t(p.sex).t("   DL/ID Type: ").t("DL").t("   DL/ID State: ").t(p.dl_state).t("   DL/ID #: ").p("DRIVERS_LICENSE", p.dl).nl()
        d.t("Driver Phone: ").p("PHONE", p.cell).nl()
        d.t("Vehicle: ").p("VEHICLE_DESCRIPTION", f"{v.year} {v.make} {v.model}").t("   Color: ").t(v.color.upper()).nl()
        d.t("VIN: ").p("VIN", v.vin).t("   LP State: ").t(v.plate_state).t("   License Plate #: ").p("LICENSE_PLATE", v.plate).nl()
        d.t("Owner/Lessee: ")
        _name(d, p.first, p.last)
        d.t(", ")
        _addr(d, p.address)
        d.nl()
        ins = c.insurer if at_fault else c.client_insurer
        pol = c.policy_no if at_fault else c.client_policy
        d.t("Fin. Resp. Type: ").t("Proof of Liability Insurance").t("   Fin. Resp. Name: ").p("ORGANIZATION", ins, optional=True).nl()
        d.t("Fin. Resp. Policy #: ").p("POLICY_NUMBER", pol).t("   Fin. Resp. Phone: ").p("PHONE", g.phone(c.state)).nl()
        d.t("Damage Rating: ").n("FD-4" if at_fault else "BR-5", "damage").t("   Vehicle Towed By: ").t(r.choice(["Austin Wrecker Service", "AAA Towing", "not towed"])).nl()
        d.t("Contributing Factors: ").n(r.choice(["67 - Following Too Closely", "22 - Failed to Yield ROW", "38 - Inattention"]), "factor").nl(2)
    d.t("PERSONS — INJURY CODES\n")
    d.t("Unit 2, Seat 11 (driver): ")
    _name(d, c.client.first, c.client.last)
    d.t(", Injury Severity: B — Suspected Minor Injury, transported by EMS to ").p("ORGANIZATION", c.providers[0].facility, optional=True).nl()
    for ch in c.client.children[:2]:
        d.t("Unit 2, Seat 21 (rear passenger): ")
        _name(d, ch.first, ch.last, minor=True)
        d.t(", Age: ").p("AGE", str(ch.age(c.incident))).t(", Injury Severity: C — Possible Injury").nl()
    d.nl()
    d.t("WITNESSES\n")
    for w in c.witnesses:
        d.t("Name: ")
        _name(d, w.first, w.last)
        d.t("   Address: ")
        _addr(d, w.address)
        d.t("   Phone: ").p("PHONE", w.cell).nl()
    d.page()
    d.t("INVESTIGATOR'S NARRATIVE OPINION OF WHAT HAPPENED\n\n")
    v1, v2 = c.defendant.vehicle, c.client.vehicle
    d.t("Unit 1 (").p("VEHICLE_DESCRIPTION", v1.desc()).t(") was traveling northbound on ").t(c.street1).t(
        " in the inside lane. Unit 2 (").p("VEHICLE_DESCRIPTION", v2.desc()).t(") was stopped for a red signal at the intersection with ").t(
        c.street2).t(". Unit 1 failed to control speed and struck Unit 2 in the rear. Unit 2 was pushed forward into the crosswalk in front of ").p(
        "INDIRECT_LOCATION", f"the {c.business} on {c.street1}").t(". ")
    d.t("Driver of Unit 1, ")
    _name(d, c.defendant.first, c.defendant.last)
    d.t(", stated he looked down at his phone. Driver of Unit 2, ")
    _name(d, c.client.first, c.client.last)
    d.t(", complained of neck and lower back pain. ")
    w = c.witnesses[0]
    d.t("Witness ")
    _name(d, w.first, w.last)
    d.t(", ").p("INDIRECT_ROLE", f"the night manager at the {c.business}").t(", stated she saw Unit 1 traveling at a high rate of speed. ")
    d.t("The witness provided video from the store's exterior camera. ")
    if c.client.children:
        ch = c.client.children[0]
        d.t("A rear passenger in Unit 2, ").p("INDIRECT_ROLE", f"the driver's {ch.age(c.incident)}-year-old child").t(" ")
        _name(d, ch.first, ch.last, minor=True)
        d.t(", was evaluated by EMS on scene. ")
    d.t("EMS ").n("Medic 14", "unit").t(" transported the driver of Unit 2. Unit 1 driver was issued citation ").p(
        "LAW_ENFORCEMENT_ID", f"C{r.randint(10 ** 7, 10 ** 8 - 1)}").t(" for Failed to Control Speed (Transp. Code ").n(
        "§ 545.351", "statute").t(").\n\n")
    d.t("Investigating Officer: Officer ")
    _name(d, c.officer_first, c.officer_last)
    d.t("   Badge #: ").p("LAW_ENFORCEMENT_ID", c.badge).t("   ID: ").p("LAW_ENFORCEMENT_ID", str(r.randint(100000, 999999))).nl()
    d.t("Date Report Completed: ")
    _date(d, c.incident + timedelta(days=r.randint(0, 6)), r)
    d.nl()
    return d


# ---------------------------------------------------------------------------------------------
# 2. Emergency department record
# ---------------------------------------------------------------------------------------------

PMH = ["hypertension", "type 2 diabetes", "asthma", "hyperlipidemia", "GERD", "migraines", "hypothyroidism",
       "anxiety", "depression", "obesity", "sleep apnea"]
SENSITIVE_HX = [("SUBSTANCE_USE", "alcohol use disorder, in remission"), ("MENTAL_HEALTH", "major depressive disorder"),
                ("SEXUAL_REPRODUCTIVE_HEALTH", "HIV positive, on Biktarvy"), ("MENTAL_HEALTH", "PTSD"),
                ("SUBSTANCE_USE", "opioid use disorder on Suboxone maintenance"), ("MENTAL_HEALTH", "bipolar disorder"),
                ("SEXUAL_REPRODUCTIVE_HEALTH", "currently 14 weeks pregnant")]
MEDS = ["lisinopril 10 mg daily", "metformin 500 mg BID", "atorvastatin 20 mg nightly", "albuterol inhaler PRN",
        "sertraline 50 mg daily", "levothyroxine 75 mcg daily", "omeprazole 20 mg daily", "gabapentin 300 mg TID",
        "cyclobenzaprine 10 mg TID PRN", "ibuprofen 800 mg TID", "hydrocodone/APAP 5/325 q6h PRN"]


def ed_record(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    prov = c.providers[0]
    mrn = g.mrn()
    acct = str(r.randint(10 ** 8, 10 ** 9 - 1))
    d = Doc("ed_record", "Emergency Department Record")
    visit = c.incident

    def header(doc: Doc) -> None:
        doc.p("ORGANIZATION", prov.facility, optional=True).t(" — Emergency Department\n")
        doc.t("Patient: ").p("PERSON", p.last_first).t("    MRN: ").p("MRN", mrn).t("    DOB: ").p("DATE_OF_BIRTH", fmt_date(p.dob, style="mdy0")).nl()
        doc.t("Acct #: ").p("MRN", acct).t("    Visit Date: ").p("DATE", fmt_date(visit, style="mdy0")).t("    Attending: Dr. ").p(
            "PERSON", f"{prov.doctor_first} {prov.doctor_last}").nl()
        doc.t("-" * 90).nl()

    d.page_header = header
    header(d)
    d.t("\nREGISTRATION / FACE SHEET\n")
    d.kv("Patient Name", "PERSON", f"{p.first} {p.middle} {p.last}".replace("  ", " "))
    d.t("Address: ")
    _addr(d, p.address, multiline=True)
    d.nl()
    d.kv("Home Phone", "PHONE", p.phone)
    d.kv("Cell Phone", "PHONE", p.cell)
    d.kv("Email", "EMAIL", p.email)
    d.kv("SSN", "SSN", p.ssn)
    d.t("Sex: ").t("Male" if p.sex == "M" else "Female").t("    Marital Status: Married    Language: English\n")
    d.t("Employer: ").p("EMPLOYER", p.employer).t("    Occupation: ").t(p.job).nl()
    d.t("Emergency Contact: ")
    if p.spouse:
        _name(d, p.spouse.first, p.spouse.last)
        d.t(" (").p("INDIRECT_ROLE", "spouse", optional=True).t(")   Phone: ").p("PHONE", p.spouse.cell).nl()
    else:
        d.t("None listed\n")
    d.t("Primary Insurance: ").p("ORGANIZATION", p.health_plan, optional=True).nl()
    d.kv("Member ID", "HEALTH_PLAN_ID", p.member_id)
    d.kv("Group #", "HEALTH_PLAN_ID", p.group_no)
    d.t("Subscriber: ")
    _name(d, p.first, p.last)
    d.t("    Relationship: Self\n")
    d.t("Secondary: Auto PIP — ").p("ORGANIZATION", c.client_insurer, optional=True).t("  Claim #: ").p("CLAIM_NUMBER", g.claim_no()).nl()
    d.page()
    d.t("TRIAGE\n")
    d.t("Arrival: EMS (").n("Medic 14", "unit").t(")   Arrival Time: ").t(f"{r.randint(13, 23)}:{r.randint(10, 59)}").t("   Acuity: ESI ").n("3", "esi").nl()
    d.t("Vitals: BP ").n(f"{r.randint(118, 162)}/{r.randint(70, 98)}", "vitals").t("  HR ").n(str(r.randint(70, 110)), "vitals").t(
        "  RR 18  Temp 98.4 F  SpO2 98% RA  Pain 8/10\n")
    d.t("Chief Complaint: neck pain, low back pain, headache after motor vehicle collision\n\n")
    d.t("HISTORY OF PRESENT ILLNESS\n")
    age = p.age(visit)
    d.t("Mrs. " if p.sex == "F" else "Mr. ").p("PERSON", p.last).t(" is a ").p("DEMOGRAPHIC", f"{age}-year-old {'female' if p.sex == 'F' else 'male'}").t(
        " who presents by EMS after being the restrained driver of a vehicle that was rear-ended at a red light near ").p(
        "INDIRECT_LOCATION", f"the {c.business} on {c.street1}").t(". Airbags did not deploy. She denies loss of consciousness. "
        if p.sex == "F" else ". Airbags did not deploy. He denies loss of consciousness. ")
    d.t("Patient reports immediate onset of neck pain radiating to the right trapezius and low back pain radiating to the left buttock. ")
    if p.children:
        ch = p.children[0]
        d.p("INDIRECT_ROLE", "Patient's daughter" if ch.sex == "F" else "Patient's son", optional=True).t(", ")
        _name(d, ch.first, ch.last, minor=True)
        d.t(" (age ").p("AGE", str(ch.age(visit))).t("), was in the back seat and is being seen in the pediatric ED. ")
    d.t("Patient works as a ").t(p.job).t(" at ").p("EMPLOYER", p.employer).t(" and is worried about missing work.\n\n")
    d.t("PAST MEDICAL HISTORY: ")
    pmh = r.sample(PMH, 3)
    for i, cond in enumerate(pmh):
        d.p("MEDICAL_CONDITION", cond)
        d.t(", " if i < len(pmh) - 1 else "")
    sens = r.choice(SENSITIVE_HX)
    d.t(", ").p(sens[0], sens[1]).t(".\n")
    d.t("MEDICATIONS: ")
    meds = r.sample(MEDS, 3)
    for i, m in enumerate(meds):
        d.p("MEDICATION", m)
        d.t("; " if i < 2 else "\n")
    d.t("ALLERGIES: Penicillin (hives)\n")
    d.t("SOCIAL HISTORY: Lives with ").p("INDIRECT_ROLE", "her husband" if p.sex == "F" else "his wife", optional=True).t(" and children at ")
    _addr(d, p.address)
    d.t(". Smokes 1/2 ppd. Drinks socially. Denies illicit drug use.\n\n")
    d.t("PHYSICAL EXAM\n")
    d.t("General: alert, oriented x3, in moderate distress due to pain.\n")
    d.t("Neck: tenderness over C5-C6 paraspinals bilaterally, range of motion limited, flexion ").n("30 degrees", "rom").t(", extension ").n("20 degrees", "rom").t(". No midline step-off.\n")
    d.t("Back: tenderness L4-S1 paraspinal musculature, negative straight leg raise at ").n("60°", "rom").t(".\n")
    d.t("Neuro: strength 5/5 bilateral upper and lower extremities, sensation intact.\n\n")
    d.t("IMAGING\n")
    d.t("CT cervical spine without contrast (CPT ").n("72125", "cpt").t("): No acute fracture. Straightening of the normal lordosis consistent with muscle spasm.\n")
    d.t("X-ray lumbar spine 2 views (CPT ").n("72100", "cpt").t("): No acute osseous abnormality.\n\n")
    d.t("LABS: ").p("LAB_RESULT", f"glucose {r.randint(90, 180)} mg/dL").t(", urine pregnancy negative.\n\n")
    d.t("ASSESSMENT\n")
    d.t("1. Cervical strain, initial encounter (ICD-10 ").n("S13.4XXA", "icd").t(")\n")
    d.t("2. Lumbar strain, initial encounter (ICD-10 ").n("S39.012A", "icd").t(")\n")
    d.t("3. Post-traumatic headache (ICD-10 ").n("G44.309", "icd").t(")\n\n")
    d.t("PLAN\n")
    d.t("Toradol 30 mg IM given in ED. Discharged with cyclobenzaprine 10 mg #20 and ibuprofen 800 mg #30 (NDC ").n(
        "0093-0058-01", "ndc").t("). Follow up with PCP or orthopedics in 3-5 days. Return precautions reviewed. Work note provided for 3 days.\n\n")
    d.t("Electronically signed by: ")
    _name(d, prov.doctor_first, prov.doctor_last)
    d.t(", MD   NPI: ").p("NPI", prov.doctor_npi).t("   ")
    _date(d, visit, r)
    d.nl()
    return d


# ---------------------------------------------------------------------------------------------
# 3. Physical therapy notes — one page per visit (long)
# ---------------------------------------------------------------------------------------------

def pt_notes(c: Case, visits: int) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    prov = next(x for x in c.providers if "Physical" in x.facility or x.specialty == "Physical Therapy") \
        if any(x.specialty == "Physical Therapy" for x in c.providers) else c.providers[2]
    mrn = g.mrn()
    d = Doc("pt_notes", "Physical Therapy Daily Notes")
    start = c.incident + timedelta(days=r.randint(5, 20))
    therapist_first, _, therapist_last, _ = g.name()
    state = {"dos": start}

    def header(doc: Doc) -> None:
        doc.p("ORGANIZATION", prov.facility, optional=True).t("  |  ")
        doc.p("ADDRESS", prov.address.one_line()).t("  |  Ph ").p("PHONE", prov.phone).t("  Fax ").p("PHONE", prov.fax).nl()
        doc.t("PATIENT: ").p("PERSON", f"{p.first} {p.last}").t("   DOB: ").p("DATE_OF_BIRTH", fmt_date(p.dob, style="mdy")).t(
            "   Chart #: ").p("MRN", mrn).nl()
        doc.t("=" * 88).nl()

    d.page_header = header
    header(d)
    goals = ["return to full duty as a " + p.job, "lift 40 lbs floor to waist", "sit > 60 minutes without pain",
             "sleep through the night", "drive without neck pain", "play with children without pain"]
    pain = r.randint(6, 8)
    for v in range(visits):
        if v:
            d.page()
        dos = state["dos"]
        d.t(f"DAILY NOTE — Visit {v + 1} of {visits}    Date of Service: ").p("DATE", fmt_date(dos, style="mdy0")).nl()
        d.t("Diagnosis: M54.2 cervicalgia; M54.50 low back pain; S13.4XXD\n")
        d.t("Referring Provider: Dr. ").p("PERSON", c.providers[1].doctor_last).t("    Insurance: Auto PIP / LOP\n\n")
        d.t("SUBJECTIVE: ")
        pain = max(1, min(9, pain + r.choice([-1, -1, 0, 0, 1])))
        subj = r.choice([
            lambda: (d.t(f"Patient reports pain {pain}/10 today. States she tried to help ").p("INDIRECT_ROLE", "her son", optional=True)
                     .t(" with homework and had increased neck pain after 20 minutes. ")),
            lambda: (d.t(f"Pt rates pain {pain}/10. Reports a flare-up after working a double shift at ").p("EMPLOYER", p.employer)
                     .t(". ").t("Supervisor ").p("PERSON", f"{c.supervisor_first} {c.supervisor_last}").t(" has put pt on light duty. ")),
            lambda: (d.t(f"Pain {pain}/10. Pt states she was unable to attend church at ").p(
                "INDIRECT_LOCATION", f"{r.choice(['Grace', 'First Baptist', 'St. Mary', 'New Hope'])} Church on {c.street2}")
                     .t(" on Sunday due to pain sitting in the pews. ")),
            lambda: (d.t(f"Reports pain {pain}/10 and difficulty sleeping. ").t("Spouse ").p("PERSON", p.spouse.first if p.spouse else p.first)
                     .t(" has been helping with household chores. ")),
            lambda: (d.t(f"Patient reports {pain}/10 pain. Missed last visit because ").p("INDIRECT_ROLE", "her mother", optional=True).t(
                " was admitted to the hospital. Can be reached at ").p("PHONE", p.cell).t(" for scheduling. ")),
            lambda: d.t(f"Pain {pain}/10, improving with home exercise program. Compliant with HEP 5x/week. "),
        ])
        subj()
        d.t("\n\nOBJECTIVE:\n")
        d.t("Cervical AROM: flexion ").n(f"{r.randint(30, 50)}°", "rom").t(", extension ").n(f"{r.randint(25, 55)}°", "rom").t(
            ", R rotation ").n(f"{r.randint(45, 75)}°", "rom").t(", L rotation ").n(f"{r.randint(45, 75)}°", "rom").nl()
        d.t("Lumbar AROM: flexion ").n(f"{r.randint(40, 80)}%", "rom").t(" of normal, extension ").n(f"{r.randint(40, 90)}%", "rom").nl()
        d.t("MMT: shoulder abduction 4/5 R, 4+/5 L; hip extension 4/5 bilaterally\n")
        d.t("Interventions: Therapeutic exercise (").n("97110", "cpt").t(") x 2 units; Manual therapy (").n("97140", "cpt").t(
            ") x 1 unit; Neuromuscular re-ed (").n("97112", "cpt").t(") x 1 unit; E-stim unattended (").n("G0283", "hcpcs").t(")\n")
        d.t("Total timed minutes: ").n(str(r.randint(38, 53)), "minutes").t("  Total treatment time: 60 minutes\n\n")
        d.t("ASSESSMENT: Patient tolerated treatment well. ")
        d.t(r.choice(["Continues to demonstrate guarding with cervical rotation. ",
                      "Improved scapular stability noted. ",
                      "Increased tolerance to lifting tasks, progressed to 20 lbs. ",
                      "Persistent radicular symptoms into L buttock; will update referring provider. "]))
        d.t("Progressing toward goal: ").t(r.choice(goals)).t(".\n\n")
        d.t("PLAN: Continue POC 3x/week x 4 weeks. Next visit ")
        nxt = dos + timedelta(days=r.choice([2, 2, 3, 4, 7]))
        d.p("DATE", fmt_date(nxt, style="mdy"))
        d.t(".\n\nTherapist: ")
        d.p("PERSON", f"{therapist_first} {therapist_last}").t(", PT, DPT   License #: ").p("ID_NUMBER", f"{r.randint(1000, 99999)}").t(
            "   Electronically signed ").p("DATE", fmt_date(dos, style="mdy0")).nl()
        state["dos"] = nxt
    return d


# ---------------------------------------------------------------------------------------------
# 4. Itemized medical bill
# ---------------------------------------------------------------------------------------------

CHARGES = [("99285", "ED VISIT LEVEL 5", 2850.00), ("72125", "CT CERVICAL SPINE W/O CONTRAST", 3120.00),
           ("72100", "X-RAY LUMBAR SPINE 2-3 VIEWS", 412.00), ("96372", "THER/PROPH/DIAG INJ SC/IM", 285.00),
           ("J1885", "KETOROLAC TROMETHAMINE INJ 15MG", 64.00), ("70450", "CT HEAD/BRAIN W/O CONTRAST", 2780.00),
           ("97110", "THERAPEUTIC EXERCISES 15 MIN", 95.00), ("97140", "MANUAL THERAPY 15 MIN", 88.00),
           ("72148", "MRI LUMBAR SPINE W/O CONTRAST", 2450.00), ("64483", "INJ FORAMEN EPIDURAL L/S", 4100.00),
           ("99204", "OFFICE O/P NEW MOD 45 MIN", 420.00), ("99214", "OFFICE O/P EST MOD 30 MIN", 245.00)]


def itemized_bill(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    prov = c.providers[r.randint(0, len(c.providers) - 1)]
    d = Doc("bill", "Itemized Statement")
    acct = f"{r.randint(10 ** 6, 10 ** 7 - 1)}"
    d.p("ORGANIZATION", prov.facility, optional=True).nl()
    d.p("ADDRESS", prov.address.one_line()).nl()
    d.t("Federal Tax ID: ").p("EIN", prov.tax_id).t("    Billing NPI: ").p("NPI", prov.npi).nl()
    d.t("Billing Inquiries: ").p("PHONE", prov.phone).nl(2)
    d.t("ITEMIZED STATEMENT OF ACCOUNT\n")
    d.t("Statement Date: ")
    _date(d, c.incident + timedelta(days=r.randint(30, 200)), r)
    d.t("    Invoice: ").n(f"INV-{r.randint(10 ** 7, 10 ** 8 - 1)}", "invoice").nl()
    d.t("Guarantor: ")
    _name(d, p.first, p.last)
    d.nl()
    _addr(d, p.address, multiline=True)
    d.nl()
    d.t("Patient Account #: ").p("MRN", acct).t("     Patient DOB: ")
    _date(d, p.dob, r, dob=True)
    d.nl()
    d.t("Insurance: ").p("ORGANIZATION", p.health_plan, optional=True).t("   Member ID: ").p("HEALTH_PLAN_ID", p.member_id).t("   Group #: ").p(
        "HEALTH_PLAN_ID", p.group_no).nl(2)
    d.t(f"{'DOS':<12}{'CPT/HCPCS':<11}{'REV':<6}{'DESCRIPTION':<38}{'UNITS':>6}{'CHARGE':>12}\n")
    total = 0.0
    dos = c.incident
    for i in range(r.randint(8, 30)):
        code, desc, amt = r.choice(CHARGES)
        units = r.randint(1, 3)
        dos = dos + timedelta(days=r.choice([0, 0, 1, 2, 3, 7]))
        d.p("DATE", fmt_date(dos, style="mdy0")).t("  ").n(code, "cpt").t(" " * (11 - len(code))).n(
            r.choice(["0450", "0320", "0350", "0420", "0636", "0510"]), "rev_code").t("  ")
        d.t(f"{desc:<38}{units:>6}").t(" " * 2).p("MONEY", f"${amt * units:>10,.2f}".replace(" ", ""), optional=True).nl()
        total += amt * units
    d.nl().t("TOTAL CHARGES: ").p("MONEY", f"${total:,.2f}", optional=True).nl()
    d.t("PAYMENTS/ADJUSTMENTS: $0.00\nBALANCE DUE: ").p("MONEY", f"${total:,.2f}", optional=True).nl(2)
    d.t("Pay online at ").n("www.patientportal-pay.com", "url_business").t(" or mail check payable to ").p(
        "ORGANIZATION", prov.facility, optional=True).t(". To pay by card, call ").p("PHONE", prov.phone).t(".\n")
    d.t("Page ").n("1", "page").t(" of ").n("1", "page").nl()
    return d


# ---------------------------------------------------------------------------------------------
# 5. Demand letter
# ---------------------------------------------------------------------------------------------

def demand_letter(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    d = Doc("demand_letter", "Settlement Demand Letter")
    d.p("ORGANIZATION", c.firm, optional=True).nl()
    _addr(d, c.firm_address, multiline=True)
    d.nl()
    d.t("Tel ").p("PHONE", c.firm_phone).t("  |  Fax ").p("PHONE", c.firm_fax).t("  |  ").p("EMAIL", c.firm_email).nl(2)
    _date(d, c.incident + timedelta(days=r.randint(120, 400)), r, style="long")
    d.nl(2)
    d.t("VIA EMAIL (").p("EMAIL", c.adjuster_email).t(") AND CERTIFIED MAIL RRR ").n(f"9589 0710 5270 {r.randint(1000, 9999)} {r.randint(1000, 9999)} {r.randint(10, 99)}", "tracking").nl(2)
    d.p("PERSON", f"{c.adjuster_first} {c.adjuster_last}").t(", Claims Adjuster\n").p("ORGANIZATION", c.insurer, optional=True).nl()
    d.p("ADDRESS", f"P.O. Box {r.randint(100000, 999999)}\nBloomington, IL 61702").nl(2)
    d.t("Re:\tYour Insured:\t").p("PERSON", f"{c.defendant.first} {c.defendant.last}").nl()
    d.t("\tOur Client:\t").p("PERSON", f"{p.first} {p.last}").nl()
    d.t("\tClaim No.:\t").p("CLAIM_NUMBER", c.claim_no).nl()
    d.t("\tPolicy No.:\t").p("POLICY_NUMBER", c.policy_no).nl()
    d.t("\tDate of Loss:\t")
    _date(d, c.incident, r, style="long")
    d.nl()
    d.t("\tDOB:\t\t")
    _date(d, p.dob, r, dob=True, style="mdy0")
    d.nl(2)
    d.t("CONFIDENTIAL SETTLEMENT COMMUNICATION — TEX. R. EVID. 408\n\n")
    d.t("Dear ").t("Ms. " if r.random() < .5 else "Mr. ").p("PERSON", c.adjuster_last).t(":\n\n")
    d.t("As you know, this firm represents ").p("PERSON", f"{p.first} {p.last}").t(" for injuries sustained in the collision of ")
    _date(d, c.incident, r, style="long")
    d.t(". Please accept this letter as our client's offer to settle all claims against your insured within policy limits.\n\n")
    d.t("I. FACTS OF THE COLLISION\n\n")
    d.t("On the afternoon of the collision, our client was stopped at a red light at ").p(
        "INDIRECT_LOCATION", f"the intersection of {c.street1} and {c.street2}").t(", directly in front of ").p(
        "INDIRECT_LOCATION", f"the {c.business} on {c.street1}").t(". Your insured, driving a ").p(
        "VEHICLE_DESCRIPTION", c.defendant.vehicle.desc()).t(" (plate ").p("LICENSE_PLATE", c.defendant.vehicle.plate).t(
        "), struck our client's vehicle from behind at an estimated 35-40 mph. Your insured admitted to the investigating officer that he was looking at his phone. ")
    d.t("Independent witness ").p("PERSON", f"{c.witnesses[0].first} {c.witnesses[0].last}").t(", who was working as ").p(
        "INDIRECT_ROLE", f"the shift supervisor at the {c.business}").t(", confirmed the speed of your insured's vehicle and provided surveillance video. ")
    d.t("Liability is clear. Your insured was cited (Citation ").p("LAW_ENFORCEMENT_ID", f"C{r.randint(10 ** 7, 10 ** 8 - 1)}").t(").\n\n")
    d.t("II. INJURIES AND TREATMENT\n\n")
    for prov in c.providers[:5]:
        start = c.incident + timedelta(days=r.randint(0, 40))
        d.p("ORGANIZATION", prov.facility, optional=True).t(" (").p("DATE", fmt_date(start, style="mdy")).t(" – ").p(
            "DATE", fmt_date(start + timedelta(days=r.randint(0, 120)), style="mdy")).t("): ")
        choice = r.randint(0, 5)
        if choice == 1:
            d.t("Dr. ").p("PERSON", prov.doctor_last).t(" diagnosed a C5-6 disc herniation with right-sided radiculopathy and recommended epidural steroid injections. ")
        else:
          d.t([
            "Evaluated in the emergency department for neck and back pain; CT of the cervical spine showed straightening of the lordosis. ",
            "",
            "Completed 36 sessions of physical therapy with documented reduction in range of motion. ",
            "MRI of the lumbar spine revealed an L4-5 disc protrusion abutting the L5 nerve root. ",
            "Underwent a cervical epidural steroid injection at C6-7 under fluoroscopy. ",
            "Neuropsychological evaluation confirmed post-concussive syndrome with deficits in working memory. "][choice])
        d.nl(2)
    d.t("III. MEDICAL SPECIALS\n\n")
    total = 0.0
    for prov in c.providers[:6]:
        amt = r.uniform(800, 42000)
        total += amt
        d.p("ORGANIZATION", prov.facility, optional=True).t(" " * max(1, 50 - len(prov.facility))).p("MONEY", f"${amt:,.2f}", optional=True).nl()
    d.t("TOTAL MEDICAL EXPENSES").t(" " * 28).p("MONEY", f"${total:,.2f}", optional=True).nl(2)
    d.t("IV. LOST WAGES\n\n")
    d.t("At the time of the collision our client was employed as a ").t(p.job).t(" at ").p("EMPLOYER", p.employer).t(", earning ").p(
        "FINANCIAL_INFO", f"${p.hourly:.2f} per hour").t(". Per the enclosed letter from supervisor ").p(
        "PERSON", f"{c.supervisor_first} {c.supervisor_last}").t(", our client missed ").n(f"{r.randint(80, 600)} hours", "hours").t(" of work.\n\n")
    d.t("V. DEMAND\n\n")
    demand = r.choice([30000, 50000, 100000, 250000])
    d.t("Based on the foregoing, we hereby demand ").p("MONEY", f"${demand:,.2f}").t(", the policy limits, to settle all claims. This offer will remain open for thirty (30) days. ")
    d.t("Please also disclose all applicable coverage pursuant to Tex. Ins. Code ").n("§ 542.002", "statute").t(".\n\n")
    d.t("Sincerely,\n\n/s/ ").p("PERSON", f"{c.attorney_first} {c.attorney_last}").nl()
    d.p("PERSON", f"{c.attorney_first} {c.attorney_last}").t("\nState Bar No. ").p("ID_NUMBER", c.bar_no).nl()
    d.t("cc: ").p("PERSON", f"{p.first} {p.last}").t(" (client)\nEnclosures: medical records and bills (Bates ").n(
        f"{p.last.upper().replace(' ', '')}_000001", "bates").t(" – ").n(f"{p.last.upper().replace(' ', '')}_00{r.randint(1000, 9999)}", "bates").t(")\n")
    return d


# ---------------------------------------------------------------------------------------------
# 6. Deposition transcript (very long, line-numbered)
# ---------------------------------------------------------------------------------------------

def deposition(c: Case, pages: int) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    d = Doc("deposition", "Oral Deposition")
    page_no = {"n": 1}
    lines: list[list] = []  # each line: list of (kind, value) pieces

    def L(*pieces) -> None:
        lines.append(list(pieces))

    def Q(*pieces) -> None:
        L(("t", "Q.  "), *pieces)

    def A(*pieces) -> None:
        L(("t", "A.  "), *pieces)

    # caption
    L(("t", "                    CAUSE NO. "), ("CASE_NUMBER", c.case_no))
    L(("t", ""))
    L(("PERSON", f"{p.first.upper()} {p.last.upper()}"), ("t", ",               )    IN THE DISTRICT COURT OF"))
    L(("t", "     Plaintiff,                 )"))
    L(("t", "v.                              )    "), ("LOCATION", c.court.split(' District')[0].upper(), True), ("t", ", TEXAS"))
    L(("PERSON", f"{c.defendant.first.upper()} {c.defendant.last.upper()}"), ("t", ",            )"))
    L(("t", "     Defendant.                 )    "), ("t", f"{r.randint(53, 459)}TH JUDICIAL DISTRICT"))
    L(("t", ""))
    L(("t", "          ORAL AND VIDEOTAPED DEPOSITION OF "), ("PERSON", f"{p.first.upper()} {p.last.upper()}"))
    L(("t", "                    "), ("DATE", fmt_date(c.incident + timedelta(days=r.randint(300, 600)), style="long").upper()))
    L(("t", ""))
    L(("t", "APPEARANCES:"))
    L(("t", "FOR THE PLAINTIFF: Mr. "), ("PERSON", f"{c.attorney_first} {c.attorney_last}"), ("t", ", "), ("ORGANIZATION", c.firm, True))
    L(("t", "FOR THE DEFENDANT: Ms. "), ("PERSON", " ".join(g.name()[0::2][:2])), ("t", ", Brown & Kessler LLP"))
    L(("t", "ALSO PRESENT: "), ("PERSON", " ".join(g.name()[0::2][:2])), ("t", ", videographer"))
    reporter = " ".join(g.name()[0::2][:2])

    topics = []
    # Q&A blocks with PII
    topics.append(lambda: (Q(("t", "Please state your full name for the record.")),
                           A(("PERSON", f"{p.first} {p.middle} {p.last}".replace("  ", " "))),
                           Q(("t", "And your date of birth?")),
                           A(("DATE_OF_BIRTH", fmt_date(p.dob, r, "long")), ("t", ".")),
                           Q(("t", "What is your current address?")),
                           A(("ADDRESS", p.address.one_line()), ("t", ".")),
                           Q(("t", "How long have you lived there?")),
                           A(("t", f"About {r.randint(2, 14)} years.")),
                           Q(("t", "Who lives there with you?")),
                           A(("INDIRECT_ROLE", "My husband" if p.sex == "F" else "My wife", True), ("t", ", "),
                             ("PERSON", p.spouse.first if p.spouse else "nobody"), ("t", ", and our kids."))))
    if p.children:
        def kids():
            Q(("t", "What are your children's names and ages?"))
            pieces = [("t", "")]
            for i, ch in enumerate(p.children):
                pieces += [("MINOR_PERSON", ch.first), ("t", " is "), ("AGE", str(ch.age(c.incident))),
                           ("t", ", " if i < len(p.children) - 1 else ".")]
            A(*pieces)
            Q(("t", "Where do they go to school?"))
            A(("t", "They go to "), ("SCHOOL", f"{r.choice(['Pecan Springs', 'Barton Hills', 'Oak Hill', 'Ridgetop', 'Highland Park'])} Elementary School"), ("t", "."))
        topics.append(kids)
    topics.append(lambda: (Q(("t", "What is your phone number?")),
                           A(("PHONE", p.cell), ("t", ".")),
                           Q(("t", "Is that a cell phone?")),
                           A(("t", "Yes.")),
                           Q(("t", "Were you using that phone at the time of the collision?")),
                           A(("t", "No, it was in my purse." if p.sex == "F" else "No, it was in the cup holder.")),
                           Q(("t", "Do you use any social media?")),
                           A(("t", "Instagram. My handle is "), ("USERNAME", p.username if p.username.startswith("@") else "@" + p.username), ("t", "."))))
    topics.append(lambda: (Q(("t", "Where were you employed at the time of the accident?")),
                           A(("t", "I worked at "), ("EMPLOYER", p.employer), ("t", " as a "), ("t", p.job), ("t", ".")),
                           Q(("t", "Who was your supervisor?")),
                           A(("PERSON", f"{c.supervisor_first} {c.supervisor_last}"), ("t", ".")),
                           Q(("t", "What were you earning?")),
                           A(("t", "I was making "), ("FINANCIAL_INFO", f"${p.hourly:.2f} an hour"), ("t", ", about 40 hours a week.")),
                           Q(("t", "Are you still employed there?")),
                           A(("t", "No. They let me go about three months after the wreck because I couldn't lift anymore."))))
    topics.append(lambda: (Q(("t", "Tell me where you were when the collision happened.")),
                           A(("t", "I was stopped at the light right in front of "), ("INDIRECT_LOCATION", f"the {c.business} on {c.street1}"),
                             ("t", ", at "), ("INDIRECT_LOCATION", f"the corner of {c.street1} and {c.street2}"), ("t", ".")),
                           Q(("t", "Why were you there?")),
                           A(("t", "I stop there every morning before work. "), ("INDIRECT_ROLE", "The manager there"),
                             ("t", " knows me by name.")),
                           Q(("t", "Did you speak with anyone at the scene?")),
                           A(("t", "The lady who works the night shift came out, "), ("PERSON", c.witnesses[0].first), ("t", ". She gave me her number, "),
                             ("PHONE", c.witnesses[0].cell), ("t", "."))))
    topics.append(lambda: (Q(("t", "Have you ever been convicted of a felony or a crime involving moral turpitude?")),
                           A(("t", "I had a "), ("CRIMINAL_HISTORY", "DWI"), ("t", f" back in {r.randint(2005, 2015)}, a misdemeanor.")),
                           Q(("t", "Any other arrests?")),
                           A(("t", "No.")),
                           Q(("t", "Prior to this accident, had you ever injured your neck or back?")),
                           A(("t", "I hurt my back lifting boxes once, but I just took ibuprofen for a few days.")),
                           Q(("t", "Did you see a doctor for that?")),
                           A(("t", "No."))))
    topics.append(lambda: (Q(("t", "What is your Social Security number?")),
                           L(("t", "          MR. "), ("PERSON", c.attorney_last.upper()), ("t", ":  Objection. We'll provide that off the record.")),
                           Q(("t", "Fair enough. What is your driver's license number?")),
                           A(("t", "It's "), ("DRIVERS_LICENSE", p.dl), ("t", ".")),
                           Q(("t", "And the plate on your vehicle?")),
                           A(("LICENSE_PLATE", p.vehicle.plate), ("t", ". It's a "), ("VEHICLE_DESCRIPTION", p.vehicle.desc()), ("t", "."))))
    topics.append(lambda: (Q(("t", "Have you treated with anyone for emotional or psychological problems since the wreck?")),
                           A(("t", "Yes, I see a counselor at "), ("ORGANIZATION", "Hill Country Behavioral Health", True), ("t", " for "),
                             ("MENTAL_HEALTH", "anxiety"), ("t", ". I have panic attacks when I drive.")),
                           Q(("t", "Who is your counselor?")),
                           A(("PERSON", " ".join(g.name()[0::2][:2])), ("t", ".")),
                           Q(("t", "Are you taking any medication for that?")),
                           A(("MEDICATION", "Zoloft"), ("t", ", and "), ("MEDICATION", "Xanax"), ("t", " when it gets bad."))))
    topics.append(lambda: (Q(("t", "Let me hand you what has been marked as Exhibit "), ("n", str(r.randint(1, 30))), ("t", ". Do you recognize this document?")),
                           A(("t", "Yes, those are my medical bills.")),
                           Q(("t", "Please turn to page "), ("n", str(r.randint(2, 99))), ("t", ". Do you see the charge for CPT code "), ("n", "72148"), ("t", "?")),
                           A(("t", "Yes, that's the MRI.")),
                           Q(("t", "Did your health insurance pay any of these bills?")),
                           A(("t", "Some. My member ID is on the card, "), ("HEALTH_PLAN_ID", p.member_id), ("t", "."))))
    topics.append(lambda: (Q(("t", "Do you have any family who lives nearby?")),
                           A(("INDIRECT_ROLE", "My mother", True), ("t", " lives over on "), ("INDIRECT_LOCATION", f"{r.choice(['Oak', 'Pecan', 'Willow', 'Elm'])} Street"),
                             ("t", " in the "), ("INDIRECT_LOCATION", f"{r.choice(['Sunset Ridge', 'Brookhollow', 'Cedar Park'])} Apartments"), ("t", ", "),
                             ("INDIRECT_LOCATION", f"unit {r.randint(100, 499)}"), ("t", ".")),
                           Q(("t", "Does she help you?")),
                           A(("t", "She picks up the kids from school when I have therapy."))))
    filler_q = ["And what happened next?", "How long did that last?", "Did that help?", "Okay.", "Can you describe the pain?",
                "On a scale of one to ten?", "Is it constant or does it come and go?", "What makes it worse?",
                "Did you tell the doctor that?", "Are you still treating?", "When was your last visit?", "All right.",
                "I want to make sure I understand your answer.", "Is there anything else?", "Let's take a short break."]
    filler_a = ["I'm not sure.", "It hurts every day.", "Maybe a seven.", "It comes and goes.", "Sitting for a long time.",
                "Yes, I told them everything.", "About two weeks ago.", "No, not really.", "I don't remember exactly.",
                "Yes.", "No.", "It was really scary.", "I couldn't turn my head.", "My neck and my lower back."]
    while len(lines) < pages * 25:
        if r.random() < 0.25 and topics:
            topics.pop(r.randrange(len(topics)))() if r.random() < 0.6 else topics[r.randrange(len(topics))]()
        else:
            Q(("t", r.choice(filler_q)))
            A(("t", r.choice(filler_a)))
    # reporter's certificate
    L(("t", "REPORTER'S CERTIFICATE"))
    L(("t", "I, "), ("PERSON", reporter), ("t", ", Certified Shorthand Reporter No. "), ("ID_NUMBER", str(r.randint(1000, 9999))),
      ("t", ", certify that the foregoing is a true record of the testimony given."))

    # render pages of 25 numbered lines
    for i, pieces in enumerate(lines):
        ln = i % 25 + 1
        if ln == 1:
            if i:
                d.t("\n\f")
            d.t(" " * 70).n(f"Page {page_no['n']}", "page").nl()
            page_no["n"] += 1
        d.n(f"{ln:>2}", "line_no").t("   ")
        for kind, val, *rest in pieces:
            if kind == "t":
                d.t(val)
            elif kind == "n":
                d.n(val, "exhibit")
            elif kind == "MINOR_PERSON":
                d.p("PERSON", val, minor=True)
            else:
                d.p(kind, val, optional=bool(rest and rest[0]))
        d.nl()
    return d


# ---------------------------------------------------------------------------------------------
# 7. HIPAA authorization, 8. wage verification, 9. intake, 10. settlement statement,
# 11. email thread, 12. pharmacy profile, 13. complaint, 14. bank statement
# ---------------------------------------------------------------------------------------------

def hipaa_auth(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    prov = r.choice(c.providers)
    d = Doc("hipaa_auth", "HIPAA Authorization")
    d.t("AUTHORIZATION FOR RELEASE OF PROTECTED HEALTH INFORMATION\n(45 C.F.R. ").n("§ 164.508", "statute").t(")\n\n")
    d.t("Patient Name: ").p("PERSON", f"{p.first} {p.middle} {p.last}".replace("  ", " ")).nl()
    d.t("Date of Birth: ")
    _date(d, p.dob, r, dob=True)
    d.t("        Last 4 of SSN: ").p("SSN", p.ssn[-4:]).nl()
    d.t("Address: ")
    _addr(d, p.address)
    d.nl()
    d.t("Phone: ").p("PHONE", p.cell).t("        Email: ").p("EMAIL", p.email).nl(2)
    d.t("I authorize: ").p("ORGANIZATION", prov.facility, optional=True).t(", ")
    _addr(d, prov.address)
    d.nl()
    d.t("to release to: ").p("ORGANIZATION", c.firm, optional=True).t(", ")
    _addr(d, c.firm_address)
    d.t(", Fax ").p("PHONE", c.firm_fax).nl(2)
    d.t("Information to be released: complete medical records, billing records, imaging, and itemized statements from ")
    _date(d, c.incident, r)
    d.t(" to present, INCLUDING records relating to: [X] mental health  [X] drug/alcohol treatment (42 C.F.R. Part 2)  [X] HIV/AIDS testing\n\n")
    d.t("Purpose: legal representation — personal injury claim.\n")
    d.t("This authorization expires one year from the date signed. I understand I may revoke it in writing.\n\n")
    d.t("Signature of Patient: /s/ ").p("PERSON", f"{p.first} {p.last}").t("        Date: ")
    _date(d, c.incident + timedelta(days=r.randint(3, 30)), r)
    d.nl()
    if p.children:
        ch = p.children[0]
        d.t("\nIf signed by a personal representative, relationship to patient: Parent of minor ")
        _name(d, ch.first, ch.last, minor=True)
        d.t(", DOB ")
        _date(d, ch.dob, r, dob=True)
        d.nl()
    return d


def wage_verification(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    d = Doc("wage", "Employer Wage & Salary Verification")
    d.p("EMPLOYER", p.employer).t("\nHuman Resources Department\n")
    _addr(d, g.address((c.city, c.state, "787")))
    d.t("\nFEIN: ").p("EIN", ein(r)).nl(2)
    d.t("EMPLOYER'S VERIFICATION OF LOST WAGES\n\n")
    d.t("Employee Name: ").p("PERSON", f"{p.first} {p.last}").nl()
    d.t("Employee ID: ").p("ID_NUMBER", f"E{r.randint(10 ** 5, 10 ** 6 - 1)}").t("     SSN: ").p("SSN", p.ssn).nl()
    d.t("Position: ").t(p.job).t("     Date of Hire: ")
    _date(d, p.dob + timedelta(days=365 * 20 + r.randint(0, 3000)), r)
    d.nl()
    d.t("Rate of Pay: ").p("FINANCIAL_INFO", f"${p.hourly:.2f} per hour").t("     Average hours per week: ").n("40", "hours").nl()
    d.t("Dates absent due to injury: ")
    _date(d, c.incident + timedelta(days=1), r)
    d.t(" through ")
    _date(d, c.incident + timedelta(days=r.randint(20, 120)), r)
    d.nl()
    d.t("Total hours missed: ").n(str(r.randint(80, 640)), "hours").t("   Total wages lost: ").p("MONEY", g.money(2000, 30000)).nl()
    d.t("Payroll direct deposit on file: ").p("ORGANIZATION", BANKS[p.routing], optional=True).t(", routing ").p(
        "ROUTING_NUMBER", p.routing).t(", account ending ").p("BANK_ACCOUNT", p.bank_account[-4:]).nl(2)
    d.t("Completed by: ").p("PERSON", f"{c.supervisor_first} {c.supervisor_last}").t(", Store Manager   Phone: ").p(
        "PHONE", g.phone(c.state)).t("   Email: ").p("EMAIL", g.email(c.supervisor_first, c.supervisor_last)).nl()
    return d


def intake(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    d = Doc("intake", "Client Intake Questionnaire")
    d.t("NEW CLIENT INTAKE — PERSONAL INJURY\n").p("ORGANIZATION", c.firm, optional=True).t("   Intake by: ").p(
        "PERSON", f"{c.paralegal_first} {c.paralegal_last}").nl(2)
    d.kv("Full Legal Name", "PERSON", f"{p.first} {p.middle} {p.last}".replace("  ", " "))
    d.t("Other names used: ").p("PERSON", f"{p.first} {g.name()[2]}").t(" (maiden)\n")
    d.t("Date of Birth: ")
    _date(d, p.dob, r, dob=True)
    d.t("   Age: ").p("AGE", str(p.age(c.incident))).nl()
    d.kv("Social Security #", "SSN", p.ssn)
    d.t("Driver's License #: ").p("DRIVERS_LICENSE", p.dl).t("  State: ").t(p.dl_state).nl()
    d.t("Home Address: ")
    _addr(d, p.address)
    d.nl()
    d.kv("Cell", "PHONE", p.cell)
    d.kv("Email", "EMAIL", p.email)
    d.t("Best time to call: evenings\n")
    if p.spouse:
        d.kv("Spouse Name", "PERSON", f"{p.spouse.first} {p.spouse.last}")
        d.t("Spouse DOB: ")
        _date(d, p.spouse.dob, r, dob=True)
        d.t("   Spouse Phone: ").p("PHONE", p.spouse.cell).nl()
    for i, ch in enumerate(p.children):
        d.t(f"Child {i + 1}: ")
        _name(d, ch.first, ch.last, minor=True)
        d.t("   DOB: ")
        _date(d, ch.dob, r, dob=True)
        d.t("   In vehicle? ").t(r.choice(["Yes", "No"])).nl()
    d.t("Employer: ").p("EMPLOYER", p.employer).t("   Job title: ").t(p.job).t("   Wage: ").p("FINANCIAL_INFO", f"${p.hourly:.2f}/hr").nl()
    d.t("Health insurance: ").p("ORGANIZATION", p.health_plan, optional=True).t("   Member ID: ").p("HEALTH_PLAN_ID", p.member_id).nl()
    d.t("Medicare? ").t(r.choice(["No", "Yes — MBI "]))
    if d.text.endswith("MBI "):
        d.p("MEDICARE_ID", p.mbi)
    d.nl()
    d.t("Auto insurer: ").p("ORGANIZATION", c.client_insurer, optional=True).t("   Policy #: ").p("POLICY_NUMBER", c.client_policy).nl()
    d.t("Vehicle: ").p("VEHICLE_DESCRIPTION", p.vehicle.desc()).t("   Plate: ").p("LICENSE_PLATE", p.vehicle.plate).t("   VIN: ").p("VIN", p.vehicle.vin).nl()
    d.t("Prior claims or lawsuits? ").t("Slip and fall at ").p("INDIRECT_LOCATION", f"the Walmart on {r.choice(['Ben White', 'Slaughter', 'Research'])} Blvd").t(", 2017, settled.\n")
    d.t("Prior criminal history? ").p("CRIMINAL_HISTORY", "misdemeanor DWI").t(f", {r.randint(2005, 2015)}, completed probation.\n")
    d.t("Immigration status (for lost-wage claim): ").p("IMMIGRATION_STATUS", r.choice(["lawful permanent resident", "U.S. citizen", "DACA recipient"])).nl()
    d.t("How did you hear about us? Billboard on ").n("I-35", "highway").nl()
    d.t("Payment for intake: ").p("CREDIT_CARD", p.card[1]).t("  exp ").p("CARD_EXPIRY", f"{r.randint(1, 12):02d}/{r.randint(26, 30)}").t("  CVV ").p(
        "CVV", str(r.randint(100, 999))).nl()
    d.t("Portal login: username ").p("USERNAME", p.email).t("  temporary password: ").p("PASSWORD", f"Welcome{r.randint(100, 999)}!").nl()
    return d


def settlement_statement(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    d = Doc("settlement", "Settlement Disbursement Statement")
    gross = r.choice([45000, 75000, 100000, 175000, 250000])
    d.t("SETTLEMENT STATEMENT AND DISBURSEMENT SCHEDULE\n").p("ORGANIZATION", c.firm, optional=True).nl(2)
    d.t("Client: ").p("PERSON", f"{p.first} {p.last}").t("        Case: ").p("PERSON", f"{p.last}").t(" v. ").p("PERSON", c.defendant.last).t(", Cause No. ").p("CASE_NUMBER", c.case_no).nl()
    d.t("Claim No.: ").p("CLAIM_NUMBER", c.claim_no).nl(2)
    d.t("PRIVILEGED & CONFIDENTIAL — ATTORNEY-CLIENT COMMUNICATION\n")
    d.t("Gross Settlement Amount ................................. ").p("MONEY", f"${gross:,.2f}").nl()
    d.t("Attorney's Fee (33.33%) ................................. ").p("MONEY", f"${gross / 3:,.2f}").nl()
    d.t("Case Expenses ........................................... ").p("MONEY", g.money(500, 6000)).nl()
    d.t("Medical liens:\n")
    d.t("   Medicare (MBI ").p("MEDICARE_ID", p.mbi).t(") conditional payment ...... ").p("MONEY", g.money(1000, 9000)).nl()
    d.t("   ").p("ORGANIZATION", p.health_plan, optional=True).t(" (Member ").p("HEALTH_PLAN_ID", p.member_id).t(") ... ").p("MONEY", g.money(2000, 15000)).nl()
    for prov in c.providers[:3]:
        d.t("   ").p("ORGANIZATION", prov.facility, optional=True).t(" (LOP) ... ").p("MONEY", g.money(1000, 20000)).nl()
    d.t("NET TO CLIENT ........................................... ").p("MONEY", g.money(10000, 90000)).nl(2)
    d.t("Disbursement by wire to client:\n")
    d.t("   Bank: ").p("ORGANIZATION", BANKS[p.routing], optional=True).nl()
    d.t("   ABA Routing: ").p("ROUTING_NUMBER", p.routing).nl()
    d.t("   Account No.: ").p("BANK_ACCOUNT", p.bank_account).nl()
    d.t("   Account Holder: ").p("PERSON", f"{p.first} {p.last}").nl()
    if r.random() < 0.5:
        d.t("   Foreign lienholder IBAN: ").p("IBAN", iban_de(r)).t("  SWIFT/BIC: ").p("SWIFT_BIC", "DEUTDEFF").nl()
    d.t("\nI approve this settlement statement and authorize disbursement.\n\n")
    d.t("Client Signature: /s/ ").p("PERSON", f"{p.first} {p.last}").t("      Date: ")
    _date(d, c.incident + timedelta(days=r.randint(400, 800)), r)
    d.nl()
    d.t("Trust account (IOLTA) #: ").p("BANK_ACCOUNT", g.account()).nl()
    return d


def email_thread(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    d = Doc("email", "Attorney-Client Email Thread")
    att = f"{c.attorney_first} {c.attorney_last}"
    for i in range(r.randint(3, 6)):
        frm_client = i % 2 == 1
        d.t("From: ")
        if frm_client:
            d.p("PERSON", f"{p.first} {p.last}").t(" <").p("EMAIL", p.email).t(">\n")
            d.t("To: ").p("PERSON", att).t(" <").p("EMAIL", c.firm_email).t(">\n")
        else:
            d.p("PERSON", att).t(" <").p("EMAIL", c.firm_email).t(">\n")
            d.t("To: ").p("PERSON", f"{p.first} {p.last}").t(" <").p("EMAIL", p.email).t(">\n")
            d.t("Cc: ").p("PERSON", f"{c.paralegal_first} {c.paralegal_last}").t(" <").p(
                "EMAIL", f"{c.paralegal_first[0].lower()}{c.paralegal_last.lower().replace(' ', '')}@{c.attorney_last.lower().replace(' ', '')}law.com".replace("'", "")).t(">\n")
        d.t("Date: ")
        _date(d, c.incident + timedelta(days=100 + i * 3), r, style="long")
        d.t(f" {r.randint(8, 18)}:{r.randint(10, 59)}\n")
        d.t("Subject: RE: Settlement offer — ").p("PERSON", p.last).t(" claim\n\n")
        if not frm_client:
            d.t("PRIVILEGED & CONFIDENTIAL — ATTORNEY-CLIENT COMMUNICATION\n\n")
            d.t("Hi ").p("PERSON", p.first).t(",\n\n")
            k = r.randint(0, 2)
            if k == 0:
                d.t("The adjuster came back at ").p("MONEY", "$18,500", optional=True).t(". I think we can get them closer to ").p(
                    "MONEY", "$35,000", optional=True).t(" if we wait for the MRI results. My advice is to reject this offer.")
            elif k == 1:
                d.t("I spoke with Dr. ").p("PERSON", c.providers[1].doctor_last).t(" and he will support a future surgery recommendation. That should significantly increase the value.")
            else:
                d.t("Please do not post anything on social media about the accident or your activities. The defense will look at your accounts.")
            d.t("\n\nBest,\n").p("PERSON", att).nl().p("ORGANIZATION", c.firm, optional=True).t("  |  Direct ").p("PHONE", c.firm_phone).nl()
        else:
            d.t(r.choice([
                "I really need the money soon, I'm behind on rent at ",
                "My landlord at ",
                "Can you send the check to my sister's place? She lives at ",
            ]))
            d.p("ADDRESS", g.address((c.city, c.state, "787")).one_line())
            d.t(". Also my new number is ").p("PHONE", g.phone(c.state)).t(". The therapist at ").p(
                "ORGANIZATION", "Hill Country Behavioral Health", optional=True).t(" said my ").p("MENTAL_HEALTH", "PTSD").t(" is getting worse.\n\nThanks,\n").p(
                "PERSON", p.first).nl()
        d.t("\n" + "-" * 60 + "\n")
    return d


def pharmacy(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    d = Doc("pharmacy", "Pharmacy Patient Profile")
    store = r.choice(["Walgreens", "CVS Pharmacy", "H-E-B Pharmacy"])
    d.p("INDIRECT_LOCATION", f"{store} #{r.randint(1000, 19999)}").t(" — ")
    _addr(d, g.address((c.city, c.state, "787")))
    d.t("   Ph ").p("PHONE", g.phone(c.state)).nl()
    d.t("PATIENT PRESCRIPTION HISTORY\n")
    d.t("Patient: ").p("PERSON", p.last_first).t("   DOB: ")
    _date(d, p.dob, r, dob=True)
    d.t("   Phone: ").p("PHONE", p.cell).nl()
    d.t("Third party: ").p("ORGANIZATION", p.health_plan, optional=True).t("  BIN ").n("610014", "bin").t("  PCN ").n("MEDDPRIME", "pcn").t("  ID ").p("HEALTH_PLAN_ID", p.member_id).nl(2)
    d.t(f"{'Fill Date':<12}{'Rx #':<10}{'Drug':<36}{'Qty':>5}  Prescriber\n")
    drugs = ["cyclobenzaprine 10 mg tab", "ibuprofen 800 mg tab", "hydrocodone-acetaminophen 5-325 mg", "gabapentin 300 mg cap",
             "methylprednisolone 4 mg dose pack", "tizanidine 4 mg tab", "meloxicam 15 mg tab", "sertraline 50 mg tab",
             "alprazolam 0.5 mg tab", "tramadol 50 mg tab"]
    for i in range(r.randint(10, 25)):
        doc = r.choice(c.providers)
        dt = c.incident + timedelta(days=r.randint(0, 300))
        d.p("DATE", fmt_date(dt, style="mdy0")).t("  ").n(str(r.randint(10 ** 6, 10 ** 7 - 1)), "rx_number").t("   ")
        drug = r.choice(drugs)
        d.p("MEDICATION", drug).t(" " * (34 - len(drug))).t(f"{r.choice([20, 30, 60, 90]):>5}  Dr. ").p("PERSON", doc.doctor_last).t(" DEA ").p("DEA_NUMBER", dea(r, doc.doctor_last)).nl()
    return d


def complaint(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    d = Doc("complaint", "Plaintiff's Original Petition")
    d.t("CAUSE NO. ").p("CASE_NUMBER", c.case_no).nl(2)
    d.p("PERSON", f"{p.first.upper()} {p.last.upper()}").t(", Individually and as Next Friend of ")
    if p.children:
        ch = p.children[0]
        d.p("PERSON", f"{ch.first[0]}.{ch.last[0]}.", minor=True).t(", a Minor,\n")
    else:
        d.t("no minors,\n")
    d.t("     Plaintiff,\nv.\n").p("PERSON", f"{c.defendant.first.upper()} {c.defendant.last.upper()}").t(",\n     Defendant.\n\n")
    d.t("PLAINTIFF'S ORIGINAL PETITION\n\nTO THE HONORABLE JUDGE OF SAID COURT:\n\n")
    d.t("1. Discovery is intended to be conducted under Level 3 of Tex. R. Civ. P. ").n("190.4", "rule").t(".\n\n")
    d.t("2. Plaintiff ").p("PERSON", f"{p.first} {p.last}").t(" is an individual residing in ").p("LOCATION", f"{c.court.split(' County')[0]} County", optional=True).t(
        ", Texas. The last three digits of Plaintiff's driver's license number are ").p("DRIVERS_LICENSE", "".join(ch for ch in p.dl if ch.isdigit())[-3:]).t(
        " and the last three digits of Plaintiff's Social Security number are ").p("SSN", p.ssn[-3:]).t(" (Tex. Civ. Prac. & Rem. Code ").n("§ 30.014", "statute").t(").\n\n")
    d.t("3. Defendant ").p("PERSON", f"{c.defendant.first} {c.defendant.last}").t(" is an individual who may be served at ")
    _addr(d, c.defendant.address)
    d.t(", or wherever he may be found.\n\n")
    d.t("4. On or about ")
    _date(d, c.incident, r, style="long")
    d.t(", Plaintiff was stopped at ").p("INDIRECT_LOCATION", f"the intersection of {c.street1} and {c.street2}").t(
        " when Defendant, operating a ").p("VEHICLE_DESCRIPTION", c.defendant.vehicle.desc()).t(", violently struck the rear of Plaintiff's vehicle.\n\n")
    d.t("5. Plaintiff seeks monetary relief over $250,000 but not more than $1,000,000 (Tex. R. Civ. P. ").n("47(c)(3)", "rule").t(").\n\n")
    d.t("Respectfully submitted,\n").p("ORGANIZATION", c.firm, optional=True).t("\nBy: /s/ ").p("PERSON", f"{c.attorney_first} {c.attorney_last}").t(
        "\nState Bar No. ").p("ID_NUMBER", c.bar_no).t("\n").p("EMAIL", c.firm_email).t("\nATTORNEY FOR PLAINTIFF\n")
    return d


def bank_statement(c: Case) -> Doc:
    g, r = c.g, c.g.r
    p = c.client
    d = Doc("bank", "Bank Statement")
    bank = BANKS[p.routing]
    d.p("ORGANIZATION", bank, optional=True).nl().p("ADDRESS", "P.O. Box 15284, Wilmington, DE 19850").nl(2)
    _name(d, p.first.upper(), p.last.upper())
    d.nl()
    _addr(d, p.address, multiline=True)
    d.nl(2)
    d.t("Primary Account: ").p("BANK_ACCOUNT", p.bank_account).t("    Routing: ").p("ROUTING_NUMBER", p.routing).nl()
    d.t("Statement Period: ")
    s0 = c.incident.replace(day=1)
    _date(d, s0, r)
    d.t(" through ")
    _date(d, s0 + timedelta(days=30), r)
    d.nl(2)
    d.t("TRANSACTION DETAIL\n")
    for i in range(r.randint(15, 40)):
        dt = s0 + timedelta(days=r.randint(0, 30))
        d.p("DATE", f"{dt.month:02d}/{dt.day:02d}").t("  ")
        kind = r.random()
        if kind < 0.3:
            d.t("Card Purchase With Pin ").n(f"{dt.month:02d}/{dt.day:02d}", "txn_date").t(" ").p(
                "INDIRECT_LOCATION", f"{r.choice(['HEB #', 'SHELL OIL ', 'MCDONALD\'S F', 'WALGREENS #'])}{r.randint(100, 9999)} {c.city.upper()} {c.state}").t(" Card ").p(
                "CREDIT_CARD", p.card[1].replace(" ", "")[-4:], optional=True).t("  ")
        elif kind < 0.5:
            other = g.name()
            d.t("Zelle Payment To ").p("PERSON", f"{other[0]} {other[2]}").t(" Jpm").n(f"{r.randint(10 ** 9, 10 ** 10 - 1)}", "txn_id").t("  ")
        elif kind < 0.6:
            d.t("Payroll Direct Dep ").p("EMPLOYER", p.employer.upper()).t(" PPD ID: ").n(f"{r.randint(10 ** 9, 10 ** 10 - 1)}", "ppd_id").t("  ")
        else:
            d.t(r.choice(["ATM Withdrawal", "Online Transfer To Sav", "Netflix.com", "Spectrum", "Venmo Cashout",
                          "Amazon Mktpl", "Texas Gas Service", "Progressive Ins Prem"])).t("  ")
        d.p("MONEY", g.money(4, 900), optional=True).nl()
    d.t("\nEnding Balance: ").p("MONEY", g.money(10, 5000), optional=True).nl()
    return d


# ---------------------------------------------------------------------------------------------

def case_file(seed: int, scale: int = 1) -> list[Doc]:
    """One complete PI case file. ``scale`` multiplies the long documents (PT visits, depo pages)."""
    g = Gen(seed)
    c = make_case(g)
    r = g.r
    docs = [crash_report(c), ed_record(c), pt_notes(c, visits=r.randint(12, 24) * scale), itemized_bill(c),
            itemized_bill(c), demand_letter(c), deposition(c, pages=r.randint(40, 70) * scale), hipaa_auth(c),
            wage_verification(c), intake(c), settlement_statement(c), email_thread(c), pharmacy(c), complaint(c),
            bank_statement(c)]
    return docs
