"""Descriptive identifiers written in prose: who someone is, what they look like, where they live or hang out.

These are the details reviewers miss most often because no single word is sensitive:

* role descriptions   "the only overnight load dispatcher for the Fife yard", "a unit clerk on the night
                      shift in the Hopkins ED", "the retired teacher who leads the Saturday nature walk"
* appearance          "heavyset, about 50, gray goatee, 'Semper Fi' tattoo on the right calf",
                      "6'1\", about 230 lbs, shaved head, red beard", "long bleached-blonde hair"
* body-mark tables    "L forearm     teardrop and '520' area code, faded"
* dwellings           "the yellow split-level across from the park entrance on Shroyer",
                      "the back room of the green house behind Taquería El Tapatío on Sanborn"
* saints' names       "St. Mary's in Walsenburg", "the basement of St. Brendan's on S. Yakima Ave"

Spans end at a sentence or clause boundary, never in the middle of a word.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from .base import NormText, Span
from .quasi import RELATION_NOUNS

# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------


def _mk(nt: NormText, s: int, e: int, entity: str, score: float, source: str, why: str) -> Span:
    t = nt.text
    while s < e and t[s] in " \t\n,;:(\"'":
        s += 1
    while e > s and t[e - 1] in " \t\n,;:(\"'.":
        if t[e - 1] in "\"'" and t.count(t[e - 1], s, e - 1) % 2:
            break  # the quote closes one inside the span: 'TAT R FARM "LUPE"'
        e -= 1
    os_, oe = nt.to_original(s, e)
    return Span(os_, oe, entity, score, source, nt.original[os_:oe], why)


# a sentence end (but not "approx.", "lbs.", "St.", initials), ; ! ? ) " -- ", a blank line, or a comma that
# starts a new clause ("…, and she", "…, photographed the dog")
_CLAUSE_END = re.compile(
    r"(?:\.(?=\s|$)(?<!\b[A-Z]\.)(?<!\bSt\.)(?<!\bDr\.)(?<!\bMt\.)(?<!approx\.)(?<!lbs\.)(?<!\blb\.)(?<!\bwt\.)"
    r"(?<!\bht\.)(?<!\best\.)(?<!\bNo\.)(?<!\bft\.)(?<!\din\.)(?<!\d\sin\.)(?<!\bMr\.)(?<!\bMrs\.)(?<!\bMs\.)(?<!\bJr\.)(?<!\bSr\.)"
    r"|[;!?]|\)|\s--\s|\n[ \t]*\n|\s+(?=BUT\s)|[\x22”](?=[ \t]*\n)|\n(?=[ \t]*[A-Z][A-Za-z /()-]{1,30}:)|"
    r",\s+(?=(?:and|but|so|then|I|he|she|they|we|it)\b)|,\s+(?!(?:shaved|dyed|bleached|tattooed|scarred|pierced|"
    r"braided|bearded|freckled|faded|slicked|buzzed|cropped|receding|thinning|tinted)\b)"
    r"(?=(?:[a-z]{2,}ed\b|said|says|told|saw|was|is|has|had|went|"
    r"came|ran|left|called)\b)|\s+and\s+(?=(?:is|was|has|had|will|can|could|would|said|says|works|worked|lives|"
    r"[a-z]{2,}ed|sat|went|came|ran|got|saw|told|drove|took|made|put|stood|kept|left|then)\b)|"
    r",\s*(?=(?:at\s+)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4})|,\s+(?=(?:which|whose|who)\b)|"
    # the main verb of the sentence ("the bartender at the Rusty Anchor saw the collision") — but not inside a
    # relative clause ("the nurse who was on duty")
    r"(?<!\bwho)(?<!\bthat)(?<!\bwhich)(?<!\bwhom)(?<!\bwhere)(?<!\bwhen)\s+(?=(?:saw|said|says|told|testified|"
    r"stated|heard|noticed|observed|reported|witnessed|watched|yelled|screamed|confirmed|denied|explained|admitted|"
    r"recalled|remembered|described|identified|gave|wrote|signed|refused|asked|answered|called|claimed|"
    r"is|was|were|are|has|had|will|would|could|did|does|struck|hit|shoved|pushed|grabbed|punched|kicked|cornered|"
    r"threatened|attacked|bit|stole|took|came|went|ran|drove|fled|got|walked|pulled|knocked|threw|broke|caught|found|"
    r"brought|spoke|sent|made|kept|sat|stood|fell|began|became)\b))")


def _clause_end(t: str, pos: int, limit: int = 110) -> int:
    """End of the clause that starts at ``pos``: the next sentence end, semicolon, closing bracket, dash
    break, blank line, or a comma followed by a new clause ("and she…", "who…" are kept)."""
    end = min(len(t), pos + limit)
    at = pos
    while True:
        m = _CLAUSE_END.search(t, at, end)
        if m and m.group() == ")" and t.count("(", pos, m.start()) > t.count(")", pos, m.start()):
            at = m.end()  # "our only bilingual (Gujarati) SLP": the bracket closes an aside inside the clause
            continue
        break
    if m:
        end = m.start()
    # never stop inside a word
    while end < len(t) and end > pos and t[end - 1].isalnum() and t[end].isalnum():
        end -= 1
    return end


# ---------------------------------------------------------------------------------------------
# role descriptions
# ---------------------------------------------------------------------------------------------

OCCUPATIONS = (
    r"dispatcher|barista|bartender|baker|cook|chef|line\s+cook|prep\s+cook|dishwasher|server|waitress|waiter|"
    r"cashier|clerk|unit\s+clerk|stocker|loader|picker|packer|forklift\s+(?:driver|operator)|"
    r"bus\s+(?:driver|operator)|truck\s+driver|delivery\s+driver|courier|mail\s+carrier|custodian|janitor|"
    r"housekeeper|maid|nanny|babysitter|caregiver|aide|lunch\s+aide|teacher(?:'s\s+aide)?|substitute|tutor|coach|"
    r"assistant\s+coach|counselor|librarian|secretary|church\s+secretary|receptionist|coordinator|"
    r"front[- ]desk\s+(?:coordinator|lead|clerk|agent)|lead|shift\s+lead|supervisor|manager|assistant\s+manager|"
    r"store\s+manager|night\s+manager|produce\s+manager|foreman|forewoman|superintendent|maintenance\s+(?:man|tech)|"
    r"handyman|mechanic|technician|tech|welder|electrician|plumber|carpenter|roofer|painter|landscaper|"
    r"security\s+guard|guard|bouncer|valet|attendant|pharmacist|pharmacy\s+tech(?:nician)?|nurse|charge\s+nurse|"
    r"cna|medical\s+assistant|phlebotomist|paramedic|emt|firefighter|volunteer|usher|deacon|pastor|priest|"
    r"organist|choir\s+director|point\s+guard|quarterback|pitcher|goalie|captain|student|intern|apprentice|"
    r"owner|co-owner|operator|teller|accountant|bookkeeper|stylist|barber|nail\s+tech(?:nician)?|"
    r"safety\s+coordinator|dispatch(?:er)?|crossing\s+guard|bus\s+monitor|"
    r"driver|van\s+driver|cab\s+driver|letter\s+carrier|carrier|fireman|miner|machinist|troubleshooter|watchman|"
    r"groundskeeper|director|choir\s+director|imam|super|temp|inspector|brand\s+inspector|promotora|milker|fitter|"
    r"lineman|groomer|trainer|instructor|lifeguard|ranch\s+hand|farm\s+hand|deck\s+hand|deckhand|striker|"
    r"interpreter|translator|transporter|home\s+attendant|attendant|provider|daycare\s+provider|bus\s+aide|"
    r"hygienist|dental\s+hygienist|sitter|housemother|landlord|landlady|property\s+manager|crossing\s+guard"
)
_WEEKDAY_MOD = r"(?:mon|tues|wednes|thurs|fri|satur|sun)day(?:[-/](?:mon|tues|wednes|thurs|fri|satur|sun)day)*"
_ROLE_MODS = (rf"(?:only|sole|lone|one|retired|former|longtime|head|lead|senior|assistant|night|overnight|day|"
              rf"morning|evening|weekend|graveyard|second-shift|third-shift|first-shift|opening|closing|"
              rf"part-time|full-time|bilingual|older|younger|new|regular|usual|sophomore|junior|senior|freshman|"
              rf"varsity|volunteer|elderly|young|{_WEEKDAY_MOD}|\d{{1,2}}-year-old|[a-z]+-shift|[a-z]+[- ]time)")
# modifiers that make a job description point at one person ("the retired machinist", "the Sunday van driver")
_DISTINGUISHING_MOD = re.compile(rf"(?i)\b(?:only|sole|lone|head|lead|retired|former|longtime|elderly|older|night|"
                                 rf"overnight|weekend|graveyard|regular|usual|{_WEEKDAY_MOD}|\d{{1,2}}-year-old)\b")
# what follows a job and pins it to someone: a habit ("who coaches …"), a feature ("with the hearing aids"),
# a spot ("across the street", "two doors down", "in the trailer below the house")
_PINNING_TAIL = re.compile(
    r"(?i)^(?:who|that)\s+(?:also\s+)?(?:(?!(?:was|has|is|does)\b)[a-z]{3,}s|is\s+the|has\s+the)\b|^with\s+the\b|^there\b|"
    r"^(?:across|next\s+door|two\s+doors|three\s+doors|down\s+the\s+(?:street|road|hall)|up\s+the\s+(?:road|street)|"
    r"(?:in|from)\s+the\s+(?:\w+\s+){0,3}(?:house|trailer|apartment|unit|place|room)|below|above|behind|over\s+the)")
# "the only overnight load dispatcher for the Fife yard", "a unit clerk on the night shift in the Hopkins ED"
# filler words inside a role description are content words, never "the only way to get the nurse"
_FN = r"(?!(?:the|a|an|of|to|in|on|at|for|and|or|but|before|after|with|by|from|when|while|his|her|their|was|is|" \
      r"were|he|she|they|I|we|it|that|this|shift|shifts|way|thing|time|reason|place|option|problem)(?![\w-]))"
# "the only overnight load dispatcher for the Fife yard", "a unit clerk on the night shift in the Hopkins ED",
# "the Gilbert Drug pharmacist who drives refills out", "the Aunt Millie's bread driver for our route"
_ROLE_DESC = re.compile(
    rf"\b(?i:the|a|an)\s+(?:(?i:{_ROLE_MODS})[\s,]+){{0,3}}(?:{_FN}(?:[a-z]+(?:-[a-z]+)*|[A-Z][\w'’&]*(?:\.[A-Z][\w'’&]*)*(?:-\w+)*)\s+){{0,3}}?"
    rf"(?i:{OCCUPATIONS}|widow|widower|gentleman|lady|man|woman|couple)\b(?![-'’])"
    rf"(?P<f>\s+(?:at|for|on|in|of|with|who|that|covering|assigned\s+to|working|running|from|near|across|next\s+door|"
    rf"two\s+doors|down\s+the|up\s+the|below|above|behind|over|by)\s+|\s+there\b(?=[\s,.;])|,\s+(?=(?:the\s+)?only\b))?")
# what a "the only …" / "one of the two …" description ends on: a job, a person word, or a job acronym ("SLP", "RN")
_PERSON_HEAD = (rf"(?:(?i:{OCCUPATIONS}|interpreter|translator|transporter|lineman|linewoman|setter|installer|"
                rf"lifeguard|advocate|organizer|resident|tenant|neighbou?r|parent|mom|dad|guy|lady|woman|man|"
                rf"girl|boy|kid|person|people|employee|worker|staffer|teen|hand(?=\s+(?:at|on|for|in)\b)|"
                rf"one(?=\s+(?:who|that)|\s*[.,;)\n]|\s+--)|"
                rf"(?!(?:list|wrist|twist|fist|mist|exist|assist|insist|resist|persist|consist)\b)[a-z]+(?:ist|ian))"
                rf"|(?:RN|LPN|LVN|CNA|EMT|SLP|OT|PT|PA|NP|MA|CMA|CPA|CFO|CEO|COO|DJ|TA|RA|GM|SRO|MP))(?:e?s)?")
_UNIQUE_ROLE = re.compile(
    rf"\b(?:(?i:the|our|their|his|her|my|its|your)\s+(?i:only|sole|lone)|(?i:the\s+one\s+(?:that|who))|"
    rf"(?:(?<=,\s)|(?<=,\n))(?i:only))\s+(?:{_FN}[A-Za-z'’()/-]+\s+){{0,5}}?"
    rf"(?:(?i:works?|working|runs?|leads?|coaches|teaches|drives|cooks|certified)|{_PERSON_HEAD})\b")
# "one of the two night-shift gantry crane operators", "one of only three Somali interpreters"
_ONE_OF = re.compile(
    rf"\b(?i:one\s+of\s+(?:(?:the|our|their|only|just)\s+){{0,2}}(?:two|three|four|five|a\s+few|a\s+handful\s+of|"
    rf"few|2|3|4|5)\s+)(?:{_FN}[A-Za-z'’/-]+\s+){{0,4}}?{_PERSON_HEAD}\b")
# a job pinned to a shift: "overnight patient transporter, ED", "3rd shift NICU charge nurse"
_SHIFT_JOB = re.compile(
    rf"(?:\b(?:RN|LPN|CNA|EMT|LVN|MA|CMA|PCT)\s*,\s*)?\b(?i:overnight|graveyard|night-shift|day-shift|weekend|swing-shift|(?:1st|2nd|3rd|first|second|third)[- ]shift)"
    rf"\s+(?:{_FN}[A-Za-z/&-]+\s+){{1,3}}?(?i:{OCCUPATIONS}|transporter|lead|operator)\b(?:,\s*[A-Z0-9][A-Za-z0-9/-]{{0,8}}\b)?"
    rf"(?:\s+(?i:on|at|in|for)\s+(?:(?i:the)\s+)?[A-Z][\w'’&-]*(?:\s+[A-Za-z][\w'’&-]*){{0,3}})?")
# a relative named by their job: "his younger brother, a cab driver working out of DTW", "her granddaughter, the
# Ben Creek route bus driver for Mingo County Schools", "His landlord, the owner of Sana'a Sweets"
_REL_OWNER = (r"(?:(?i:her|his|their|my|our|your|ur|the)(?:\s+(?:late\s+|ex-|former\s+)?[a-z]+['’]s)?|(?i:pt|patient|victim|subject|debtor|member|"
              r"insured|claimant|client|customer|decedent|respondent|petitioner|plaintiff|defendant)['’]s|[A-Z][a-z]+['’]s)")
_REL_APPOS = re.compile(
    rf"\b{_REL_OWNER}\s+(?:(?i:{_ROLE_MODS}|late|maternal|paternal|live-in|common-law|estranged)[\s,]+){{0,3}}"
    rf"(?i:{RELATION_NOUNS}|landlord|landlady|compadre|comadre|neighbou?r|lead|boss|supervisor|roommate|ex|"
    rf"ex-girlfriend|ex-boyfriend|godson|goddaughter)\s*,\s+"
    rf"(?=(?i:the|a|an)\s+(?:{_FN}[\w'’&-]+\s+){{0,4}}?(?i:{OCCUPATIONS}|{_PERSON_HEAD}|inmate|resident|student|"
    rf"owner|employee|patient)\b)")
# a relative of a relative / of the owner, pinned by what they do: "the owner's nephew who works the register at
# night", "the dock boss's wife who keeps their books", "the grandson's roommate from the Publix deli counter"
_REL_TAIL = re.compile(
    rf"\b(?i:the|her|his|their|my|our)\s+(?i:[a-z-]+(?:\s+boss)?)['’]s\s+(?:(?i:{_ROLE_MODS}|late|new|maternal|paternal)\s+){{0,2}}"
    rf"(?i:{RELATION_NOUNS}|roommate|landlord|neighbou?r|tenant|son-in-law|daughter-in-law|nephew|niece)"
    rf"(?=\s+(?:who|that|in|from|at|on)\s)")
# field values: "OCCUPATION: NIGHT MILKER, BARN 3", "Position  sole front-desk & billing coordinator",
# "Relationship:  my landlord at the fourplex on Boulder"
_JOB_FIELD = re.compile(r"(?im)(?:^|[ \t]{2,})(?:occupation|position|job\s+title|assignment)[ \t]*(?::[ \t]*|[ \t]{2,})"
                        r"(\S[^\n]{2,70}?)(?=[ \t]{2,}|\n|$)")
_JOB_PIN = re.compile(r"(?i)\b(?:night|overnight|graveyard|sole|only|lead|head|weekend)\b|,\s*[A-Z]+\s+\d|"
                      r"\b(?:on|at|for)\s+(?:the\s+)?[A-Z]")
_RELATIONSHIP_FIELD = re.compile(r"(?im)\brelationship[ \t]*:[ \t]*((?:my|our|his|her|the)\b[^\n]{6,70}?|"
                                 r"[a-z][\w ]{2,30}\s+(?:at|from|of)\s+[^\n]{3,60}?)(?=[ \t]{2,}|\n|$)")
# "Mrs. Haugland's 2nd grade class"
_TEACHERS_CLASS = re.compile(
    r"\b(?:Mrs|Mr|Ms|Miss|Coach)\.?\s+[A-Z][A-Za-z'’-]+['’]s\s+(?:(?:\d(?:st|nd|rd|th)|first|second|third|fourth|fifth|"
    r"sixth|seventh|eighth|kindergarten|pre-?k)[- ](?:grade\s+)?)?(?i:class|classroom|homeroom|team|section|period)\b")
# "works nights running the grain-loading crew at …", "works the 6 a.m. shift as the only student lifeguard"
_WORKS_SHIFT = re.compile(
    r"\b(?i:works?|worked|working)\s+((?i:nights|days|overnights|weekends|evenings|mornings|graveyards|"
    r"the\s+(?:night|overnight|graveyard|day|weekend|swing|early|late|morning|evening|\d{1,2}(?::\d\d)?\s*"
    r"(?:a\.?m\.?|p\.?m\.?))\s+shift)\s+(?i:running|as|driving|cleaning|managing|covering|doing|"
    r"stocking|unloading|loading|behind|tending|watching|guarding)\b)")
# "the PT guy who helped my mom", "our door guy", "the produce lady"
_SERVICE_NOUNS = (r"door|pool|cable|mail|produce|deli|meat|lawn|tree|pest|propane|oil|insurance|maintenance|security|"
                  r"parts|tire|bike|taco|coffee|pizza|delivery|dumpster|trash|snow|plow|tow|repair|alarm|furnace|roofing|"
                  r"gutter|landscaping|cleaning|carpet|piano|dog|lunch|desk|front-desk|bread|fish|fruit|flower|church|"
                  r"choir|band|ice-cream|ice\s+cream|hot-dog|vending|parking|valet|towing|bail|bond|loan|title|check")
_SERVICE_PERSON = re.compile(
    rf"\b(?i:the|our|my|their|his|her)\s+(?:[A-Z]{{2,4}}|(?i:{_SERVICE_NOUNS}))\s+(?i:guy|lady|man|woman|girl|dude|kid)\b")
# "the decedent's live-in caregiver", "Customer's home health aide"
_PARTY_ROLE = re.compile(
    r"\b(?:(?i:the)\s+)?(?i:decedent|deceased|patient|pt|client|customer|plaintiff|defendant|claimant|victim|insured|"
    r"debtor|borrower|tenant|applicant|respondent|petitioner|employee|resident|member|guarantor|testator|ward)['’]s\s+"
    r"(?:(?i:live-in|full-time|part-time|personal|private|home\s+health|in-home|longtime|long-time|regular|only|"
    r"primary|former|overnight|night|weekend)[\s-]+){1,3}(?:[a-z-]+\s+){0,2}(?i:caregiver|aide|nurse|attendant|nanny|"
    r"housekeeper|driver|assistant|helper|companion|landlord|roommate|employer|boss|supervisor|coworker|neighbor)\b")
# appositive after a name / "I'm the …": the whole role phrase
_ROLE_AFTER = re.compile(
    rf"(?:\b(?:I'm|I\s+am|she's|he's|she\s+is|he\s+is|who\s+is|works?\s+as|worked\s+as|working\s+as|was)\s+|,\s+)"
    rf"(?=(?:the|a|an)\s+(?:[A-Za-z'’-]+\s+){{0,4}}(?i:{OCCUPATIONS})\b)")
# professionals acting in their role are covered by name / employer rules, not role descriptions
_PROFESSIONAL = re.compile(r"(?i)\b(?:physician|doctor|surgeon|attorney|lawyer|counsel|counselor|judge|officer|detective|"
                           r"deputy|trooper|adjuster|paralegal|examiner|radiologist|psychiatrist|psychologist|"
                           r"therapist|clinician|(?<!daycare\s)provider|case\s+manager|investigator|prosecutor|"
                           r"clerk\s+of\s+court)\b")


def find_roles(nt: NormText) -> Iterator[Span]:
    t = nt.text
    seen: list[tuple[int, int]] = []
    for rx in (_ROLE_DESC, _UNIQUE_ROLE, _ONE_OF):
        for m in rx.finditer(t):
            s = m.start()
            if rx is _ROLE_DESC and not m.group("f"):
                # no place / clause after the job: only a company-specific job ("the Lazy KW foreman") stands alone
                if not re.search(r"\s[A-Z][\w'’&.]*\s", m.group()[3:] + " ") or re.match(r"(?i)a\s", m.group()) or \
                        not m.group().split()[-1][:1].islower() or \
                        re.search(r"\s(?:Business|Company|Account|Primary|Self|Other|Main|Plan|Benefits|Program)\s", m.group()):
                    continue
                e = m.end()
            elif rx is _ROLE_DESC and m.group("f").strip() == "there":
                e = m.end()  # "the youth choir director there" — the place was named just before
            elif rx is _ROLE_DESC and t[m.end() - 1] != " ":
                # "the second-shift lead, only guy certified on the reach truck": the appositive goes with it
                e = _clause_end(t, m.end() + 2, 120)
            else:
                e = _clause_end(t, m.end() if rx is _ROLE_DESC else m.start(), 120)
            if e - s < 8 or rx is _ROLE_DESC and _PROFESSIONAL.search(t[s:min(e, m.end() + 5)]):
                continue
            if re.match(r"(?i)\s*(?:of|in|on)\s+(?:the\s+)?(?:unit|vehicle|veh|v|car|truck)\s*#?\s*\d", t[m.end() - 4:e]) or \
                    re.search(r"(?i)\b(?:of|in)\s+(?:unit|vehicle|veh)\s*#?\s*\d", t[s:e]) or \
                    re.search(r"(?i)\bdriver\s+of\s+(?:a|an|the|his|her|their|unit|vehicle|v\d)\b", t[s:e]):
                continue  # "the driver of Unit 2", "the restrained driver of a silver Altima" — a crash party
            if any(a <= s < b for a, b in seen):
                continue
            seen.append((s, e))
            unique = rx is not _ROLE_DESC or re.search(r"(?i)\b(?:only|sole|lone|head|lead)\b", t[s:e])
            # "a dental hygienist at Southpark Family Dental" is someone's job (the employer is redacted on its
            # own); "the night troubleshooter at the Xcel service center" is one person
            # — except staff at a school or a posting someone was sent to ("a lunch aide at Ignacio Cruz Elementary",
            # "a travel nurse on a 13-week contract at the VA")
            indefinite = rx is _ROLE_DESC and re.match(r"(?i)an?\s", m.group()) and not _DISTINGUISHING_MOD.search(t[s:e]) \
                and not re.search(r"\b(?:Elementary|Middle|High|School|Academy|VA|travel|contract|temp)\b", t[s:e])
            # weak descriptions stay review suggestions, and must not add up to a redaction with another weak rule
            score = 0.3 if indefinite else 0.7 if unique or re.search(r"\b[A-Z][a-z]", t[s + 3:e]) else \
                0.6 if _DISTINGUISHING_MOD.search(m.group()) or _PINNING_TAIL.search(t[m.end() - len(m.group("f") or ""):e].strip()) \
                else 0.3
            yield _mk(nt, s, e, "INDIRECT_ROLE", score, "descriptor:role", "a job / role description that points to one person")
    for m in _REL_APPOS.finditer(t):
        e = _clause_end(t, m.end(), 120)
        if e - m.end() > 6:
            yield _mk(nt, m.start(), e, "INDIRECT_ROLE", 0.7, "descriptor:role",
                      "a relative identified by their job or position")
    for m in _REL_TAIL.finditer(t):
        yield _mk(nt, m.start(), _clause_end(t, m.end(), 90), "INDIRECT_ROLE", 0.7, "descriptor:role",
                  "a relative of a known person, pinned by where they are or what they do")
    for m in _JOB_FIELD.finditer(t):
        v = m.group(1)
        if _JOB_PIN.search(v) and not re.match(r"(?i)(?:n/?a|none|unemployed|retired|disabled|student)\b", v):
            yield _mk(nt, *m.span(1), "INDIRECT_ROLE", 0.7, "kv:role", "a job pinned to a shift, site or position")
    for m in _RELATIONSHIP_FIELD.finditer(t):
        if len(m.group(1).split()) >= 3:
            yield _mk(nt, *m.span(1), "INDIRECT_ROLE", 0.7, "kv:role", "how a reference knows the person")
    for m in _TEACHERS_CLASS.finditer(t):
        yield _mk(nt, *m.span(), "INDIRECT_ROLE", 0.65, "descriptor:role", "a child's particular class / teacher")
    for m in _SHIFT_JOB.finditer(t):
        if _PROFESSIONAL.search(m.group()):
            continue
        yield _mk(nt, *m.span(), "INDIRECT_ROLE", 0.6, "descriptor:role", "a job on a particular shift")
    for m in _WORKS_SHIFT.finditer(t):
        e = _clause_end(t, m.end(), 120)
        yield _mk(nt, m.start(1), e, "INDIRECT_ROLE", 0.7, "descriptor:role",
                  "the shift and job someone works single them out")
    for m in _SERVICE_PERSON.finditer(t):
        e = m.end()
        if re.match(r"\s+(?:who|that|from|at|on|in|with)\b", t[e:e + 6]):
            e = _clause_end(t, e, 100)
        yield _mk(nt, m.start(), e, "INDIRECT_ROLE", 0.6, "descriptor:role", "a person known by the service they provide")
    for m in _PARTY_ROLE.finditer(t):
        yield _mk(nt, m.start(), _clause_end(t, m.end(), 80), "INDIRECT_ROLE", 0.65, "descriptor:role",
                  "a party's personal caregiver / helper identifies that person")


# ---------------------------------------------------------------------------------------------
# appearance
# ---------------------------------------------------------------------------------------------

_LOOKS = (
    r"heavyset|heavy-set|stocky|husky|chubby|overweight|obese|heavy|thin|skinny|slim|slender|lanky|petite|"
    r"muscular|athletic|built|short|tall|bald|balding|shaved\s+head|buzz\s+cut|crew\s+cut|mullet|ponytail|"
    r"top-?knot|man\s+bun|bun|braids|box\s+braids|cornrows|dreads|dreadlocks|locs|afro|curly|wavy|"
    r"(?:blond|blonde|brown|black|red|gray|grey|white|auburn|dark|light|dyed|bleached|teal|pink|blue|purple|"
    r"green|silver|salt-and-pepper|dirty-blond|sandy)[- ](?:\w+[- ])?hair(?:ed)?|redhead|beard|goatee|"
    r"mustache|moustache|stubble|sideburns|freckles|glasses|eyeglasses|nose\s+ring|lip\s+ring|eyebrow\s+ring|"
    r"septum|gauges|(?:a\s+)?ring\s+(?:in|through)\s+(?:his|her|their|the)\s+(?:nose|lip|eyebrow|ear)|grill|gold\s+(?:front\s+)?tooth|gold\s+crown|missing\s+(?:front\s+)?tooth|tattoo(?:ed|s)?|"
    r"tat|scar(?:s|red)?|birthmark|mole|piercings?|limp|light[- ]skin(?:ned)?|dark[- ]skin(?:ned)?|"
    r"fair[- ]skin(?:ned)?|complexion|red\s+face|acne|"
    r"\d\s*(?:'|ft\.?|foot|feet)\s*\d{0,2}\s*(?:\"|in\.?|inches)?|six\s+(?:foot|feet)(?:\s+\w+)?|"
    r"\d{2,3}\s*(?:lbs?|pounds)|about\s+\d{2,3}\s*(?:lbs?|pounds)|(?:about|around|maybe)\s+(?:[2-8]0|\d{2})\b|"
    r"(?:young|old|older|elderly|middle-aged)\s+(?:white|black|hispanic|latino|latina|asian|native)?\s*"
    r"(?:guy|man|woman|lady|girl|boy|dude|kid|male|female)|wearing\s+[^,;.]{3,40}|wears\s+[^,;.]{3,40}"
)
_LOOK_RX = re.compile(rf"(?i)\b(?:{_LOOKS})")
_NEXT_LOOK = re.compile(r"(?i),?\s+(?:and\s+)?(?:(?:he|she|they)\s+)?(?:also\s+)?(?:has|had|have|got)\s+")
_DISTINCTIVE = re.compile(r"(?i)tattoo|\btat\b|scar|birthmark|mole|piercing|nose\s+ring|lip\s+ring|ring\s+in\s+\w+\s+nose|gold\s+(?:front\s+)?tooth|"
                          r"missing\s+(?:front\s+)?tooth|grill|goatee|beard|mustache|moustache|braids|dreads|locs|"
                          r"cornrows|mohawk|bun|top-?knot|ponytail|bald|shaved|buzz|(?:blond|blonde|red|gray|grey|white|"
                          r"auburn|dyed|bleached|teal|pink|blue|purple|green|silver|sandy|curly)\b[^,;]{0,15}hair|redhead|"
                          r"\d\s*(?:'|ft|foot|feet)|six\s+(?:foot|feet)|\d{2,3}\s*(?:lbs?|pounds)|heavyset|stocky|"
                          r"light[- ]skin|dark[- ]skin|freckles|glasses|limp|wearing\s+(?:a|the|an)\s+[^,;]{0,30}"
                          r"(?:jersey|hoodie|scrubs|vest|jacket|hat|cap|uniform)")
_LOOK_CUE = re.compile(r"(?i)(?:\bdescrib\w*\s+(?:him|her|them|the\s+\w+)\s+as|\bdescription\s*:|\bdesc\s*:|"
                       r"\bappearance\s*:|\bgen(?:eral)?\s*:|\b(?:he|she|they)\s+(?:is|was|were|'s)\b|"
                       r"\b(?:he's|she's)\s+like|\bhe\s+had|\bshe\s+had|\b(?=an?\s+(?:young|white|black|tall|short|"
                       r"skinny|heavy|heavyset|big|little|older|elderly|light[- ]skin(?:ned)?|dark[- ]skin(?:ned)?)\b)|"
                       r"\bi'm\s+(?=wearing)|\bi've\s+got|\bwith\s+(?=(?:long|short|a|his|her)\b))")
_BODY_PARTS = (r"(?:[LR]\.?|left|right|both|upper|lower)?\s*(?:chest|neck|side\s+of\s+neck|forearm|upper\s+arm|arm|"
               r"hand|hands|knuckles|fingers?|wrist|shoulder|back|upper\s+back|lower\s+back|abdomen|stomach|"
               r"calf|thigh|leg|ankle|foot|face|cheek|cheeks|temple|forehead|eyebrow|chin|lip|ear|scalp|head|"
               r"teeth|upper\s+teeth|lower\s+teeth|tooth|hip|buttock|groin|breast|torso|ribs)")
# a "TATTOOS / SCARS / MARKS" table row: body location, a gap, the description
_MARK_ROW = re.compile(rf"(?im)^[ \t]*(?:{_BODY_PARTS})[ \t]{{2,}}(?P<d>\S[^\n]{{2,100}})$")
_MARK_SECTION = re.compile(r"(?i)scars|marks|tattoos|smt\b|identifying\s+features|distinguishing")
# clinical exam findings that are also distinguishing marks
_EXAM_MARK = re.compile(
    r"(?i)\b(?:(?:well-?healed|healed|old|faded|fresh|small|large|\d+(?:\.\d+)?\s*(?:cm|mm|in(?:ch(?:es)?)?|\"))\s+)+"
    r"(?:[a-z-]+\s+){0,2}(?:incision|scar|macule|birthmark|nevus|mole|keloid|scarification(?:\s+marks)?|tattoo|"
    r"port[- ]wine\s+stain|cafe[- ]au[- ]lait\s+(?:macule|spot))\b(?:\s+(?:over|on|at|across|of|above|below|under)\s+"
    r"(?:the\s+)?[^.;,\n]{2,40})?"
    r"|\b(?:tribal\s+scarification|cafe[- ]au[- ]lait\s+(?:macule|spot)s?|port[- ]wine\s+stain)[^.;\n]{0,60}")


def find_appearance(nt: NormText) -> Iterator[Span]:
    t = nt.text
    # comma chains of looks: "heavyset, about 50, gray goatee, 'Semper Fi' tattoo on the right calf"
    for m in _LOOK_CUE.finditer(t):
        start = m.end()
        end = _clause_end(t, start, 200)
        seg = t[start:end]
        hits = list(_LOOK_RX.finditer(seg))
        if len(hits) < 2 and not (hits and re.search(r"(?i)tattoo|scar|birthmark|hair|beard|goatee|braids", seg)):
            continue
        if not _DISTINCTIVE.search(seg):
            continue  # "thin, unshaven, wearing hospital gown" — a generic exam note, nobody could be picked out
        a, b = start + hits[0].start(), start + hits[-1].end()
        # take the rest of the last descriptor's phrase ("tattoo of a koi fish on his left arm")
        tail = re.match(r"[^,;.\n]{0,60}(?:\n[ \t]*[a-z][^,;.\n]{0,40})?", t[b:end])
        b += len(tail.group()) if tail else 0
        # and the start of the first one ("long bleached-blonde hair")
        head = re.search(r"(?i)(?:\b(?:a|an|the|his|her|long|short|big|small|little|light|dark)\s+){0,3}$", t[start:a])
        a -= len(head.group()) if head else 0
        # "…a koi fish on his left arm, and he has a scar on his chin": the next clause adds another mark
        for _ in range(2):
            nxt = _NEXT_LOOK.match(t, b) if b >= end - 1 else None
            if not nxt:
                break
            e2 = _clause_end(t, nxt.end(), 120)
            if not _DISTINCTIVE.search(t[nxt.end():e2]):
                break
            b = end = e2
        if b - a >= 6:
            yield _mk(nt, a, b, "PHYSICAL_DESCRIPTOR", 0.75, "descriptor:appearance",
                      "physical description of a person")
    for m in _MARK_ROW.finditer(t):
        # the table's heading: anywhere in the block of rows above (a long table pushes it far back)
        block = t.rfind("\n\n", 0, m.start())
        if _MARK_SECTION.search(t[max(0, min(m.start() - 400, block - 200)):m.start()]):
            yield _mk(nt, *m.span("d"), "PHYSICAL_DESCRIPTOR", 0.8, "descriptor:mark_row",
                      "tattoo / scar / mark recorded in a body-marks table")
    for m in _EXAM_MARK.finditer(t):
        yield _mk(nt, *m.span(), "PHYSICAL_DESCRIPTOR", 0.7, "descriptor:exam_mark",
                  "distinguishing mark noted on examination")


# ---------------------------------------------------------------------------------------------
# dwellings and saints
# ---------------------------------------------------------------------------------------------

_COLORS = r"yellow|green|blue|red|white|gray|grey|brown|pink|tan|beige|purple|orange|black"
# whose home it is: "her mother's condo at …", "Shay's place on N 47th", "my cousin's trailer behind …"
_KIN = (r"mother|mom|mama|father|dad|papa|sister|brother|aunt|auntie|uncle|cousin|grandmother|grandma|granny|"
        r"grandfather|grandpa|friend|best\s+friend|boyfriend|girlfriend|son|daughter|ex|ex-wife|ex-husband|neighbou?r|"
        r"in-laws?|parents|sister-in-law|brother-in-law|mother-in-law|father-in-law|godmother|niece|nephew|stepdad|stepmom")
_OWNER = rf"(?:(?i:her|his|their|my|our|the)\s+(?:(?i:{_KIN})['’]s|[A-Z][a-z]+['’]s)|[A-Z][a-z]+['’]s)"
# homes: "the yellow split-level across from the park entrance", "the third-floor walkup over the barbershop"
_DWELL_NOUNS = (r"house|home|split-level|duplex|triplex|fourplex|trailer|mobile\s+home|double-wide|single-wide|doublewide|"
                r"singlewide|bungalow|ranch|cabin|condo|apartment|townhouse|townhome|shack|camper|rv|farmhouse|cottage|"
                r"high-rise|building|crib|room|basement(?:\s+room)?|back\s+room|unit|end\s+unit|walkup|walk-up|rambler|"
                r"double|adobe|rowhouses?|farm|camp(?<=['’]s\scamp)|acreage|bunkhouse|schoolhouse|loft|studio|place(?<=['’]s\splace)")
# places someone is found at: "the hookah lounge next to the Yemeni bakery", "the in-home daycare across from the Hy-Vee"
_VENUE_NOUNS = (r"store|shop|body\s+shop|lounge|caf[eé]|laundromat|laundry|bar|tavern|daycare|food\s+court|field|gate|"
                r"dock|bakery|bodega|tortiller[ií]a|diner|bus\s+stop|bench|stand|booth|clubhouse|barn|shed|lot|kiosk|"
                r"counter|motel|ATM|pool\s+hall|taqueria|garage")
_REL_PREP = (r"under|beneath|below|above|over|behind|beside|next\s+(?:door\s+)?to|across\s+(?:the\s+(?:street|road|hall|"
             r"alley|lot)\s+)?from|by|near|past|just\s+(?:past|off|behind|up|down)|off|facing|up|"
             r"(?:north|south|east|west)\s+of|(?:\w+\s+)?(?:doors?|houses?|blocks?|miles?|lots?)\s+(?:down\s+|up\s+)?"
             r"(?:from|past)|(?:down|up)\s+the\s+(?:street|road|block|hill)\s+from|around\s+the\s+corner\s+from|"
             r"at\s+the\s+(?:end|back|edge|top|bottom)\s+of|with\s+(?:the|a)\s+[a-z -]{3,30}|"
             r"parked\s+(?:beside|behind|next\s+to|by|in)")
_DWELLING = re.compile(
    rf"(?:\b(?P<det>{_OWNER}|(?i:the|a|an|her|his|their|my|our))\s+|(?:(?<=,\s)|(?<=\(\s)|(?<=\())(?=(?i:last|first|only)\s)|"
    rf"\b(?=(?i:unit\s+[A-Z0-9]{{1,3}}\s+of)\s))"
    rf"(?:(?i:back|front|upstairs|downstairs|basement|spare)\s+(?i:room|unit|apartment)\s+of\s+(?:the|a)\s+|"
    rf"(?i:the\s+)?(?i:downstairs|upstairs|end\s+unit|(?:upper|lower|top|bottom|front|back|rear)\s+(?:unit|floor|apartment)|"
    rf"unit\s+[A-Z0-9]{{1,3}})\s+of\s+(?:the|a)\s+)?"
    rf"(?:{_FN}(?:(?i:{_COLORS}|old|little|big|small|tiny|run-down|two-story|one-story|brick|wooden|stucco|last|first|"
    rf"only|corner|end|[\w-]+-floor|24-hour|in-home)|[A-Z][\w'’-]*|[a-z][\w-]*)\s+){{0,4}}?"
    rf"(?P<noun>(?i:{_DWELL_NOUNS})|(?i:{_VENUE_NOUNS}))\b(?![-'’])"
    rf"(?P<prep>\s+(?i:{_REL_PREP}|on|at|in))\s+")
_LANDMARK = re.compile(
    r"(?i)\b(?:park|church|chapel|masjid|mosque|temple|store|shop|school|corner|entrance|zoo|tracks|creek|river|mill|"
    r"field|lake|pond|boat|awning|fence|porch|yard|garage|turnoff|road|highway|elevator|silo|tower|quarry|dump|landfill|"
    r"cemetery|bridge|overpass|underpass|laundromat|laundry|rail\s+yard|bait\s+shop|tackle\s+shop|gas\s+station|"
    r"fire\s+station|post\s+office|pool|cattle\s+guard|mailbox|grocery|bakery|barbershop|bar|tavern|diner|bodega|"
    r"playground|gate|roof|barn|vfw|legion|house|trailer)\b")


def _find_homes(t: str, nt: NormText) -> Iterator[Span]:
    for m in _DWELLING.finditer(t):
        e = _clause_end(t, m.end(), 110)
        if e - m.end() < 3:
            continue
        rest = t[m.end():e]
        prep = m.group("prep").strip().lower()
        indefinite = (m.group("det") or "").lower() in ("a", "an")
        venue = not re.fullmatch(rf"(?i:{_DWELL_NOUNS})", m.group("noun"))
        if prep == "in" and not re.search(r"(?i)\bthe\b|\d", rest):
            continue  # "my cousin's house in Santa Cruz" — a town, not a particular house
        if prep in ("on", "at", "in") and (indefinite or venue and not m.group("det")):
            continue  # "a clinic on Northside Drive" — any clinic on that road
        # the description must point somewhere: a capitalised place, a landmark, or a colour / feature; a business
        # needs a named landmark or a feature ("the café with the green awning")
        named = re.search(r"[A-Z][a-z]|\b[A-Z]{2,}\b", rest)
        if venue and not (named or prep.startswith("with") or re.match(_OWNER, m.group())) or \
                not venue and not (named or _LANDMARK.search(rest)):
            continue
        yield _mk(nt, m.start(), e, "INDIRECT_LOCATION", 0.7 if venue else 0.75, "descriptor:dwelling",
                  "description of a particular home or place")


_SAINT = re.compile(r"\b(?:(?i:the\s+basement\s+of|the\s+parish\s+hall\s+(?:of|at)|the\s+gym\s+at)\s+)?"
                    r"St\.?\s+[A-Z][a-z]+(?:\s+(?:the\s+)?[A-Z][a-z]+)?['’]s\b(?:\s+(?:Church|Parish|Catholic\s+Church|"
                    r"Episcopal|Hospital|School|Academy|Cathedral))?")
_SAINT_CTX = re.compile(r"(?i)\b(?:mass|church|parish|pray|worship|sunday|choir|confession|rosary|meeting|meetings|"
                        r"aa|na|volunteer|services?|tamales|sales|at|to|from|in)\b|c/o")
_SAINT_CAPS = re.compile(r"\bST\.?\s+[A-Z]+['’]S\s+(?:[A-Z]+\s+){0,2}(?:DINING\s+ROOM|CHURCH|PARISH|SHELTER|KITCHEN|CENTER|"
                         r"HOUSE|SCHOOL|ACADEMY)(?:,[ \t]*[A-Z]+(?:[ \t]+[A-Z]+)?(?=[ \t]*$|[ \t]{2,}))?", re.M)


def find_dwellings(nt: NormText) -> Iterator[Span]:
    t = nt.text
    yield from _find_homes(t, nt)
    for m in _SAINT.finditer(t):
        if _SAINT_CTX.search(t[max(0, m.start() - 60):m.end() + 40]):
            e = m.end()
            g = re.match(r"\s+(?:in|on|at|off)\s+(?:the\s+)?(?:[A-Z][\w.'’-]*\s*){1,4}", t[e:e + 60])
            if g:
                e += len(g.group().rstrip())
            yield _mk(nt, m.start(), e, "INDIRECT_LOCATION", 0.72, "descriptor:saint_place",
                      "a named church / parish / school someone attends")
    for m in _SAINT_CAPS.finditer(t):
        if _SAINT_CTX.search(t[max(0, m.start() - 30):m.start()]):
            yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.72, "descriptor:saint_place",
                      "a named church / mission someone uses as an address")


def find_descriptors(nt: NormText) -> Iterator[Span]:
    yield from find_roles(nt)
    yield from find_appearance(nt)
    yield from find_dwellings(nt)
