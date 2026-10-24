"""Synthetic identities with realistic, checksum-valid identifiers.

Everything here is fake. Values are generated to look exactly like real-world data (valid Luhn,
ABA, VIN check digits, state driver's-license formats, real area codes) so the benchmark exercises
the same code paths as production documents.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from datetime import date, timedelta

from faker import Faker

from obscura.detection.text import validators as V

_LOCALES = [("en_US", 50), ("es_MX", 14), ("en_GB", 5), ("en_IN", 6), ("it_IT", 4), ("de_DE", 4), ("fr_FR", 4),
            ("pl_PL", 3), ("pt_BR", 4), ("en_IE", 3), ("tr_TR", 1)]
_FAKERS = {loc: Faker(loc) for loc, _ in _LOCALES}

# Hand-picked hard cases: names that are also words, places, brands; multicultural; hyphenated.
HARD_NAMES = [
    ("Grace", "Hill"), ("Mark", "Price"), ("Will", "Hunter"), ("Faith", "Bishop"), ("Rose", "Banks"),
    ("Jack", "Black"), ("Crystal", "Waters"), ("Sunny", "Day"), ("Paris", "Hilton"), ("Victoria", "Lincoln"),
    ("Washington", "Ortiz"), ("Austin", "Dallas"), ("Jordan", "Brooks"), ("Summer", "Rain"), ("Hope", "Church"),
    ("Destiny", "Wells"), ("Royal", "King"), ("Pearl", "Marsh"), ("Chase", "Bank"), ("Dawn", "Street"),
    ("Nguyen", "Thi Lan"), ("Tran", "Van Minh"), ("Wei", "Zhang"), ("Xiaoming", "Li"), ("Ji-woo", "Park"),
    ("Min-jun", "Kim"), ("Oluwaseun", "Adeyemi"), ("Chukwuemeka", "Okafor"), ("Aaliyah", "Abdullah"),
    ("Mohammed", "Al-Rashid"), ("Fatima", "El-Amin"), ("Siobhan", "O'Sullivan"), ("Seamus", "MacDonald"),
    ("Maria", "De La Cruz"), ("Jose", "Garcia-Lopez"), ("Hendrik", "Van Der Berg"), ("Running", "Bear"),
    ("Kai", "Nakamura"), ("Priya", "Venkataraman"), ("Anh", "Le"), ("Bo", "Ng"), ("Xi", "Wu"), ("Al", "Fox"),
    ("Ivy", "Ross"), ("Sterling", "Silver"), ("Miles", "Long"), ("Bill", "Gates"), ("Ray", "Charles"),
    ("Tiffany", "Rodriguez-Smith"), ("D'Andre", "Washington"), ("Ja'Marcus", "Williams"), ("Le'Asia", "Jones"),
]

REAL_CITIES = [
    ("Austin", "TX", "787"), ("Houston", "TX", "770"), ("Dallas", "TX", "752"), ("San Antonio", "TX", "782"),
    ("El Paso", "TX", "799"), ("Fort Worth", "TX", "761"), ("Miami", "FL", "331"), ("Orlando", "FL", "328"),
    ("Tampa", "FL", "336"), ("Jacksonville", "FL", "322"), ("Fort Lauderdale", "FL", "333"), ("Atlanta", "GA", "303"),
    ("Savannah", "GA", "314"), ("Charlotte", "NC", "282"), ("Raleigh", "NC", "276"), ("Nashville", "TN", "372"),
    ("Memphis", "TN", "381"), ("Phoenix", "AZ", "850"), ("Tucson", "AZ", "857"), ("Los Angeles", "CA", "900"),
    ("San Diego", "CA", "921"), ("Sacramento", "CA", "958"), ("Fresno", "CA", "937"), ("Oakland", "CA", "946"),
    ("Las Vegas", "NV", "891"), ("Denver", "CO", "802"), ("Chicago", "IL", "606"), ("Springfield", "IL", "627"),
    ("Detroit", "MI", "482"), ("Grand Rapids", "MI", "495"), ("Columbus", "OH", "432"), ("Cleveland", "OH", "441"),
    ("Pittsburgh", "PA", "152"), ("Philadelphia", "PA", "191"), ("New York", "NY", "100"), ("Brooklyn", "NY", "112"),
    ("Buffalo", "NY", "142"), ("Newark", "NJ", "071"), ("Boston", "MA", "021"), ("Baltimore", "MD", "212"),
    ("Richmond", "VA", "232"), ("Seattle", "WA", "981"), ("Spokane", "WA", "992"), ("Portland", "OR", "972"),
    ("Kansas City", "MO", "641"), ("St. Louis", "MO", "631"), ("New Orleans", "LA", "701"),
    ("Baton Rouge", "LA", "708"), ("Birmingham", "AL", "352"), ("Louisville", "KY", "402"), ("Tulsa", "OK", "741"),
    ("Oklahoma City", "OK", "731"), ("Albuquerque", "NM", "871"), ("Salt Lake City", "UT", "841"),
    ("Minneapolis", "MN", "554"), ("Milwaukee", "WI", "532"), ("Indianapolis", "IN", "462"), ("Omaha", "NE", "681"),
    ("Little Rock", "AR", "722"), ("Jackson", "MS", "392"), ("Columbia", "SC", "292"), ("Boise", "ID", "837"),
    ("Pine Bluff", "AR", "716"), ("Fort Wayne", "IN", "468"), ("Long Beach", "CA", "908"), ("Sedona", "AZ", "863"),
    ("Kilgore", "TX", "756"), ("Wichita", "KS", "672"), ("Hialeah", "FL", "330"), ("Corpus Christi", "TX", "784"),
]
AREA_CODES = {"TX": [512, 737, 713, 281, 832, 214, 469, 972, 210, 915, 817, 903, 361, 806], "FL": [305, 786, 407,
              321, 813, 727, 904, 954, 561], "GA": [404, 470, 678, 912], "NC": [704, 980, 919, 984], "TN": [615, 629,
              901], "AZ": [602, 480, 520, 928], "CA": [213, 310, 323, 619, 858, 916, 559, 510, 562, 714], "NV": [702,
              725], "CO": [303, 720], "IL": [312, 773, 217], "MI": [313, 616], "OH": [614, 216], "PA": [412, 215,
              267], "NY": [212, 646, 718, 347, 716], "NJ": [973, 201], "MA": [617, 857], "MD": [410, 443], "VA": [804],
              "WA": [206, 509], "OR": [503, 971], "MO": [816, 314], "LA": [504, 225], "AL": [205], "KY": [502],
              "OK": [918, 405], "NM": [505], "UT": [801], "MN": [612], "WI": [414], "IN": [317, 260], "NE": [402],
              "AR": [501, 870], "MS": [601], "SC": [803], "ID": [208], "KS": [316]}
STREET_NAMES = ["Oak", "Maple", "Elm", "Cedar", "Pine", "Main", "Church", "Bank", "Mill", "Park", "Lake", "Hill",
                "Washington", "Lincoln", "Jefferson", "Madison", "Franklin", "Martin Luther King Jr", "Old Mill",
                "Country Club", "Sunset", "Riverside", "Highland", "Magnolia", "Peachtree", "Live Oak", "Pecan",
                "Willow", "Bluebonnet", "Mockingbird", "Cypress", "Sycamore", "Dogwood", "Juniper", "Chestnut",
                "Spring Valley", "Fox Run", "Deer Creek", "Shady Grove", "Windmill", "Prairie View", "Canyon Ridge",
                "5th", "21st", "3rd", "42nd", "112th", "Oakridge", "Brookhollow", "Stonebridge", "Hawthorne"]
STREET_SUFFIXES = ["St", "Street", "Ave", "Avenue", "Rd", "Road", "Dr", "Drive", "Ln", "Lane", "Blvd", "Ct", "Way",
                   "Pl", "Cir", "Trl", "Pkwy", "Ter", "Hwy", "Loop", "Cove", "Bend", "Pass", "Run", "Trace"]

DL_FORMATS = {  # state -> generator
    "TX": lambda r: "".join(r.choices(string.digits, k=8)),
    "CA": lambda r: r.choice(string.ascii_uppercase) + "".join(r.choices(string.digits, k=7)),
    "FL": lambda r: (lambda d: f"{r.choice(string.ascii_uppercase)}{d[:3]}-{d[3:6]}-{d[6:8]}-{d[8:11]}-{d[11]}")(
        "".join(r.choices(string.digits, k=12))),
    "NY": lambda r: "".join(r.choices(string.digits, k=9)),
    "IL": lambda r: r.choice(string.ascii_uppercase) + "".join(r.choices(string.digits, k=11)),
    "GA": lambda r: "".join(r.choices(string.digits, k=9)),
    "AZ": lambda r: r.choice("ABDY") + "".join(r.choices(string.digits, k=8)),
    "WA": lambda r: "WDL" + "".join(r.choices(string.ascii_uppercase + string.digits, k=9)),
    "PA": lambda r: "".join(r.choices(string.digits, k=8)),
    "OH": lambda r: "".join(r.choices(string.ascii_uppercase, k=2)) + "".join(r.choices(string.digits, k=6)),
}
PLATE_FORMATS = [
    lambda r: "".join(r.choices("ABCDEFGHJKLMNPRSTVWXYZ", k=3)) + "-" + "".join(r.choices(string.digits, k=4)),
    lambda r: r.choice("123456789") + "".join(r.choices("ABCDEFGHJKLMNPRSTVWXYZ", k=3)) + "".join(
        r.choices(string.digits, k=3)),
    lambda r: "".join(r.choices("ABCDEFGHJKLMNPRSTVWXYZ", k=3)) + " " + "".join(r.choices(string.digits, k=4)),
    lambda r: "".join(r.choices("ABCDEFGHJKLMNPRSTVWXYZ", k=2)) + "".join(r.choices(string.digits, k=1)) + "-" +
    "".join(r.choices("ABCDEFGHJKLMNPRSTVWXYZ", k=1)) + "".join(r.choices(string.digits, k=3)),
    lambda r: "".join(r.choices("ABCDEFGHJKLMNPRSTVWXYZ0123456789", k=7)),
]
VEHICLES = [("Honda", "Accord", "1HG"), ("Honda", "Civic", "2HG"), ("Toyota", "Camry", "4T1"), ("Toyota", "Corolla", "2T1"),
            ("Toyota", "Tacoma", "3TM"), ("Ford", "F-150", "1FT"), ("Ford", "Explorer", "1FM"), ("Ford", "Fusion", "3FA"),
            ("Chevrolet", "Silverado", "1GC"), ("Chevrolet", "Malibu", "1G1"), ("Chevrolet", "Equinox", "2GN"),
            ("Nissan", "Altima", "1N4"), ("Nissan", "Rogue", "5N1"), ("Hyundai", "Elantra", "5NP"),
            ("Hyundai", "Sonata", "KMH"), ("Kia", "Optima", "5XX"), ("Dodge", "Ram 1500", "1C6"),
            ("Jeep", "Grand Cherokee", "1C4"), ("Tesla", "Model 3", "5YJ"), ("BMW", "X5", "5UX"),
            ("Subaru", "Outback", "4S4"), ("Volkswagen", "Jetta", "3VW"), ("GMC", "Sierra", "1GT"),
            ("Freightliner", "Cascadia", "3AK"), ("Kenworth", "T680", "1XK")]
COLORS = ["white", "black", "silver", "gray", "red", "blue", "dark blue", "maroon", "green", "tan", "gold"]
INSURERS = ["State Farm Mutual Automobile Insurance Company", "GEICO General Insurance Company",
            "Progressive County Mutual Insurance Company", "Allstate Fire and Casualty Insurance Company",
            "USAA Casualty Insurance Company", "Liberty Mutual Insurance Company", "Farmers Insurance Exchange",
            "Nationwide Mutual Insurance Company", "Travelers Indemnity Company", "Root Insurance Company"]
HEALTH_PLANS = ["Blue Cross Blue Shield of Texas", "Aetna Choice POS II", "UnitedHealthcare Choice Plus",
                "Cigna Open Access Plus", "Humana Gold Plus HMO", "Ambetter from Superior HealthPlan",
                "Texas Medicaid (STAR)", "Medicare Part B", "Oscar Health Bronze Classic", "Kaiser Permanente HMO"]
EMPLOYERS = ["Acme Logistics LLC", "Lone Star Plumbing Services", "H&R Distribution Co.", "Riverside Dental Group",
             "Brightline Staffing Inc.", "Summit Roofing & Construction", "Metro Transit Authority",
             "Coastal Freight Lines", "Golden Corral", "Amazon Fulfillment Center DFW7", "Baylor Scott & White",
             "Pinnacle Auto Body", "Greenway Landscaping", "Sunrise Senior Living", "TechNova Solutions",
             "Fiesta Mart", "City of Pine Bluff", "Westside Elementary School", "QuikTrip Corporation",
             "Blue Ridge Electric"]
JOBS = ["warehouse associate", "forklift operator", "dental hygienist", "delivery driver", "line cook",
        "registered nurse", "electrician", "bus driver", "roofer", "cashier", "night manager", "teacher's aide",
        "HVAC technician", "home health aide", "store manager", "software developer", "mechanic", "bartender",
        "security guard", "medical assistant"]
ROUTING = ["021000021", "026009593", "121000248", "111000025", "322271627", "063100277", "111900659", "113000023",
           "071000013", "044000037", "031100649", "061000104", "053000219", "082000549", "102001017", "114000093"]
BANKS = {"021000021": "JPMorgan Chase Bank", "026009593": "Bank of America", "121000248": "Wells Fargo Bank",
         "111000025": "Bank of America (Texas)", "322271627": "Chase (California)", "063100277": "Bank of America (FL)",
         "111900659": "Wells Fargo (Texas)", "113000023": "Wells Fargo (Houston)", "071000013": "JPMorgan Chase (IL)",
         "044000037": "JPMorgan Chase (OH)", "031100649": "Discover Bank", "061000104": "Truist Bank",
         "053000219": "Wells Fargo (NC)", "082000549": "Regions Bank", "102001017": "U.S. Bank",
         "114000093": "Frost Bank"}


def ssn(r: random.Random) -> str:
    while True:
        a, g, s = r.randint(1, 899), r.randint(1, 99), r.randint(1, 9999)
        v = f"{a:03d}-{g:02d}-{s:04d}"
        if V.ssn_ok(v):
            return v


def luhn_complete(r: random.Random, prefix: str, length: int) -> str:
    body = prefix + "".join(r.choices(string.digits, k=length - len(prefix) - 1))
    return body + str(V.luhn_check_digit(body))


def card(r: random.Random) -> tuple[str, str]:
    kind = r.choice(["visa", "mc", "amex", "discover"])
    if kind == "visa":
        n = luhn_complete(r, "4" + str(r.randint(0, 9)), 16)
    elif kind == "mc":
        n = luhn_complete(r, str(r.randint(51, 55)), 16)
    elif kind == "amex":
        n = luhn_complete(r, r.choice(["34", "37"]), 15)
        return "American Express", f"{n[:4]} {n[4:10]} {n[10:]}"
    else:
        n = luhn_complete(r, "6011", 16)
    sep = r.choice([" ", "-", ""])
    name = {"visa": "Visa", "mc": "Mastercard", "discover": "Discover"}[kind]
    return name, sep.join(n[i:i + 4] for i in range(0, 16, 4))


def aba(r: random.Random) -> str:
    return r.choice(ROUTING)


def npi(r: random.Random) -> str:
    body = r.choice("12") + "".join(r.choices(string.digits, k=8))
    for c in range(10):
        if V.npi_ok(body + str(c)):
            return body + str(c)
    raise AssertionError


def dea(r: random.Random, last: str) -> str:
    first = r.choice("ABFGM")
    second = (last[0].upper() if last and last[0].isalpha() else "X")
    d = [r.randint(0, 9) for _ in range(6)]
    chk = ((d[0] + d[2] + d[4]) + 2 * (d[1] + d[3] + d[5])) % 10
    return first + second + "".join(map(str, d)) + str(chk)


def ein(r: random.Random) -> str:
    while True:
        v = f"{r.randint(10, 99):02d}-{r.randint(0, 9999999):07d}"
        if V.ein_ok(v):
            return v


def vin(r: random.Random, wmi: str, year: int) -> str:
    alphabet = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
    year_codes = "ABCDEFGHJKLMNPRSTVWXY123456789"
    yc = year_codes[(year - 2010) % 30]
    while True:
        body = wmi + "".join(r.choices(alphabet, k=5)) + "0" + yc + r.choice(alphabet) + "".join(
            r.choices(string.digits, k=6))
        weights = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
        total = sum(V._VIN_MAP[c] * w for c, w in zip(body, weights))
        cd = total % 11
        v = body[:8] + ("X" if cd == 10 else str(cd)) + body[9:]
        if V.vin_checkdigit_ok(v):
            return v


def mbi(r: random.Random) -> str:
    A = "ACDEFGHJKMNPQRTUVWXY"
    AN = A + string.digits
    while True:
        v = (r.choice("123456789") + r.choice(A) + r.choice(AN) + r.choice(string.digits) + r.choice(A) +
             r.choice(AN) + r.choice(string.digits) + r.choice(A) + r.choice(A) + r.choice(string.digits) +
             r.choice(string.digits))
        if V.mbi_ok(v):
            return f"{v[:4]}-{v[4:7]}-{v[7:]}"


def iban_de(r: random.Random) -> str:
    bban = "".join(r.choices(string.digits, k=18))
    rearr = bban + "1314" + "00"  # D=13, E=14
    chk = 98 - int(rearr) % 97
    v = f"DE{chk:02d}{bban}"
    assert V.iban_ok(v)
    return " ".join(v[i:i + 4] for i in range(0, len(v), 4))


@dataclass
class Address:
    street: str
    unit: str
    city: str
    state: str
    zip: str

    def one_line(self) -> str:
        u = f", {self.unit}" if self.unit else ""
        return f"{self.street}{u}, {self.city}, {self.state} {self.zip}"

    def lines(self) -> tuple[str, str]:
        u = f" {self.unit}" if self.unit else ""
        return f"{self.street}{u}", f"{self.city}, {self.state} {self.zip}"


@dataclass
class Vehicle:
    year: int
    make: str
    model: str
    color: str
    vin: str
    plate: str
    plate_state: str

    def desc(self) -> str:
        return f"{self.color} {self.year} {self.make} {self.model}"


@dataclass
class Person:
    first: str
    middle: str
    last: str
    sex: str
    dob: date
    ssn: str
    phone: str
    cell: str
    email: str
    address: Address
    dl: str
    dl_state: str
    employer: str
    job: str
    hourly: float
    vehicle: Vehicle | None = None
    member_id: str = ""
    group_no: str = ""
    health_plan: str = ""
    children: list["Person"] = field(default_factory=list)
    spouse: "Person | None" = None
    username: str = ""
    card: tuple[str, str] = ("", "")
    bank_account: str = ""
    routing: str = ""
    mbi: str = ""

    @property
    def full(self) -> str:
        return f"{self.first} {self.last}"

    @property
    def full_middle(self) -> str:
        return f"{self.first} {self.middle[0]}. {self.last}" if self.middle else self.full

    @property
    def last_first(self) -> str:
        m = f" {self.middle[0]}" if self.middle else ""
        return f"{self.last.upper()}, {self.first.upper()}{m}"

    def age(self, on: date) -> int:
        return on.year - self.dob.year - ((on.month, on.day) < (self.dob.month, self.dob.day))


class Gen:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        Faker.seed(seed)
        self.used_names: set[str] = set()

    # --- primitives -----------------------------------------------------------------------
    def name(self, sex: str | None = None) -> tuple[str, str, str, str]:
        r = self.r
        sex = sex or r.choice("MF")
        for _ in range(50):
            if r.random() < 0.12:
                first, last = r.choice(HARD_NAMES)
                middle = ""
            else:
                loc = r.choices([l for l, _ in _LOCALES], weights=[w for _, w in _LOCALES])[0]
                f = _FAKERS[loc]
                first = f.first_name_male() if sex == "M" else f.first_name_female()
                last = f.last_name()
                middle = (f.first_name_male() if sex == "M" else f.first_name_female()) if r.random() < 0.5 else ""
            key = f"{first} {last}"
            if key not in self.used_names and len(last) > 1:
                self.used_names.add(key)
                return first, middle, last, sex
        return first, middle, last, sex

    def city(self) -> tuple[str, str, str]:
        c, st, z3 = self.r.choice(REAL_CITIES)
        return c, st, f"{z3}{self.r.randint(1, 99):02d}"

    def address(self, city=None) -> Address:
        r = self.r
        c, st, z = city or self.city()
        if len(z) == 3:
            z = f"{z}{r.randint(1, 99):02d}"
        num = r.choice([r.randint(100, 9999), r.randint(10, 99), r.randint(10000, 29999)])
        pre = r.choice(["", "", "", "N ", "S ", "E ", "W ", "N. ", "West "])
        street = f"{num} {pre}{r.choice(STREET_NAMES)} {r.choice(STREET_SUFFIXES)}"
        unit = r.choice(["", "", "", f"Apt {r.randint(1, 40)}{r.choice(['', 'A', 'B', 'C'])}",
                         f"Unit {r.randint(100, 999)}", f"#{r.randint(1, 300)}", f"Suite {r.randint(100, 900)}"])
        if r.random() < 0.06:
            street = f"P.O. Box {r.randint(100, 99999)}"
            unit = ""
        return Address(street, unit, c, st, z + (f"-{r.randint(1000, 9999)}" if r.random() < 0.15 else ""))

    def phone(self, state: str) -> str:
        r = self.r
        ac = r.choice(AREA_CODES.get(state, [512]))
        ex = r.randint(200, 999)
        while ex % 100 == 11:
            ex = r.randint(200, 999)
        ln = r.randint(0, 9999)
        fmt = r.choice(["({a}) {e}-{l}", "{a}-{e}-{l}", "{a}.{e}.{l}", "({a}){e}-{l}", "+1 {a} {e} {l}",
                        "1-{a}-{e}-{l}"])
        return fmt.format(a=ac, e=ex, l=f"{ln:04d}")

    def email(self, first: str, last: str) -> str:
        r = self.r
        f = "".join(c for c in first.lower() if c.isalnum()) or "user"
        l = "".join(c for c in last.lower() if c.isalnum()) or "x"
        user = r.choice([f"{f}.{l}", f"{f[0]}{l}", f"{f}{l}{r.randint(1, 99)}", f"{f}_{l}", f"{l}.{f}{r.randint(70, 99)}"])
        return f"{user}@{r.choice(['gmail.com', 'yahoo.com', 'outlook.com', 'icloud.com', 'hotmail.com', 'att.net', 'aol.com', 'protonmail.com'])}"

    def dob(self, min_age=18, max_age=80, ref: date = date(2024, 1, 1)) -> date:
        return ref - timedelta(days=self.r.randint(min_age * 365, max_age * 365))

    def dl(self, state: str) -> str:
        return DL_FORMATS.get(state, DL_FORMATS["TX"])(self.r)

    def plate(self) -> str:
        return self.r.choice(PLATE_FORMATS)(self.r)

    def vehicle(self, state: str) -> Vehicle:
        make, model, wmi = self.r.choice(VEHICLES)
        year = self.r.randint(2010, 2024)
        return Vehicle(year, make, model, self.r.choice(COLORS), vin(self.r, wmi, year), self.plate(), state)

    def mrn(self) -> str:
        r = self.r
        return r.choice([f"{r.randint(10 ** 7, 10 ** 8 - 1)}", f"MR{r.randint(10 ** 6, 10 ** 7 - 1)}",
                         f"E{r.randint(10 ** 8, 10 ** 9 - 1)}", f"{r.randint(100, 999)}-{r.randint(10 ** 5, 10 ** 6 - 1)}",
                         f"00{r.randint(10 ** 6, 10 ** 7 - 1)}"])

    def member_id(self) -> str:
        r = self.r
        return r.choice([f"XWH{r.randint(10 ** 8, 10 ** 9 - 1)}", f"W{r.randint(10 ** 8, 10 ** 9 - 1)}",
                         f"U{r.randint(10 ** 7, 10 ** 8 - 1)}01", f"{''.join(r.choices(string.ascii_uppercase, k=3))}"
                         f"{r.randint(10 ** 8, 10 ** 9 - 1)}", f"JQK{r.randint(10 ** 6, 10 ** 7 - 1)}"])

    def group_no(self) -> str:
        r = self.r
        return r.choice([f"{r.randint(10 ** 5, 10 ** 6 - 1)}", f"GRP-{r.randint(1000, 9999)}",
                         f"0{r.randint(10 ** 6, 10 ** 7 - 1)}"])

    def claim_no(self) -> str:
        r = self.r
        y = r.randint(2021, 2024)
        return r.choice([f"CLM-{y}-{r.randint(10 ** 6, 10 ** 7 - 1)}", f"{r.randint(10, 99)}-{r.randint(1000, 9999)}-"
                         f"{r.randint(100, 999)}", f"{y}WC{r.randint(10 ** 5, 10 ** 6 - 1)}",
                         f"0{r.randint(10 ** 8, 10 ** 9 - 1)}-01", f"LA-{r.randint(10 ** 6, 10 ** 7 - 1)}-{r.randint(1, 9):02d}"])

    def policy_no(self, state="TX") -> str:
        r = self.r
        return r.choice([f"{state}-AUTO-{r.randint(10 ** 6, 10 ** 7 - 1)}", f"PAP {r.randint(10 ** 9, 10 ** 10 - 1)}",
                         f"{r.randint(10 ** 6, 10 ** 7 - 1)}-{r.randint(10, 99)}", f"POL{r.randint(10 ** 8, 10 ** 9 - 1)}",
                         f"{r.randint(100, 999)} {r.randint(1000, 9999)}-{r.choice('ABCDEFG')}{r.randint(10, 99)}-{r.randint(10, 99)}"])

    def case_no(self) -> str:
        r = self.r
        y = r.randint(21, 24)
        return r.choice([f"20{y}-CA-{r.randint(100, 999999):06d}", f"1:{y}-cv-{r.randint(1000, 99999):05d}",
                         f"D-1-GN-{y}-{r.randint(100, 999999):06d}", f"CACE-{y}-{r.randint(100, 999999):06d}",
                         f"BC{r.randint(100000, 999999)}", f"{y}-L-{r.randint(100, 999999):06d}",
                         f"4:{y}-cv-{r.randint(100, 9999):04d}-ALM"])

    def report_no(self, agency="APD") -> str:
        r = self.r
        y = r.randint(2021, 2024)
        return r.choice([f"{agency}-{y}-{r.randint(10 ** 5, 10 ** 6 - 1)}", f"{str(y)[2:]}-{r.randint(10 ** 5, 10 ** 6 - 1)}",
                         f"{y}{r.randint(10 ** 6, 10 ** 7 - 1)}"])

    def account(self) -> str:
        return str(self.r.randint(10 ** 7, 10 ** 12 - 1))

    def person(self, sex=None, min_age=18, max_age=80, city=None, with_family=False) -> Person:
        r = self.r
        first, middle, last, sex = self.name(sex)
        addr = self.address(city)
        state = addr.state
        p = Person(first, middle, last, sex, self.dob(min_age, max_age), ssn(r), self.phone(state), self.phone(state),
                   self.email(first, last), addr, self.dl(state), state, r.choice(EMPLOYERS), r.choice(JOBS),
                   round(r.uniform(14, 48), 2))
        p.vehicle = self.vehicle(state)
        p.member_id, p.group_no, p.health_plan = self.member_id(), self.group_no(), r.choice(HEALTH_PLANS)
        p.username = r.choice([f"@{first.lower()}{last.lower()[:3]}{r.randint(1, 99)}", f"@{last.lower()}_{r.randint(80, 99)}",
                               f"{first.lower()}.{last.lower()}{r.randint(1, 9)}"])
        p.card = card(r)
        p.bank_account = self.account()
        p.routing = aba(r)
        p.mbi = mbi(r)
        if with_family:
            sp_sex = "F" if sex == "M" else "M"
            sfirst, smid, _, _ = self.name(sp_sex)
            p.spouse = Person(sfirst, smid, last, sp_sex, self.dob(20, 70), ssn(r), self.phone(state), self.phone(state),
                              self.email(sfirst, last), addr, self.dl(state), state, r.choice(EMPLOYERS), r.choice(JOBS),
                              round(r.uniform(14, 48), 2))
            for _ in range(r.randint(0, 3)):
                cs = r.choice("MF")
                cfirst, cmid, _, _ = self.name(cs)
                child = Person(cfirst, cmid, last, cs, self.dob(1, 17), ssn(r), "", "", "", addr, "", state, "", "", 0)
                p.children.append(child)
        return p

    def money(self, lo, hi) -> str:
        return f"${self.r.uniform(lo, hi):,.2f}"

    def date_between(self, a: date, b: date) -> date:
        return a + timedelta(days=self.r.randint(0, max(0, (b - a).days)))


def fmt_date(d: date, r: random.Random | None = None, style: str | None = None) -> str:
    style = style or (r.choice(["mdy", "mdy0", "long", "short", "iso"]) if r else "mdy0")
    if style == "mdy":
        return f"{d.month}/{d.day}/{d.year}"
    if style == "mdy0":
        return f"{d.month:02d}/{d.day:02d}/{d.year}"
    if style == "long":
        return d.strftime("%B ") + f"{d.day}, {d.year}"
    if style == "short":
        return d.strftime("%b. ") + f"{d.day}, {d.year}"
    if style == "iso":
        return d.isoformat()
    if style == "dmy_mon":
        return d.strftime("%d-%b-%Y").upper()
    return d.isoformat()
