"""Rule-based person-name detection and document-wide name propagation.

ML NER misses names in exactly the places that matter most: ALL-CAPS headers, "LAST, FIRST" record
formats, signature blocks, deposition answers and a surname used alone 40 pages later. These rules
close those gaps. All patterns are accent-aware (Noémi, Nevárez, Łukasz).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from .base import LO, UP, NormText, Span
from .negatives import CREDENTIALS, LEGAL_ROLES, OCCUPATION_WORDS

HONORIFICS = (r"Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Professor|Rev|Reverend|Fr|Father|Sister|Pastor|Hon|Honorable|Judge|"
              r"Justice|Magistrate|Commissioner|Officer|Ofc|Patrolman|Sgt|Sergeant|Det|Detective|Lt|Lieutenant|"
              r"Capt|Captain|Cpl|Corporal|Trooper|Tpr|Deputy|Dep|Agent|Special Agent|SA|Sheriff|Marshal|Chief|"
              r"Nurse|Atty|Attorney|Counselor|Coach|Principal|Mme|Mlle|Sra|Srta|Doña|Herr|Frau")
_U, _L = f"[{UP}]", f"[{LO}]"
_TITLE = rf"{_U}{_L}+(?:['’\-]{_U}?{_L}+)*"            # Smith, O'Brien, Garcia-Lopez, Nevárez
_CAPS = rf"{_U}(?:{_U}+|['’]{_U}{{2,}})(?:['’\-]{_U}+)*"  # SMITH, O'BRIEN, D'ANDRE, GARZA-YBARRA
_MIXED = rf"(?:Mc|Mac|O['’]|D['’]|De|Di|La|Le){_U}{_L}+"  # McDonald, MacArthur, D'Andre, DeShawn
_CAP = rf"(?:{_MIXED}|{_TITLE}|{_CAPS}|{_U}['’]{_U}{_L}+)"
_PARTICLE = r"(?:de|da|del|della|di|van|von|der|den|le|la|du|bin|ibn|al|el|dos|das|st\.?)"
_NAME2 = rf"(?:(?:{_U}\.\s?){{0,2}}{_CAP}(?:[ \t]+(?:{_U}\.|{_PARTICLE}[ \t]+{_CAP}|{_CAP})){{0,3}})"
# a title without its period is followed by one space: "Principal  Interest    Fees" is a table header
_HON_NAME = re.compile(r"\b(?:" + HONORIFICS + r")(?:\.[ \t]+|[ ])((?:" + _PARTICLE + r"[ \t]+){0,2})(" + _NAME2 + ")")
_SIG = re.compile(rf"(?:/s/|/S/|\bs/)[ \t]*({_U}[{UP}{LO}.'’\-]+(?:[ \t]+{_U}[{UP}{LO}.'’\-]+){{0,4}})")
_CAPTION = re.compile(rf"(?m)^[ \t]*(?:\d{{1,2}}[ \t]+)?({_CAPS}(?:[ \t]+(?:{_U}\.|{_CAPS})){{1,4}}),?[ \t]*"
                      rf"(?:an\s+individual,?\s*|individually,?\s*)?(?:\)|,|$)")
_CAPTION_NEXT = re.compile(r"(?im)^\W*(?:\d{1,2}\s+)?(?:Plaintiffs?|Defendants?|Petitioners?|Respondents?|Appellants?|"
                           r"Appellees?|v\.|vs\.?)\b")
_LAST_FIRST = re.compile(rf"(?<![\w])({_U}[{UP}'’\-]{{1,}}),[ \t]*({_U}[{UP}'’\-]+)(?:[ \t]+({_U})\.?)?(?![\w])")
_LAST_INITIAL = re.compile(rf"(?<![\w])({_U}[{UP}'’\-]{{2,}}),[ \t]?({_U})\.?(?= {{2,}}|[ \t]*\(|[ \t]*$)", re.M)
_VS = re.compile(rf"(?<![\w])({_CAP}(?:[ \t]+{_CAP}){{0,3}})[ \t]+(?:v\.|vs\.?|versus)[ \t]+({_CAP}(?:[ \t]+{_CAP}){{0,3}})")
_I_NAME = re.compile(rf"\bI,\s+({_NAME2}),\s+(?:a\s+|the\s+)?(?:Certified|Notary|undersigned|duly|being|Registered|"
                     rf"Official|Court|Deputy|Clerk|do\s+hereby|hereby|declare|state|swear|swore|certify|attest|affirm|"
                     rf"understand|have\s+read|give|make|having)")
# "My name is Rosalind Pham", "her name's Grace", "a guy named Darek"
_MY_NAME = re.compile(rf"\b(?i:(?:my|his|her|their|your|the\s+(?:victim|caller|driver|witness|patient)['’]s)\s+(?:full\s+|first\s+|"
                      rf"last\s+)?name\s+(?:is|was|'s)|name['’]s|named|goes\s+by\s+the\s+name)\s+({_NAME2})")
_INITIALS_MINOR = re.compile(rf"(?:\b(?:minor|child|children|son|daughter|of|ppa|p\.p\.a\.|friend\s+of|behalf\s+of|"
                             rf"interest\s+of|and|or|with|share\s+a\s+child)[,\s]+|\n\s*)"
                             rf"((?:{_U}\.){{2,3}})(?=[,;\s)']|$)", re.I)
_INITIALS_CUE = re.compile(r"(?i)^[,\s]*(?:,?\s*(?:a\s+)?minor|\(minor\)|,?\s*age[sd]?\s*\d|,?\s*\(\d{1,2}\)|,?\s*(?:and|&)\s+"
                           r"(?:[A-Z]\.){2,3}|,?\s*children|['’]s\b|\s+(?:F|M)\s)")
_INITIALS_ANY = re.compile(rf"(?<![\w.])((?:{_U}\.){{3}}|(?:{_U}\.){{2}}(?=,?\s+(?:a\s+minor|age|\(\d)))(?![\w])")
_NOT_INITIALS = {"U.S.A.", "P.O.B.", "L.L.C.", "P.L.L.C.", "A.K.A.", "D.B.A.", "N.K.A.", "F.K.A.", "U.S.", "P.O.", "M.D.",
                 "D.O.", "R.N.", "D.C.", "P.A.", "N.A.", "S.A.", "L.P.", "E.R.", "I.D.", "A.M.", "P.M.", "J.D.", "B.S.", "M.S.",
                 "B.A.", "M.A.", "U.K.", "E.U.", "D.D.S.", "T.X.", "S.W.", "N.E.", "N.W.", "S.E.", "U.S.C.", "C.F.R.", "A.D.A.",
                 "E.M.S.", "R.T.", "G.A.", "Q.I.", "S.S.N."}
_ALIAS = re.compile(r"\b(?:AKA|A\.K\.A\.|aka|a\.k\.a\.|alias|nickname|known\s+as|goes\s+by|street\s+name)\s*:?\s*[\x22\u201c]"
                    r"([A-Z][A-Za-z.'’-]*(?:\s+[A-Z][A-Za-z.'’-]*){0,2})[\x22\u201d]"
                    r"|[\x22\u201c]((?:[A-Z]\.){2,3})[,]?[\x22\u201d],?\s+(?:as\s+(?:everyone|everybody|we|they|people|friends)\s+"
                    r"(?:knew|called|call|know)|(?:everyone|everybody)\s+called)"
                    r"|\(\s*[\x22\u201c]([A-Z][A-Za-z'’-]{1,20})[\x22\u201d]\s*\)")
# "grandchildren Kaden, Aniyah, Wyatt, and Lily", "Dependents: 2 (Liam, 10; Ciara, 7)"
# "Thanks,\nRay" / "Best regards,\nMaria Lopez" — the sign-off line of a letter or e-mail; "Hi Ray," / "Dear Ms. Wu,"
_SIGNOFF = re.compile(r"(?im)^[ \t]*(?:thanks|thank\s+you|many\s+thanks|regards|best|best\s+regards|kind\s+regards|warm\s+regards|"
                      r"sincerely|yours\s+truly|respectfully|cheers|take\s+care|love|xoxo)[,!.]?[ \t]*\n[ \t]*"
                      rf"((?:{_U}[{LO}]+|{_U}\.)(?:[ \t]+(?:{_U}[{LO}'’-]+|{_U}\.)){{0,2}})[ \t]*$")
_GREETING = re.compile(rf"(?im)^[ \t]*(?:hi|hello|hey|dear|good\s+morning|good\s+afternoon)[ \t]+((?:{_U}[{LO}]+)(?:[ \t]+{_U}[{LO}'’-]+)?)[ \t]*[,!:]")
_DEFINED_TERMS = {w for w in """applicant petitioner respondent plaintiff plaintiffs defendant defendants company employer
employee buyer seller landlord tenant insured insurer claimant decedent minor child children parties party agreement
property premises vehicle policy estate trust borrower lender guarantor debtor creditor contractor owner agency city
county state district hospital facility provider patient member subscriber carrier client firm""".split()}
_NAME_LIST = re.compile(r"\b(?i:grandchildren|great-grandchildren|children|kids|sons|daughters|siblings|brothers|sisters|"
                        r"dependents|stepchildren|grandsons|granddaughters|nieces|nephews|survived\s+by)\b[:,\s]*(?:\d+\s*)?\(?\s*")
_LIST_ITEM = re.compile(r"([A-Z][a-z]+(?:[-'’][A-Z]?[a-z]+)?(?:\s+[A-Z][a-z]+)?)(?:\s*\(\d{1,2}\)|,\s*(\d{1,2})\b)?")
# "Dev, Dev, stay with me." — a repeated name called out
_VOCATIVE = re.compile(r"(?<![\w'’-])([A-Z][a-z]{1,15}),\s+\1\b(?=[,.!?]|\s+(?:stay|wake|look|come|talk|answer|please|can|are|do))")
# "dropping H. off", "picking J. up" — a child referred to by initial
_INITIAL_OBJ = re.compile(r"\b(?i:dropping|dropped|drop|picking|picked|pick|took|take|taking|bring|brought|bringing)\s+([A-Z]\.)\s+"
                          r"(?i:off|up|to|from|home)\b")
_NICKNAME = re.compile(r"(?:\(\s*[\x22\u201c\u2018']([A-Z][A-Za-z'\u2019-]{1,20})[\x22\u201d\u2019']\s*\)|\b(?:aka|a\.k\.a\.|nicknamed|goes\s+by|known\s+as|"
                       r"call\s+me|calls\s+him|calls\s+her|friend|people\s+call\s+me)\s*\(?[\x22\u201c']?([A-Z][A-Za-z'\u2019-]{1,20})[\x22\u201d']?\)?)")
_SPELLED = re.compile(r"(?<![\w-])(?:[A-Z]-){2,}[A-Z](?:,\s*hyphen,\s*(?:[A-Z]-){1,}[A-Z])?(?![\w-])")
_POLICE_ROLE = re.compile(rf"\b(?:V|S|W|C|RP|P|D|O)\d{{1,2}}[ ,:]+((?:{_U}\.\s)?{_TITLE}(?:[ ](?:{_U}\.|{_TITLE})){{1,3}})")
_PAYMENT_TO = re.compile(rf"(?i:zelle|venmo|cash\s*app|paypal|apple\s*cash)\s+(?i:payment|pmt|transfer|xfer|sent|"
                         rf"request|received)?\s*(?i:to|from)\s+({_CAP}(?:[ \t]+{_CAP}){{1,3}})")
_ROLE_BEFORE_NAME = re.compile(
    r"(?:(?<=[a-z,;(] )|(?<=^)|(?<=\n)|(?<=[.!?] )|(?<=\d )|(?<=  ))"
    r"(witness|plaintiff|defendant|driver|passenger|pedestrian|officer|deputy|trooper|detective|"
    r"supervisor|manager|employer|coworker|co-worker|neighbor|neighbour|roommate|landlord|tenant|spouse|husband|wife|"
    r"son|daughter|brother|sister|mother|father|cousin|uncle|aunt|nephew|niece|grandson|granddaughter|boyfriend|"
    r"girlfriend|fianc[ée]e?|partner|friend|client|patient|claimant|decedent|victim|suspect|caller|nurse|therapist|"
    r"counselor|adjuster|paralegal|attorney|counsel|doctor|physician|surgeon|chiropractor|dentist|pharmacist|"
    r"teacher|coach|pastor|child|infant|baby|guardian|parent|stepfather|stepmother|grandmother|grandfather|minor|"
    r"insured|deponent|interpreter|reporter|videographer|notary|plaintiffs|defendants|youngest|oldest|eldest|"
    r"Witness|Plaintiff|Defendant|Driver|Officer|Supervisor|Spouse|Husband|Wife|Patient|Client|Claimant|Victim|"
    r"Daughter|Son|Mother|Father|Brother|Sister|Grandmother|Grandfather|Neighbor|Neighbour|Boyfriend|Girlfriend|"
    r"Suspect|Deputy|Trooper|Detective|Nurse|Therapist|Adjuster|Paralegal|Attorney|Teacher|Coach|Pastor|Insured|"
    r"Deponent|Interpreter|Reporter|Neighbor|Landlord|Tenant)"
    rf"(?:\s+(?:named|is|was|called))?,?[ ]((?:{_U}\.\s?)?{_TITLE}(?:[ ](?:{_U}\.|{_TITLE}|(?:de|da|del|la|los|van|von|der|"
    rf"den|bin|ibn|al|el)(?=[ ](?:{_U}|la\b|los\b|der\b)))){{0,3}})")
_NAME_COMMA_TITLE = re.compile(
    rf"(?m)^[ \t]*((?:{_U}\.[ ])?{_CAP}(?:[ ](?:{_U}\.|{_CAP})){{1,3}}),[ ]+(?:Senior\s+|Sr\.\s+|Lead\s+|Chief\s+|"
    rf"Assistant\s+|Associate\s+|Managing\s+|General\s+)?(?:Claims?\s+Adjuster|Adjuster|Claims\s+Representative|"
    rf"Claims\s+Specialist|Esq\.?|Attorney(?:\s+at\s+Law)?|Counsel|Paralegal|Legal\s+Assistant|M\.?D\.?|D\.?O\.?|"
    rf"R\.?N\.?|PA-C|DPT|PT|DC|Ph\.?D\.?|LCSW|Manager|Supervisor|Director|Officer|Specialist|Representative|"
    rf"Coordinator|Administrator|Custodian\s+of\s+Records|Records\s+Custodian|Notary\s+Public|Partner|Associate|"
    rf"President|Vice\s+President|Owner|Agent|Investigator|Examiner|Analyst|Nurse|Physician|Therapist)\b")

# Words that look like names in title/upper case but are not.
NON_NAME_WORDS = {w.lower() for w in """
amma appa abuela abuelo abuelita abuelito grandma grandpa grandmother grandfather mama papa mommy daddy mom dad
identified unidentified breathing poss possible gcs custody unconscious conscious responsive unresponsive advised advsd
transported arrived cleared stable negative positive unknown pending none confirmed suspected arrested released
financial services billing accounts relations access advocacy registration scheduling admissions
out sent received read delivered incoming outgoing unsaved missed
dadi oma opa bubbe zayde hi hello hey dear thanks regards sincerely cheers greetings
the and of for to in on at by with from a an or nor but as is are was were be been this that these those it its
patient client claimant insured plaintiff plaintiffs defendant defendants witness driver owner passenger victim
suspect officer deputy trooper detective sergeant doctor nurse physician provider attorney counsel judge court
county state city district circuit superior supreme federal united states america department police sheriff
hospital medical center clinic health care healthcare insurance company inc llc corp corporation bank group
report record records note notes page date time name address phone fax email number no total amount balance
due paid charge charges payment payments statement account summary history exam examination assessment plan
diagnosis diagnoses impression procedure procedures medication medications allergies vitals review systems
chief complaint present illness physical subjective objective signed electronically reviewed dictated
transcribed approved authorized authorization release consent form forms section part exhibit appendix
attachment schedule item items line lines unit units yes no none unknown n/a male female left right bilateral
upper lower anterior posterior lumbar cervical thoracic spine knee shoulder hip neck back head emergency
department room er ed icu or mri ct xray x-ray ray scan radiology imaging lab laboratory results result
normal abnormal negative positive pending final preliminary discharge admission admit admitted visit follow
followup follow-up return work status restrictions therapy physical occupational chiropractic orthopedic
orthopedics neurology neurologist surgery surgeon surgical pain management rehab rehabilitation re dear
sincerely regards respectfully very truly yours cc enclosure enclosures enc via certified mail facsimile
monday tuesday wednesday thursday friday saturday sunday january february march april may june july august
september october november december street avenue road drive lane boulevard court place way highway suite
apt apartment north south east west main first second third mr mrs ms dr jr sr ii iii iv md do rn np pa phd
esq dds dc pt dpt lcsw honorable re: subject regarding matter case claim policy loss incident accident crash
collision vehicle auto motor traffic notice demand letter settlement offer agreement contract complaint
motion order judgment answer interrogatories requests production admissions deposition transcript
testimony question answer q a by mr. ms. examination cross direct redirect recross objection sustained
overruled continued pages volume certified certificate reporter notary public commission expires
signature bates services program responsibility medic magistrate applicant petitioner respondent movant relator lawyers trial ex-fiancee ex-fiance ex-wife ex-husband ex-boyfriend ex-girlfriend fiancee fiance stepson stepdaughter cosigner supervisor manager witness spouse husband wife officer deputy trooper detective adjuster paralegal therapist counselor nurse doctor physician coach pastor teacher neighbor landlord tenant roommate coworker employer patient's client's zelle venmo paypal netflix spectrum amazon cashout sav chk tex fla cal ill civ prac rem evid ins proc stat ann rev crim fam gov transp penal dea npi lic license id wage wages salary rate title job injury injuries severity suspected possible minor major serious fatal incapacitating non-incapacitating
seat seats type types class code codes rating factor factors contributing narrative opinion unit investigator
investigating also present appearances videographer stenographer interpreter translator spouse husband wife
son daughter mother father brother sister parent guardian child children minor relationship self other
individually individual next friend estate deceased decedent heirs representative administrator executor
trust trustee petition original amended first second third fourth answer reply response objections
respectfully submitted honorable said parties party cause no. cause plaintiff's defendant's defendants'
texas florida california york illinois georgia arizona ohio michigan nevada colorado washington oregon
interest principal escrow borrower borrowers co-borrower coborrower co-applicant lender lenders lienholder creditor
recipient recipients payer payor payee remitter originator dba jtwros utma ugma pod ocr micr fraud recovery
official thank change shop mobile branch drone contingent
derechos consumidor cuenta dinero pago recibo fecha nombre firma monto cliente usted necesito
""".split()}

# Words in NON_NAME_WORDS that are also common surnames / given names. They are never a reason to
# reject a name found in a strong context (after "Dr.", in a "Patient:" field, a caption, a signature).
SURNAME_WORDS = {w.lower() for w in """
page pages bank banks church hill hills street court chase king price day days rain ray washington lincoln jefferson
madison franklin jackson hunter wells brooks rose grace hope faith will mark summer dawn sunny crystal royal pearl
sterling miles long black white brown green gray grey young north south east west major minor marsh park parks
lane rivers river ford case claim law judge counsel nurse cook baker fisher hunter mason carpenter singer
clay stone woods wood lake field fields bishop dean deacon pope cardinal abbott friend story love joy may june
april august tuesday guard sharp short little small rich strong armstrong english french welsh scott branch
""".split()}
HARD_STOP = NON_NAME_WORDS - SURNAME_WORDS
ALWAYS_PROPAGATE_MIN_LEN = 3
_PARTICLE_WORDS = {"de", "da", "del", "della", "di", "van", "von", "der", "den", "le", "la", "du", "bin", "ibn", "al",
                   "el", "dos", "das", "ii", "iii", "iv", "jr", "sr"}
_MINOR_NOT = re.compile(r"(?i)minor\s+(?:injur|damage|accident|collision|offen[cs]e|procedure|surgery|issue|cut|"
                        r"bruis|abrasion|pain|change|correction|edit|role|league|detail|amount|scratch|dent|"
                        r"repair|crash|fender|impact|tear|strain|sprain|fracture|laceration|contusion)")


def _clean_name(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" ,.;:")


def _mk(nt: NormText, s: int, e: int, score: float, source: str, why: str, entity: str = "PERSON") -> Span:
    os_, oe = nt.to_original(s, e)
    return Span(os_, oe, entity, score, source, nt.original[os_:oe], why)


def _trim(name: str, stop: set[str] | None = None) -> list[str]:
    stop = HARD_STOP if stop is None else stop
    parts = name.split()
    # case style must be consistent: "Rain DEA BR" → "Rain"; "SMITH, JOHN" stays
    if parts and len(parts[0]) > 1 and not parts[0].isupper():
        for i, w in enumerate(parts[1:], 1):
            core = w.strip(".,")
            if len(core) >= 2 and core.isupper() and core.lower() not in _PARTICLE_WORDS:
                parts = parts[:i]
                break
    while parts and parts[-1].lower().strip(".,") in stop:
        parts.pop()
    while parts and parts[0].lower().strip(".,") in stop and not re.fullmatch(rf"{_U}\.", parts[0]):
        parts.pop(0)
    return parts


def find_rule_names(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for m in _ROLE_BEFORE_NAME.finditer(t):
        parts = _trim(m.group(2), NON_NAME_WORDS)  # running text: the strict list
        if not parts or not m.group(2).startswith(parts[0]):
            continue
        ls = t.rfind("\n", 0, m.start()) + 1
        le = t.find("\n", m.end())
        line_words = [w for w in re.findall(rf"[{UP}{LO}][{UP}{LO}'’-]*", t[ls:le if le >= 0 else len(t)])]
        if len(line_words) >= 3 and sum(w[0].isupper() for w in line_words) / len(line_words) >= 0.75:
            continue  # a Title Case heading ("The Patient Reported Pain"), not running text
        s = m.start(2)
        e = s + len(" ".join(parts))
        yield _mk(nt, s, e, 0.82 if len(parts) >= 2 else 0.62, "rule:role_name", "name following a role word")
    for m in _MY_NAME.finditer(t):
        parts = _trim(m.group(1))
        if parts and m.group(1).startswith(parts[0]) and parts[0].lower() not in NON_NAME_WORDS:
            yield _mk(nt, m.start(1), m.start(1) + len(" ".join(parts)), 0.88, "rule:my_name", "name stated as a name")
    for m in _HON_NAME.finditer(t):
        s = m.start(2)
        parts = _trim(m.group(2))
        if not parts or not m.group(2).startswith(parts[0]):
            continue
        if m.group(1):
            s = m.start(1)  # "Dr. da Rocha", "Mr. de la Cruz"
            parts = [m.group(1).strip()] + parts
        yield _mk(nt, s, s + len(" ".join(parts)), 0.9, "rule:honorific", "name following a title/honorific")
    for m in _SIG.finditer(t):
        parts = _trim(m.group(1))
        if not parts:
            continue
        s = m.start(1)
        e = s + len(" ".join(parts))
        yield _mk(nt, s, e, 0.93, "rule:signature", "/s/ electronic signature")
        os_, oe = nt.to_original(s, e)
        yield Span(os_, oe, "SIGNATURE", 0.93, "rule:signature", nt.original[os_:oe], "/s/ electronic signature")
    for m in _CAPTION.finditer(t):
        # a caption party line is followed within two lines by "Plaintiff," / "Defendant." / "v."
        look = t[m.end():m.end() + 160]
        nxt_lines = look.split("\n")[1:3]
        if not any(_CAPTION_NEXT.match(ln) for ln in nxt_lines):
            continue
        words = m.group(1).split()
        if any(w.lower().strip(".,") in HARD_STOP for w in words):
            continue
        s, e = m.span(1)
        yield _mk(nt, s, e, 0.9, "rule:caption", "party name in case caption")
    for m in _LAST_FIRST.finditer(t):
        last, first = m.group(1), m.group(2)
        if last.lower() in HARD_STOP or first.lower() in HARD_STOP or len(last) < 2:
            continue
        ls = t.rfind("\n", 0, m.start()) + 1
        le = t.find("\n", m.end())
        prefix = t[ls:m.start()]
        rest_line = t[m.end():le if le >= 0 else len(t)]
        labelled = re.search(r"(?i)(?:name|patient|pt|client|insured|member|subscriber|re|guarantor|driver|owner|"
                             r"resident|ordering|attending|referring|picked\s+up\s+by|by|protected\s+persons?)\b[^:\n]{0,40}[:#]?\s*$",
                             prefix)
        record_line = re.search(r"(?i)\b(?:dob|mrn|mr#|sex|age|acct|ssn|#\d|\d{1,2}/\d{1,2}/\d{2,4}|--)", rest_line)
        table_cell = len(re.findall(r"\S {2,}\S", t[ls:le if le >= 0 else len(t)])) >= 3 and re.match(r" {2,}|$", rest_line) \
            and re.search(r" {2,}$|^\s*$", prefix)
        if not labelled and not (not prefix.strip() and record_line) and not re.search(r"--\s*$", prefix) \
                and not table_cell:
            continue
        if re.match(r"(?:[ \t][A-Z]{2,}){2,}", rest_line) and not re.match(r"\s+(?:&|AND)\b", rest_line):
            continue  # "IDENTIFIED, NOT IN CUSTODY" — caps narrative, not a name
        s, e = m.span()
        yield _mk(nt, s, e, 0.85, "rule:last_first", "LAST, FIRST record-format name")
    # "GALLEGOS, M" / "OKONJO, D (X-waiver)" in a table column (prescriber, provider, technician)
    for m in _LAST_INITIAL.finditer(t):
        last = m.group(1)
        if last.lower() in HARD_STOP or len(last) < 3:
            continue
        ls = t.rfind("\n", 0, m.start()) + 1
        le = t.find("\n", m.end())
        line = t[ls:le if le >= 0 else len(t)]
        if len(re.findall(r"\S {2,}\S", line)) >= 3 and re.search(r"(?: {2,}|^\s*)$", t[ls:m.start()]):
            yield _mk(nt, m.start(), m.end(), 0.8, "rule:last_first", "LAST, I name in a table column")
    for m in _VS.finditer(t):
        for g in (1, 2):
            parts = m.group(g).split()
            if any(w.lower().strip(".,") in HARD_STOP for w in parts):
                continue
            s, e = m.span(g)
            yield _mk(nt, s, e, 0.8 if len(parts) >= 2 else 0.7, "rule:case_style", "party name in case style (X v. Y)")
    for m in _NAME_COMMA_TITLE.finditer(t):
        parts = _trim(m.group(1))
        if parts and m.group(1).startswith(parts[0]):
            s = m.start(1)
            yield _mk(nt, s, s + len(" ".join(parts)), 0.88, "rule:name_title", "name followed by a job title")
    for m in _I_NAME.finditer(t):
        parts = _trim(m.group(1))
        if parts:
            s = m.start(1)
            yield _mk(nt, s, s + len(" ".join(parts)), 0.9, "rule:i_name", "declarant / certifying person")
    for m in _INITIALS_MINOR.finditer(t):
        s, e = m.span(1)
        val = t[s:e].rstrip()
        if val.upper() in _NOT_INITIALS or re.match(rf"\s+{_TITLE}", t[e:e + 20]):
            continue  # "U.S. passport", "G.A. Stowers" (initials that start a name)
        yield _mk(nt, s, s + len(val), 0.85, "rule:minor_initials", "minor identified by initials")
        os_, oe = nt.to_original(s, s + len(val))
        yield Span(os_, oe, "MINOR", 0.85, "rule:minor_initials", nt.original[os_:oe], "minor identified by initials")
    for m in _INITIALS_ANY.finditer(t):
        v = m.group(1)
        if v.upper() in _NOT_INITIALS or v.upper() in {x.replace(".", "") for x in _NOT_INITIALS}:
            continue
        cue = _INITIALS_CUE.match(t[m.end():m.end() + 20]) or re.search(r"(?i)(?:minor|child|son|daughter|children)\W{1,3}$",
                                                                         t[max(0, m.start() - 15):m.start()])
        if not cue and t.count(v) < 2:
            continue  # unexplained initials appearing once are more likely an abbreviation
        s0 = m.start(1)
        yield _mk(nt, s0, s0 + len(v), 0.8, "rule:initials", "person identified by initials")
        if cue:
            yield _mk(nt, s0, s0 + len(v), 0.8, "rule:initials", "minor identified by initials", entity="MINOR")
    for m in _NICKNAME.finditer(t):
        g = 1 if m.group(1) else 2
        v = m.group(g)
        if v.lower() in NON_NAME_WORDS or v.lower() in LEGAL_ROLES or v.lower() in OCCUPATION_WORDS or \
                v.lower() in _DEFINED_TERMS:
            continue  # ("Borrower"), ("Lender") — a defined term of the agreement
        s0 = m.start(g)
        yield _mk(nt, s0, s0 + len(v), 0.82, "rule:nickname", "nickname / alias of a person")
    for rx in (_SIGNOFF, _GREETING):
        for m in rx.finditer(t):
            if m.group(1).split()[0].lower() not in ("team", "all", "everyone", "there", "folks", "sir", "madam", "counsel"):
                yield _mk(nt, *m.span(1), 0.85, "rule:signoff", "name in a greeting / sign-off")
    for m in _ALIAS.finditer(t):
        g = next(i for i in (1, 2, 3) if m.group(i))
        v = m.group(g)
        if v.lower() in ("none", "unknown", "n/a", "same") or v.lower() in _DEFINED_TERMS or v.lower() in LEGAL_ROLES:
            continue  # GRACE HILL ("Applicant") — a defined term, not an alias
        yield _mk(nt, m.start(g), m.end(g), 0.88, "rule:nickname", "alias / nickname of a person")
    for m in _NAME_LIST.finditer(t):
        pos, n = m.end(), 0
        while n < 12:
            im = _LIST_ITEM.match(t, pos)
            if not im or im.group(1).lower() in NON_NAME_WORDS or (len(im.group(1)) <= 3 and t[im.end(1):im.end(1) + 1] == "."):
                break  # "dependents (Sch. 8812)" is a form reference
            sp = _mk(nt, im.start(1), im.end(1), 0.82, "rule:name_list", "name in a list of children / relatives")
            yield sp
            n += 1
            sep = re.match(r"\s*[,;]\s*(?:and\s+)?|\s+and\s+|\s*,?\s*\n\s*", t[im.end():im.end() + 12])
            if not sep:
                break
            pos = im.end() + sep.end()
    for m in _VOCATIVE.finditer(t):
        if m.group(1).lower() not in NON_NAME_WORDS:
            yield _mk(nt, m.start(1), m.end(1), 0.75, "rule:vocative", "name called out")
            yield _mk(nt, m.end() - len(m.group(1)), m.end(), 0.75, "rule:vocative", "name called out")
    for m in _INITIAL_OBJ.finditer(t):
        yield _mk(nt, m.start(1), m.end(1), 0.7, "rule:initials", "a person (often a child) referred to by initial")
    for m in _SPELLED.finditer(t):
        letters = re.sub(r"[^A-Z]", "", m.group().split(",")[0])
        before = t[max(0, m.start() - 80):m.start()]
        # spelled after a cue, or spelling a word said just before ("Rosalind Pham. P-H-A-M.")
        if re.search(r"(?i)spell|name|first|last|middle|surname", before) or \
                re.search(r"(?i)\b" + letters + r"\b", before[-40:]):
            yield _mk(nt, m.start(), m.end(), 0.85, "rule:spelled_name", "name spelled out letter by letter")
    for m in _POLICE_ROLE.finditer(t):
        parts = _trim(m.group(1))
        if parts and m.group(1).startswith(parts[0]):
            s0 = m.start(1)
            yield _mk(nt, s0, s0 + len(" ".join(parts)), 0.85, "rule:police_role", "person tagged V1 / S1 / W1 in a report")
    for m in _PAYMENT_TO.finditer(t):
        parts = _trim(m.group(1))
        if parts and re.match(r"\d", t[m.start(1) + len(" ".join(parts)):][:1] or " "):
            parts = parts[:-1]  # "… Nevárez Jpm9670767874": the last token is a bank reference
        if parts:
            s = m.start(1)
            yield _mk(nt, s, s + len(" ".join(parts)), 0.88, "rule:payment_party", "person paid / paying via P2P app")
    yield from _context_names(nt)


# Names given in context rather than with a title. All cue words tolerate OCR's rn/m and 0/o, 1/l confusions.
_OCR_NAME = r"na(?:m|rn)e"
# "his last name … something like Kowal-chick", "sounds like Nguyen"
_NAME_GUESS = re.compile(rf"(?i:(?:last|sur|full|real|first)[ \t]*{_OCR_NAME}|{_OCR_NAME})\b[^.]{{0,60}}?"
                         r"\b(?i:something\s+like|so(?:m|rn)ething\s+like|sounds\s+like|spelled)\s+"
                         r"([A-Z][a-z]+(?:[-'’][A-Za-z]+)?)")
# "his real name is Mackenzie something Halvorson"
_NAME_FILLER = re.compile(rf"(?i:{_OCR_NAME})\s+(?i:is|was)\s+[A-Z][a-z]+\s+(?i:something|so(?:m|rn)ething|somethin'?)"
                          r"\s+([A-Z][A-Za-z'’-]+)")
# "a customer, Omar (I don't know last name", OCR "0rnar (I d0nt kn0w 1ast narne"
_NAME_NO_LAST = re.compile(r"(?<![\w'’])([A-Za-z0][a-z0-9]{2,15})\s*\(\s*(?:I\s+)?(?i:d[o0]n'?t|d[o0]\s+n[o0]t|didn'?t)"
                           rf"\s+(?i:kn[o0]w)\s+(?:(?i:his|her|their|the)\s+)?(?i:[l1]ast|full|sur)[ \t]*(?i:{_OCR_NAME})")
# "___Rosa A. Tzul X.___________" on a signature line
_SIG_UNDERSCORE = re.compile(r"_{2,}[ \t]*([A-Z][a-z]+(?:[ \t]+(?:[A-Z]\.|[A-Z][a-z]+(?:-[A-Z][a-z]+)?)){1,4})[ \t]*_{2,}")


def _context_names(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for rx, score, src, why in ((_NAME_GUESS, 0.85, "rule:name_guess", "a name the writer was unsure how to spell"),
                                (_NAME_FILLER, 0.85, "rule:name_filler", "a surname after \"name is … something\""),
                                (_NAME_NO_LAST, 0.82, "rule:name_no_last", "a first name given without a last name")):
        for m in rx.finditer(t):
            word = m.group(1)
            if word.lower().strip("'’") in NON_NAME_WORDS or word.lower() in _GUESS_STOP:
                continue
            if word[0].islower() and not re.search(r"[0-9]", nt.original[m.start(1):m.end(1)]) and \
                    nt.original[m.start(1):m.end(1)] == word:
                continue  # lower case is only accepted where OCR mangled a capital ("0rnar" → "ornar")
            yield _mk(nt, m.start(1), m.end(1), score, src, why)
    for m in _SIG_UNDERSCORE.finditer(t):
        parts = m.group(1).split()
        if any(p.lower() in NON_NAME_WORDS for p in parts if len(p) > 2):
            continue
        yield _mk(nt, m.start(1), m.end(1), 0.9, "rule:signature_line", "name written on a signature line")


_GUESS_STOP = {"guy", "man", "woman", "lady", "girl", "boy", "dude", "kid", "customer", "neighbor", "driver", "friend",
               "coworker", "someone", "somebody", "person", "he", "she", "polish", "spanish", "mexican", "italian", "irish", "german", "russian", "french", "greek", "arabic",
               "chinese", "korean", "vietnamese", "indian", "that", "this", "the", "it", "him", "her", "them"}


_NAME_LINE = re.compile(rf"^[ \t]*((?:{_U}\.?[ \t]+)?{_CAP}(?:[ \t]+(?:{_U}\.?|{_CAP})){{1,3}})[ \t]*$")


def names_above_addresses(text: str, address_spans: list[Span]) -> Iterator[Span]:
    """Mailing blocks: a line holding only a name directly above a street-address line."""
    for a in address_spans:
        ls = text.rfind("\n", 0, a.start)
        if ls <= 0 or text[ls + 1:a.start].strip():
            continue
        pls = text.rfind("\n", 0, ls) + 1
        line = text[pls:ls]
        m = _NAME_LINE.match(line)
        if not m:
            continue
        # two mailing blocks side by side ("THADDEUS K OYELARAN        Co-Borrower"): judge each column alone
        pos = pls + m.start(1)
        for piece in re.split(r"([ \t]{3,}|\t)", m.group(1)):
            a, pos = pos, pos + len(piece)
            parts = piece.split()
            if not parts or re.fullmatch(r"[ \t]+", piece):
                continue
            if any(w.lower().strip(".,") in HARD_STOP for w in parts):
                continue
            if piece != m.group(1) and (len(parts) < 2 or not _NAME_LINE.match(piece)):
                continue
            yield Span(a, a + len(piece), "PERSON", 0.85, "rule:name_above_address", piece,
                       "name line of a mailing address block")


# ---------------------------------------------------------------------------------------------
# Propagation: once a name is known, find every other mention of it.
# ---------------------------------------------------------------------------------------------

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "md", "m.d", "do", "rn", "np", "pa", "phd", "esq", "dds", "dc"}


def _name_variants(name: str) -> tuple[set[str], set[str]]:
    """Return (full-name variants, single-token variants) for a detected name."""
    name = _clean_name(name)
    if "," in name:  # "DOE, JANE A" -> "JANE A DOE"
        last, _, rest = name.partition(",")
        name = f"{rest.strip()} {last.strip()}"
    toks = [w for w in re.split(r"\s+", name) if w]
    toks = [w for w in toks if w.lower().strip(".") not in _SUFFIXES and w.lower().strip(".,") not in CREDENTIALS]
    core = [w for w in toks if len(w.strip(".")) > 1]
    full: set[str] = set()
    single: set[str] = set()
    if not core:
        return full, single
    if len(core) >= 2:
        full.add(" ".join(core))
        full.add(f"{core[0]} {core[-1]}")
        full.add(f"{core[-1]}, {core[0]}")
        full.add(f"{core[0][0]}. {core[-1]}")
        if len(toks) > len(core):  # include middle initial form, with and without its period ("NORA L ROSS")
            full.add(" ".join(toks))
            full.add(" ".join(w.rstrip(".") for w in toks))
    for i, w in enumerate(core):
        w = w.strip(".")
        is_surname = len(core) >= 2 and i == len(core) - 1
        if w.lower() in HARD_STOP:
            continue
        if len(w) >= ALWAYS_PROPAGATE_MIN_LEN or (is_surname and len(w) == 2 and w[0].isupper()):
            single.add(w)
    return full, single


def propagate_names(nt: NormText, names: Iterable[Span], common_words: set[str] | None = None) -> Iterator[Span]:
    """Yield a span for every other occurrence (any casing style, possessive) of known names."""
    full: set[str] = set()
    single: set[str] = set()
    for sp in names:
        f, s1 = _name_variants(sp.text)
        full |= f
        single |= s1
    common = common_words or set()
    single = {s for s in single if s.lower() not in common}
    t = nt.text
    lower_words = set(re.findall(rf"(?<![{UP}{LO}])[{LO}]+(?![{UP}{LO}])", t))
    for variant in sorted(full, key=len, reverse=True):
        rx = re.compile(r"(?<![\w])" + r"\s+".join(re.escape(p) for p in variant.split()) + r"(?:['’]s)?(?![\w])",
                        re.IGNORECASE)
        for m in rx.finditer(t):
            if not _case_ok(m.group()):
                continue
            s, e = m.span()
            if m.group().lower().endswith(("'s", "’s")):
                e -= 2
            yield _mk(nt, s, e, 0.88, "propagate:full", "another mention of a name detected elsewhere in the document")
    for tok in sorted(single, key=len, reverse=True):
        rx = re.compile(r"(?<![\w'’-])" + re.escape(tok) + r"(?:['’]s)?(?![\w'’-])",
                        0 if len(tok) <= 2 else re.IGNORECASE)
        ambiguous = tok.lower() in NON_NAME_WORDS  # "Page", "Bank", "Washington"…
        for m in rx.finditer(t):
            word = m.group()
            if not _case_ok(word):
                continue
            if ambiguous:
                before = t[max(0, m.start() - 12):m.start()]
                after = t[m.end():m.end() + 3]
                if not (re.search(r"(?:" + HONORIFICS + r")\.?\s+$", before) or word.endswith(("'s", "’s")) or
                        after.startswith(",") and re.match(r",\s*[A-Z]", t[m.end():m.end() + 4])):
                    continue  # "Page 12", "the Bank" — only "Mr. Page", "Page's", "PAGE, JOHN" propagate
            s, e = m.span()
            if word.lower().endswith(("'s", "’s")):
                e -= 2
            if re.match(r"\s*(?:&|and)\s+[A-Z]|,?\s+(?:LLP|LLC|L\.L\.C|Inc|P\.?C\.?|PLLC|P\.?A\.?|Group|Associates|Law|"
                        r"Partners|Corp|Company|Co\.|Foundation|Hospital|Clinic|Center|Motors|Insurance)\b", t[e:e + 16]):
                continue  # surname inside a firm / company name ("Brown & Kessler LLP")
            # "Robert Johnson" when only "Johnson" was known: pull in an adjacent capitalised given name,
            # but only a word never used in lower case elsewhere (so "Spouse Qushi" stays "Qushi")
            lm = re.search(rf"(?<![\w'’-])({_TITLE}|{_U}\.)[ \t]+$", t[max(0, s - 24):s])
            if lm:
                w = lm.group(1).strip(".")
                if (w.lower() not in NON_NAME_WORDS and w.lower() not in lower_words and
                        not re.match(r"(?:" + HONORIFICS + r")\.?$", lm.group(1))):
                    s = s - (len(t[max(0, s - 24):s]) - lm.start(1))
            yield _mk(nt, s, e, 0.8, "propagate:token", "first-name / surname mention of a name detected elsewhere")


def _case_ok(s: str) -> bool:
    """Names are capitalised: accept Title Case and ALL CAPS, reject lower-case common words."""
    words = [w for w in re.split(r"[\s,]+", s) if w and w[0].isalpha()]
    return all(w[0].isupper() for w in words)


# ---------------------------------------------------------------------------------------------
# Minors
# ---------------------------------------------------------------------------------------------

_MINOR_BEFORE = re.compile(r"(?i)(?:\bminor(?:\s+child)?|\bchild|\bjuvenile|\binfant|\btoddler|\bbaby|\bnewborn|\bkid|"
                           r"\bson|\bdaughter|\bstepson|\bstepdaughter|\bgrandson|\bgranddaughter|\bniece|\bnephew|"
                           r"\bstudent|\bpupil|\b(?:[1-9]|1[0-7])[- ](?:year|yr)s?[- ]old(?:\s+(?:child|son|daughter|"
                           r"boy|girl))?|\bnext\s+friend\s+of|\bon\s+behalf\s+of\s+(?:his|her|their)\s+minor\s+"
                           r"(?:son|daughter|child))[\s,:]*$")
_MINOR_AFTER = re.compile(r"(?i)^[\s,(]*(?:a\s+minor|\(?minor\)?|age[sd]?\s*:?\s*(?:[1-9]|1[0-7])\b|"
                          r"\((?:[1-9]|1[0-7])\)|,\s*(?:[1-9]|1[0-7])\s*,|(?:[1-9]|1[0-7])[- ](?:year|yr)s?[- ]old|"
                          r"is\s+(?:[1-9]|1[0-7])\b(?!\s*(?:%|years?\s+(?:ago|later)|hours?|minutes?)))")


def flag_minors(text: str, persons: list[Span]) -> Iterator[Span]:
    """Persons described as minors get a MINOR span (FRCP 5.2: a minor may be named only by initials)."""
    for sp in persons:
        before = text[max(0, sp.start - 45):sp.start]
        after = text[sp.end:sp.end + 30]
        mb = _MINOR_BEFORE.search(before)
        if mb and _MINOR_NOT.search(text[max(0, sp.start - 45):sp.end]):
            mb = None
        if mb or _MINOR_AFTER.search(after):
            if re.search(r"(?i)(?:parent|guardian|mother|father)\s+(?:of\s+)?(?:minor\s+)?$", before):
                continue
            yield Span(sp.start, sp.end, "MINOR", min(0.95, sp.score), "rule:minor", sp.text,
                       "person described as a minor/child")
