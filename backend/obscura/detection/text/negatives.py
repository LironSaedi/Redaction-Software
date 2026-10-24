"""Things that look like personal names but are public / non-personal — never redact them as people.

* cited case law ("Guevara v. Ferrer, 247 S.W.3d 662 (Tex. 2008)", "In re Sullivan", "Ex parte Gomez")
* medical-literature citations ("Jupiter JB, Fernandez DL, …")
* clinical eponyms ("Spurling's maneuver", "Tinel's sign", "Waddell signs", "Hoffmann negative")
* things named after people ("Ryan White clinic", "Ben White Blvd", "MLK Elementary")
* job titles, credentials and legal role words
"""
from __future__ import annotations

import re

_REPORTER = (r"(?:S\.\s?W\.\s?(?:2d|3d)?|F\.\s?(?:2d|3d|4th)?|F\.\s?Supp\.(?:\s?(?:2d|3d))?|U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|"
             r"So\.\s?(?:2d|3d)?|N\.\s?E\.(?:\s?2d|\s?3d)?|N\.\s?W\.(?:\s?2d)?|S\.\s?E\.(?:\s?2d)?|P\.(?:\s?2d|\s?3d)?|"
             r"A\.(?:\s?2d|\s?3d)?|Cal\.\s?(?:Rptr\.|App\.)(?:\s?\d?d)?|N\.\s?Y\.\s?S\.(?:\s?2d|\s?3d)?|Tex\.\s?(?:App\.|Crim\.)|"
             r"WL|LEXIS|B\.\s?R\.|Fed\.\s?Appx?\.)")
_CASE_CITE = re.compile(
    r"(?:\b(?:In\s+re|Ex\s+parte|In\s+the\s+Matter\s+of)\s+[A-Z][\w.'’&-]*(?:\s+[A-Z][\w.'’&-]*){0,4}"
    r"|[A-Z][\w.'’&-]*(?:\s+(?:[A-Z][\w.'’&-]*|of|the|and|&|de|la)){0,8}\s+v(?:s)?\.\s+[A-Z][\w.'’&-]*"
    r"(?:\s+(?:[A-Z][\w.'’&-]*|of|the|and|&|de|la)){0,8}(?:,\s+(?:Inc|LLC|L\.L\.C|Corp|Co|Ltd|LLP|L\.P|N\.A|P\.C)\.?)?)"
    r",?\s*(?:\d{1,4}\s+" + _REPORTER + r"\s*\d{1,5}|\(\s*(?:[A-Z][\w.]*\s*){0,4}(?:19|20)\d{2}\s*\)|\d{4}\s+(?:WL|U\.S\.\s+Dist\.\s+LEXIS))")
_LIT_CITE = re.compile(r"(?:\b[A-Z][a-zA-Z'’-]+\s+[A-Z]{1,3}(?:,\s+|\.\s+)){1,8}(?:et\s+al\.?\s+)?(?:\"|“|[A-Z][a-z]+\s+[a-z])")
EPONYMS = {w.lower() for w in """
Stensen Wharton Bartholin Skene Cowper Meckel Morgagni Hesselbach Bragard Lasegue Lasègue Kocher Oddi Vater
Spurling Tinel Phalen Hoffmann Hoffman Babinski Romberg Kemp Yeoman Lasegue Patrick Gaenslen Waddell Hawkins Neer
McMurray Lachman Apley Thomas Ober Finkelstein Adson Allen Murphy McBurney Rovsing Homan Homans Kernig Brudzinski
Glasgow Apgar Parkinson Alzheimer Hodgkin Crohn Asperger Tourette Bell Guillain Barre Barré Lyme Cushing Addison
Graves Hashimoto Raynaud Sjogren Sjögren Wernicke Korsakoff Lhermitte Hoover Gillet Valsalva Trendelenburg Mulder
Thompson Jackson Wilson Dix Hallpike Epley Weber Rinne Schober Stork FABER FADIR Bechterew Slump Kernig Durkan
Tinels Speed Yergason Jobe Roos Bakody Wright Halstead Dupuytren Bennett Colles Smith Barton Jones Boxer Monteggia
Galeazzi Salter Harris Chance Jefferson Hangman Brown-Sequard Horner Pancoast Morton Sever Osgood Schlatter Baker
Heberden Bouchard Pott Scheuermann Kienbock Kienböck Preiser Legg Perthes Calve Paget Ehlers Danlos Marfan
Duchenne Becker Charcot Marie Tooth Huntington Lou Gehrig Tay Sachs Klinefelter Turner Kawasaki Reye Stevens Johnson
""".split()}
_EPONYM_AFTER = re.compile(r"(?i)^(?:['’]s)?[\s:]*(?:\([^)]{1,15}\)\s*)?(?:\(\s*[+-]\s*\)|sign|signs|test|tests|duct|ducts|gland|glands|space|canal|node|nerve|ligament|line|point|area|fascia|cyst|maneuver|manoeuvre|disease|syndrome|"
                           r"(?<=['’]s)[\s:]*(?:at|on)\s+(?:the\s+)?(?:[LR]\b|left|right|bilat)|bilaterally|"
                           r"angle|negative|positive|reflex|criteria|scale|score|classification|fracture|palsy|"
                           r"procedure|repair|incision|position|technique|program|method|exam|\(\+\)|\(-\))")
_NAMED_AFTER = re.compile(r"^(?:[ ]|[ \t]*\n[ \t]*(?![A-Za-z]+\s+(?:address|name|and\s+apt)\b|[A-Za-z]+\s*[(:]))(?:Blvd|Boulevard|St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Pkwy|Parkway|Hwy|Highway|Fwy|Freeway|Ln|"
                          r"Lane|Expressway|Expy|Loop|Bridge|Tunnel|Park|Elementary|Middle|High|Academy|College|University|"
                          r"Hospital|Medical|Center|Centre|Clinic|Library|Memorial|Foundation|Institute|Act|Program|"
                          r"Building|Courthouse|Stadium|Arena|Airport|Station|Substation|Plaza|Square|County|Co\.|Parish|"
                          r"ISD|Unified|Clinic|CARE\s+Act|Part\s+[A-D]|eligibility|Hall|Auditorium|Field|Lake)\b", re.I)
_RYAN_WHITE = re.compile(r"(?i)\bryan\s+white\b")
# legal doctrines named after cases: "Stowers demand", "Miranda warnings", "Daubert motion", "Brady material"
LEGAL_EPONYMS = {w.lower() for w in """
Stowers Miranda Brady Giglio Daubert Frye Batson Terry Garrity Loudermill Monell Chevron Erie Kastigar Allen Faretta
Franks Mapp Bivens Heck Strickland Anders Marsden Pitchess Michael Jencks Vaughn Glomar Kelley Robinson Rowland
""".split()}
_LEGAL_EPONYM_AFTER = re.compile(r"(?i)^(?:['’]s)?\s*(?:demand|deadline|letter|limits?|warnings?|rights?|hearing|motion|"
                                 r"material|disclosure|stop|charge|doctrine|standard|claim|test|challenge|violation|"
                                 r"index|request|response|exception|issue|offer|duty|obligation|analysis|factors?)\b")
# travel phrasing in front of a "name" means a road: "onto eastbound Ben White", "drive on Ben White"
_ROAD_BEFORE = re.compile(r"(?i)(?:\b(?:north|south|east|west)bound|\bonto|\b(?:driv(?:e|es|ing)|travel(?:l?ing|l?ed)?|"
                          r"headed|heading|merg(?:e|ed|ing)|exit(?:ed|ing)?)\s+(?:on|onto|down|along|off)(?:\s+(?:north|"
                          r"south|east|west)bound)?)\s+$")

OCCUPATION_WORDS = {w.lower() for w in """
registered dental hygienist hygienist assistant technician tech welder accountant owner truck food finisher concrete
transcriptionist manager supervisor director officer clerk cashier driver nurse physician surgeon therapist counselor
paramedic emt medic dispatcher deputy trooper detective sergeant lieutenant captain chief agent adjuster examiner
analyst engineer electrician plumber carpenter mechanic laborer operator foreman teacher principal professor student
attorney lawyer paralegal secretary receptionist coordinator specialist representative consultant contractor
pharmacist chiropractor dentist hygienist aide caregiver housekeeper janitor custodian guard cook chef server
bartender waiter waitress stocker loader packer picker handler associate executive president vice ceo cfo owner
casualty senior junior lead staff certified licensed registered practical vocational clinical medical dental legal
hr human resources payroll benefits trial lawyers attorneys counsel firm
generalist partner pathologist speech language installer estimator designer surveyor mgr mgmt baggage delivery shop
fraud ops tier business data teller banker underwriter processor collector bookkeeper auditor dispatcher planner
advisor adviser rep reps servicing compliance branch ramp warehouse sales account accounts loan
""".split()}
CREDENTIALS = {w.lower() for w in """
md m.d. do d.o. rn bsn msn dnp np aprn fnp pmhnp cnm crna pa pa-c pac lpn lvn cna rma cma emt emt-p emt-b paramedic
dc d.c. dpt pt ptа ot otr otr/l slp ccc-slp lcsw lcsw-s lmsw lpc lpc-s lmft lcdc lcdc-i ladc cadc phd psyd edd
dds dmd rdh pharmd rph cpht mls mt mls(ascp) mt(ascp) ascp clcp ccm cdms crc cvs cnlcp facog facs faan faap facp
abpn chi chw cpc cpa esq esq. jd llm mba mph mha ms ma ba bs ii iii cde cpss rd ld rrt crt rcp atc cscs
lmhc lmhca lpcc lcpc lisw licsw lmhp ncc nbcc bcba bcba-d whnp whnp-bc pnp cpnp agpcnp fnp-bc anp acnp arnp cns rnfa
""".split()}
LEGAL_ROLES = {w.lower() for w in """
applicant petitioner respondent movant relator intervenor claimant plaintiff defendant appellant appellee
complainant affiant declarant deponent witness victim suspect decedent beneficiary guardian ward conservator
trustee executor executrix administrator administratrix
""".split()}


def protected_ranges(text: str) -> list[tuple[int, int, str]]:
    """Ranges in which person-name detections must be discarded."""
    out = []
    for m in _CASE_CITE.finditer(text):
        out.append((m.start(), m.end(), "case citation"))
    for m in _LIT_CITE.finditer(text):
        out.append((m.start(), m.end(), "literature citation"))
    for m in _RYAN_WHITE.finditer(text):
        out.append((m.start(), m.end(), "program name"))
    return out


def is_not_a_person(text: str, start: int, end: int) -> str | None:
    """Reason a PERSON candidate is not a person, or None."""
    v = text[start:end].strip()
    words = [w.strip(".,()") for w in v.split() if w.strip(".,()")]
    if not words:
        return "empty"
    low = [w.lower() for w in words]
    after = text[end:end + 40]
    if all(w in OCCUPATION_WORDS or w in CREDENTIALS for w in low):
        return "job title / credential"
    # "Owner/President", "Designer/Estimator", "Speech-Language Pathologist"
    if any("/" in w or "-" in w for w in low) and all(
            p in OCCUPATION_WORDS or p in CREDENTIALS for w in low for p in re.split(r"[/-]", w) if p):
        return "job title / credential"
    if all(w in LEGAL_ROLES for w in low):
        return "legal role"
    core = [w for w in low if len(w) > 1]  # "R. Tinel's" — R. is right, not an initial
    if len(core) == 1 and core[0] in EPONYMS and _EPONYM_AFTER.match(after):
        return "clinical eponym"
    if len(core) == 1 and core[0] in LEGAL_EPONYMS and _LEGAL_EPONYM_AFTER.match(after):
        return "legal doctrine"
    if _ROAD_BEFORE.search(text[max(0, start - 30):start]) and not re.match(r"\s*(?:,\s*(?:Jr|Sr|MD|M\.D|DO)\b|['’]s)", after):
        return "road name (\u201ceastbound Ben White\u201d)"
    if len(words) <= 3 and _NAMED_AFTER.match(after):
        return "named after a person (street / building / program)"
    if all(len(w) <= 3 and w.isupper() for w in words) and len(words) <= 2 and not re.fullmatch(r"(?:[A-Z]\.){2,3}", v):
        return "abbreviation"
    if low[-1] in ("co", "co.") or re.match(r"\s*(?:County|Co\.|Parish)\b", after):
        return "county"
    return None
