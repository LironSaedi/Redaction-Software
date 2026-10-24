"""Street-address detection (US-first, with Canadian/UK postcodes).

Grammar: number [predirectional] street-name suffix [postdirectional] [unit] [, city, state ZIP]
plus PO boxes, rural routes, numbered highways and stand-alone "City, ST 12345" lines.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from .base import NormText, Span

STATE_ABBR = ("AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|"
              "NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|PR|VI|GU|AS|MP|"
              "AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT")
STATE_NAMES = ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|"
               "Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|"
               "Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|"
               "New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|"
               "Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|"
               "West Virginia|Wisconsin|Wyoming|Puerto Rico|Ontario|Quebec|British Columbia|Alberta")
STATE_ABBR_DOTTED = r"(?:Ala|Ariz|Ark|Calif|Cal|Colo|Conn|Del|Fla|Ga|Ill|Ind|Kan|Kans|Ky|La|Md|Mass|Mich|Minn|Miss|" \
                    r"Mo|Mont|Neb|Nebr|Nev|N\.H|N\.J|N\.M|N\.Y|N\.C|N\.D|Okla|Ore|Pa|Penn|R\.I|S\.C|S\.D|Tenn|Tex|" \
                    r"Vt|Va|Wash|W\.Va|Wis|Wyo)\."

SUFFIXES = (
    "Street|St|Str|Avenue|Ave|Av|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Place|Pl|Way|Wy|Parkway|Pkwy|"
    "Pky|Highway|Hwy|Circle|Cir|Terrace|Ter|Terr|Trail|Trl|Tr|Square|Sq|Loop|Lp|Run|Pike|Row|Crossing|Xing|Path|"
    "Point|Alley|Aly|Bend|Bnd|Cove|Cv|Expressway|Expy|Freeway|Fwy|Hill|Hl|Hills|Hls|Hollow|Holw|Junction|Jct|"
    "Manor|Mnr|Pass|Plaza|Plz|Ridge|Rdg|Route|Rte|Spur|Station|Sta|Turnpike|Tpke|View|Vw|Walk|Creek|Crk|Estates|"
    "Ests|Grove|Grv|Heights|Hts|Lake|Lk|Lakes|Meadow|Meadows|Mdws|Mountain|Mtn|Park|Pk|Parks|Shore|Shores|Shr|"
    "Spring|Springs|Spg|Spgs|Valley|Vly|Vista|Vis|Village|Vlg|Knoll|Knolls|Knl|Glen|Gln|Green|Grn|Harbor|Hbr|"
    "Landing|Lndg|Mews|Oval|Ramp|Commons|Cmns|Close|Crescent|Cres|Causeway|Cswy|Center|Ctr|Corner|Cor|Crest|Dale|"
    "Dam|Divide|Dv|Field|Fld|Fields|Flds|Flat|Flt|Ford|Frd|Forest|Frst|Fork|Frk|Garden|Gdn|Gardens|Gdns|Gateway|"
    "Gtwy|Island|Isle|Mall|Mill|Mills|Orchard|Orch|Pines|Pnes|Plains|Pln|Port|Prt|Prairie|Ranch|Rnch|Rapids|"
    "Rest|Rst|Shoal|Skyway|Summit|Smt|Trace|Trce|Track|Trak|Tunnel|Tunl|Union|Viaduct|Via|Ville|Vl|Wells|"
    "Wls|Byway|Byp|Bypass|Concourse|Cmn|Common|Extension|Ext|Overpass|Opas|Underpass|Upas|Promenade|Prom|Esplanade|"
    "Quay|Wharf|Rise|Chase|Gate|Gardens|Walkway|Bluff|Blf|Canyon|Cyn|Cliff|Clf|Coves|Downs|Glade|Hideaway|Pointe|"
    # remainder of USPS Publication 28 (full names + standard abbreviations)
    "Branch|Br|Brook|Brk|Brooks|Brks|Burg|Bg|Burgs|Bgs|Cape|Cpe|Centers|Ctrs|Circles|Cirs|Cliffs|Clfs|Corners|Cors|"
    "Courts|Cts|Crossroad|Xrd|Curve|Curv|Drives|Drs|Estate|Est|Extensions|Exts|Falls|Fls|Ferry|Fry|Fords|Frds|"
    "Forge|Frg|Forges|Frgs|Forks|Frks|Fort|Ft|Glens|Glns|Greens|Grns|Groves|Grvs|Harbors|Hbrs|Haven|Hvn|Inlet|Inlt|"
    "Islands|Iss|Junctions|Jcts|Keys|Kys|Lights|Lgts|Locks|Lcks|Lodge|Ldg|Manors|Mnrs|Motorway|Mtwy|Mount|Mt|"
    "Mountains|Mtns|Parkways|Passage|Psge|Pnes|Plain|Pln|Plains|Plns|Points|Pts|Ports|Prts|Radial|Radl|Rapid|Rpd|"
    "Rpds|Ridges|Rdgs|River|Riv|Roads|Rds|Rue|Shoals|Shls|Spurs|Squares|Sqs|Stravenue|Stra|Stream|Strm|Streets|Sts|"
    "Throughway|Trwy|Trafficway|Trfy|Unions|Uns|Valleys|Vlys|Views|Vws|Villages|Vlgs|Ways|Lf|Lck|Lgt|Ky|Msn|Nck|"
    "Pne|Wl|Clb|Crse|Cp"
)
# suffixes that are also everyday words: only full-confidence with a city/ZIP/unit or label after them
WEAK_SUFFIXES = {"club", "key", "land", "light", "lights", "lock", "locks", "loaf", "mission", "neck", "wall", "well",
                 "course", "camp", "fall", "falls", "haven", "river", "mount", "plain", "rest", "union", "port", "pine",
                 "green", "center", "station", "mall", "park", "point", "lake", "spring", "hill", "view", "walk",
                 "fork", "branch", "brook", "cape", "fort", "trace", "track", "pass", "run", "row", "gate", "chase",
                 "rise", "common", "commons", "village", "lodge", "ferry", "stream", "dale", "glen", "grove", "field"}
_UPPER_SUFFIXES = ""  # filled below once SUFFIXES is final
DIRECTIONS = r"(?:N|S|E|W|NE|NW|SE|SW|North|South|East|West|Northeast|Northwest|Southeast|Southwest)\.?"
SUFFIXES = SUFFIXES + "|Club|Course|Camp|Fall|Key|Land|Light|Loaf|Lock|Mission|Neck|Wall|Well"
# ALL-CAPS forms only for the common suffixes; rare abbreviations ("BR", "CP") in caps are too ambiguous
_UPPER_SUFFIXES = ("STREET|ST|AVENUE|AVE|AV|BOULEVARD|BLVD|ROAD|RD|DRIVE|DR|LANE|LN|COURT|CT|PLACE|PL|WAY|PARKWAY|PKWY|"
                   "HIGHWAY|HWY|CIRCLE|CIR|TERRACE|TER|TRAIL|TRL|SQUARE|SQ|LOOP|PIKE|TURNPIKE|TPKE|EXPRESSWAY|EXPY|"
                   "FREEWAY|FWY|CROSSING|XING|RUN|PASS|COVE|CV|BEND|POINT|RIDGE|RDG|ROUTE|RTE|PLAZA|PLZ|ALLEY|ALY")
UNIT = (r"(?:,?\s*(?:Apt|Apartment|Suite|Ste|Unit|Rm|Room|Fl|Floor|Bldg|Building|Lot|Trlr|Trailer|Space|Spc|"
        r"Dept|Department|Office|Ofc|Box|Slip|Pier|Hangar|Stop|PMB|Penthouse|PH|Basement|Bsmt|Rear|Front|Upper|"
        r"Lower|Side)\.?\s*#?\s*[A-Za-z0-9][A-Za-z0-9-]{0,6}|,?\s*#\s*[A-Za-z0-9][A-Za-z0-9-]{0,6})")
_NAMEWORD = r"(?:(?!(?:Dr|Mr|Mrs|Ms|Rev|Hon|Sgt|Lt|Capt|Det)\.)[A-Z][A-Za-z'’-]+\.?|\d{1,3}(?:st|nd|rd|th|ST|ND|RD|TH)|(?:of|the|de|la|del|los|las|el|du|von|van)(?=\s+[A-Z]))"
CITY = r"[A-Z][A-Za-z.'’-]+(?:[ \t]+[A-Z][A-Za-z.'’-]+){0,3}"
STATE = rf"(?:{STATE_ABBR}|{STATE_NAMES}|{STATE_ABBR_DOTTED})"
ZIP = r"\d{5}(?:-\d{4})?"
CA_POST = r"[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\s?\d[ABCEGHJ-NPRSTV-Z]\d"
UK_POST = r"(?:GIR\s?0AA|[A-PR-UWYZ][A-HK-Y]?\d[A-Z\d]?\s?\d[ABD-HJLNP-UW-Z]{2})"
CITY_STATE_ZIP = rf"(?:,?\s*(?:\n\s*)?{CITY},?\s+{STATE}(?:\.)?(?:,?\s+(?:{ZIP}|{CA_POST}))?)"

_NUMBER = r"(?<![\w$#./-])(?:\d{1,6}(?:-\d{1,5})?[A-Za-z]?(?:\s+\d/\d)?|[A-Z]?\d{1,6}[A-Z]?)"
_STREET = (rf"{_NUMBER}[ \t]{{1,2}}(?:{DIRECTIONS}[ \t]+)?{_NAMEWORD}(?:[ \t]+{_NAMEWORD}){{0,4}}[ \t]+(?:{SUFFIXES}|(?-i:{_UPPER_SUFFIXES}))\.?"
           rf"(?![A-Za-z])(?:\s+{DIRECTIONS}(?![A-Za-z]))?")
_HIGHWAY = (rf"{_NUMBER}\s+(?:(?:{DIRECTIONS})\s+)?(?:State\s+(?:Route|Road|Highway|Hwy|Rte)|County\s+(?:Road|Rd|"
            rf"Route|Highway|Hwy)|Farm\s+to\s+Market\s+Road|FM|US|U\.S\.|SR|CR|Hwy|Highway|Route|Rte|Interstate|I)"
            rf"[\s-]*\d{{1,4}}[A-Z]?(?:\s+{DIRECTIONS}(?![A-Za-z]))?")
_POBOX = r"(?<![\w])(?:P\.?\s?O\.?\s*Box|Post\s+Office\s+Box|PO\s+Drawer|P\.O\.\s+Drawer|Box)\s+#?\s*\d{1,7}"
_RURAL = r"(?<![\w])(?:(?:Rural\s+Route|Star\s+Route)\s*#?\s*\d{1,4}(?:,?\s+Box\s+\d{1,5})?|(?:RR|R\.R\.|HC)\s*#?\s*\d{1,4},?\s+Box\s+\d{1,5})"

_LETTERED = rf"{_NUMBER}[ \t]{{1,2}}(?:Avenue|Ave|AVENUE|AVE|Street|St|STREET|ST|Road|Rd|ROAD|RD)[ \t]+[A-Z](?![\w])"
_CITY_ZIP = rf"(?:,?\s*{CITY},?\s+{ZIP})"
_ADDR = re.compile(rf"(?:{_STREET}|{_LETTERED}|{_HIGHWAY}|{_POBOX}|{_RURAL})(?:{UNIT})?(?:{CITY_STATE_ZIP}|{_CITY_ZIP})?")
_CSZ_CAPS = re.compile(rf"(?<![\w])([A-Z]{{3,}}(?:[ ][A-Z]{{2,}}){{0,3}})[ \t]{{1,40}}(?:{STATE_ABBR})[ \t]{{1,40}}{ZIP}(?![\w-])")
_INTL_TAIL = re.compile(r"^(?:,\s*[A-Z][\w.'’ -]{1,30}){1,4},?\s*\d{4,6}(?![\w-])")
_INTL_HEAD = re.compile(r"(?:Flat|Apt|Apartment|Unit|Suite|Ste|House|Plot|Door|Block)\s*(?:No\.?\s*)?[\w-]{1,6},\s*(?:[A-Z][\w'’-]*\s*){1,4},\s*$")
_CSZ_ALONE = re.compile(rf"(?<![\w])(?:{CITY}),\s+(?:{STATE_ABBR}|{STATE_NAMES})\.?\s+(?:{ZIP}|{CA_POST})(?![\w-])")
_UK_POST = re.compile(rf"(?<![A-Za-z0-9]){UK_POST}(?![A-Za-z0-9])")
_CA_POST = re.compile(rf"(?<![A-Za-z0-9]){CA_POST}(?![A-Za-z0-9])")

# Things that look like "<number> <Name> <Suffix>" but are not addresses.
_FALSE_SUFFIX_CTX = re.compile(r"(?i)\b(?:superior|district|circuit|supreme|county|municipal|appeals?|federal|"
                               r"bankruptcy|family|probate|juvenile|traffic|claims|justice|magistrate|tax|land|"
                               r"housing|drug|small|common|chancery|orphans'?)\s+(?:court|ct)\b")
_BAD_LEAD = re.compile(r"(?i)\b(?:page|pg|exhibit|ex|section|sec|§|rule|chapter|ch|article|art|volume|vol|no|"
                       r"number|item|line|paragraph|para|claim|policy|case|cpt|icd|dx|rx|room|bed|level|grade|"
                       r"step|stage|phase|figure|fig|table|appendix|count|counts|year|years|day|days|week|weeks|"
                       r"month|months|hour|hours|minute|minutes|mg|mcg|ml|units|times|x|visits?|sessions?)\.?\s*$")
_NUMBER_AS_YEAR_EVENT = re.compile(r"^(?:19|20)\d{2}\s+(?:[A-Z][a-z]+\s+)?(?:Court|Park|Center|Plaza|Mall|Way|"
                                   r"Station|Square|Bridge|Hill|Commons|Run|Trail|Point|Landing)\b")


def find_addresses(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for m in _ADDR.finditer(t):
        s, e = m.span()
        val = m.group()
        lead = t[max(0, s - 14):s]
        if _BAD_LEAD.search(lead):
            continue
        if _FALSE_SUFFIX_CTX.search(val):
            continue
        if _NUMBER_AS_YEAR_EVENT.match(val) and not re.search(rf"{ZIP}$", val):
            continue
        if re.match(r"0+\s", val) or re.search(r"(?i)\breal\s+estate$", val):
            continue  # "0   I1" (a credit-report grid), "04  Real Estate Commission" (a closing-cost line)
        if re.match(r"\d{1,4}\s+U\.\s?S\.\s+\d{1,4}$", val) and re.match(
                r"\s*(?:,\s*\d{1,4}\s*)?\((?:[A-Z][\w.]*\s*)*(?:19|20)\d{2}\)", t[e:e + 30]):
            continue  # "547 U.S. 356 (2006)" — a Supreme Court citation, not U.S. Route 356
        # trim trailing newline+city capture that swallowed a non-city line
        val_lines = val.split("\n")
        if len(val_lines) > 1 and not re.search(rf"(?:{STATE})\.?(?:,?\s+(?:{ZIP}|{CA_POST}))?\s*$", val_lines[-1]):
            e = s + len("\n".join(val_lines[:-1]))
        tail = _INTL_TAIL.match(t[e:e + 120])
        if tail:  # "12 Venkatnarayana Road, T. Nagar, Chennai 600017"
            e += tail.end()
        head = _INTL_HEAD.search(t[max(0, s - 80):s])
        if head:  # "Flat 4B, Sri Sai Residency, " before the street
            s -= len(t[max(0, s - 80):s]) - head.start()
        has_csz = bool(re.search(rf"(?:{ZIP}|{CA_POST}|\d{{6}})\s*$", t[s:e]))
        has_city = bool(re.search(rf",?\s*{CITY},?\s+{STATE}", t[s:e]))
        is_box = bool(re.match(_POBOX, val)) or bool(re.match(_RURAL, val))
        if is_box and re.match(r"Box\b", val) and not (has_csz or has_city):
            continue  # a bare "Box 12a" is a tax-form box, not a P.O. Box (those say P.O. or carry a city / ZIP)
        score = 0.95 if has_csz else (0.85 if not is_box else 0.9)
        sm = re.match(rf"{_STREET}", val)
        if sm and not (has_csz or has_city or re.search(UNIT + "$", t[s:e])):
            last = re.findall(r"[A-Za-z]+", sm.group())
            if last and last[-1].lower() in WEAK_SUFFIXES and not re.match(DIRECTIONS + "$", last[-1]):
                score = 0.45
        yield _mk(nt, s, e, score, "pattern:address", "street address")
    for m in _CSZ_ALONE.finditer(t):
        s, e = m.span()
        yield _mk(nt, s, e, 0.85, "pattern:city_state_zip", "city, state and ZIP")
    for m in _CSZ_CAPS.finditer(t):
        if m.group(1).split()[0] in ("PO", "BOX", "SUITE", "STE", "APT", "PAGE", "CASE", "MRN", "DOB", "SSN", "ZIP"):
            continue
        s, e = m.span()
        yield _mk(nt, s, e, 0.85, "pattern:city_state_zip", "city, state and ZIP")
    for m in _CA_POST.finditer(t):
        s, e = m.span()
        if re.fullmatch(r"E\dV\dM\d", m.group()) or re.search(r"(?i)\bgcs\b", t[max(0, s - 15):s]):
            continue  # "GCS 15 (E4V5M6)" — Glasgow coma scale, not a postcode
        if re.search(r"\d", m.group()) and re.search(r"[A-Z]", m.group()):
            yield _mk(nt, s, e, 0.6, "pattern:ca_postcode", "Canadian postal code")
    for m in _UK_POST.finditer(t):
        s, e = m.span()
        if " " in m.group() or re.search(r"(?i)\b(?:uk|united kingdom|england|london|scotland|wales|postcode)\b",
                                         t[max(0, s - 80):e + 20]):
            yield _mk(nt, s, e, 0.6, "pattern:uk_postcode", "UK postcode")


def _mk(nt: NormText, s: int, e: int, score: float, source: str, why: str) -> Span:
    os_, oe = nt.to_original(s, e)
    return Span(os_, oe, "ADDRESS", score, source, nt.original[os_:oe], why)


# A bare street reference ("on Bank Street") — not a full address but used by the indirect detector.
STREET_REF = (rf"(?:{DIRECTIONS}\s+)?(?:{_NAMEWORD})(?:\s+{_NAMEWORD}){{0,3}}\s+(?:{SUFFIXES}|{_UPPER_SUFFIXES})\.?(?![A-Za-z])"
              rf"(?:\s+{DIRECTIONS}(?![A-Za-z]))?")
STREET_NAME_ONLY = rf"(?:{DIRECTIONS}\s+)?(?:[A-Z][a-z]+|\d{{1,3}}(?:st|nd|rd|th))(?:\s+[A-Z][a-z]+)?(?:\s+(?:{SUFFIXES})\.?)?"
