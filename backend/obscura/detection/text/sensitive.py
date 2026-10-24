"""Sensitive *content* (not identifiers) in medical and legal documents.

Lexicon + pattern detectors for diagnoses, medications, procedures, lab results, mental health,
substance use (42 CFR Part 2), sexual/reproductive health, genetics, disability, injuries,
privileged communications, money, financial status, criminal history, immigration status and
GDPR special categories. The ML layer (GLiNER) adds zero-shot coverage for terms not listed here.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from .base import NormText, Span


def _terms(block: str) -> list[str]:
    return [t.strip() for t in block.replace("\n", "|").split("|") if t.strip()]


MEDICATIONS = _terms("""
acetaminophen|tylenol|ibuprofen|advil|motrin|naproxen|aleve|naprosyn|aspirin|celecoxib|celebrex|meloxicam|mobic|
diclofenac|voltaren|ketorolac|toradol|indomethacin|etodolac|nabumetone|oxycodone|oxycontin|percocet|roxicodone|
hydrocodone|norco|vicodin|lortab|hydromorphone|dilaudid|morphine|ms contin|fentanyl|duragesic|tramadol|ultram|
tapentadol|nucynta|codeine|tylenol #3|methadone|buprenorphine|suboxone|subutex|naloxone|narcan|naltrexone|
vivitrol|gabapentin|neurontin|pregabalin|lyrica|cyclobenzaprine|flexeril|methocarbamol|robaxin|tizanidine|
zanaflex|baclofen|carisoprodol|soma|metaxalone|skelaxin|orphenadrine|prednisone|methylprednisolone|medrol|
dexamethasone|decadron|triamcinolone|kenalog|lidocaine|lidoderm|bupivacaine|marcaine|depo-medrol|
amitriptyline|elavil|nortriptyline|duloxetine|cymbalta|venlafaxine|effexor|desvenlafaxine|pristiq|sertraline|
zoloft|fluoxetine|prozac|paroxetine|paxil|citalopram|celexa|escitalopram|lexapro|bupropion|wellbutrin|
mirtazapine|remeron|trazodone|desyrel|vortioxetine|trintellix|vilazodone|alprazolam|xanax|lorazepam|ativan|
clonazepam|klonopin|diazepam|valium|temazepam|restoril|buspirone|buspar|hydroxyzine|vistaril|atarax|zolpidem|
ambien|eszopiclone|lunesta|quetiapine|seroquel|olanzapine|zyprexa|risperidone|risperdal|aripiprazole|abilify|
ziprasidone|geodon|lurasidone|latuda|haloperidol|haldol|clozapine|clozaril|lithium|lamotrigine|lamictal|
valproate|depakote|divalproex|carbamazepine|tegretol|oxcarbazepine|trileptal|topiramate|topamax|levetiracetam|
keppra|phenytoin|dilantin|methylphenidate|ritalin|concerta|amphetamine|adderall|vyvanse|lisdexamfetamine|
atomoxetine|strattera|guanfacine|clonidine|sumatriptan|imitrex|rizatriptan|maxalt|ondansetron|zofran|
promethazine|phenergan|metoclopramide|reglan|omeprazole|prilosec|pantoprazole|protonix|esomeprazole|nexium|
famotidine|pepcid|lisinopril|losartan|amlodipine|norvasc|metoprolol|lopressor|toprol|carvedilol|atenolol|
hydrochlorothiazide|hctz|furosemide|lasix|spironolactone|warfarin|coumadin|apixaban|eliquis|rivaroxaban|
xarelto|dabigatran|pradaxa|clopidogrel|plavix|enoxaparin|lovenox|heparin|atorvastatin|lipitor|simvastatin|
zocor|rosuvastatin|crestor|pravastatin|metformin|glucophage|insulin|lantus|humalog|novolog|levemir|glipizide|
glyburide|sitagliptin|januvia|empagliflozin|jardiance|dapagliflozin|farxiga|semaglutide|ozempic|wegovy|
liraglutide|victoza|tirzepatide|mounjaro|levothyroxine|synthroid|albuterol|proair|ventolin|fluticasone|
flonase|advair|symbicort|montelukast|singulair|cetirizine|zyrtec|loratadine|claritin|diphenhydramine|benadryl|
amoxicillin|augmentin|azithromycin|zithromax|cephalexin|keflex|ciprofloxacin|cipro|levofloxacin|levaquin|
doxycycline|clindamycin|sulfamethoxazole|bactrim|metronidazole|flagyl|nitrofurantoin|macrobid|vancomycin|
penicillin|valacyclovir|valtrex|acyclovir|oseltamivir|tamiflu|truvada|descovy|biktarvy|genvoya|triumeq|
dovato|emtricitabine|tenofovir|efavirenz|dolutegravir|raltegravir|isentress|prep|sildenafil|viagra|tadalafil|
cialis|finasteride|estradiol|progesterone|medroxyprogesterone|depo-provera|norethindrone|levonorgestrel|
plan b|mifepristone|misoprostol|clomiphene|clomid|letrozole|testosterone|methotrexate|humira|adalimumab|
enbrel|etanercept|remicade|infliximab|hydroxychloroquine|plaquenil|tamoxifen|anastrozole|chemotherapy|
cannabidiol|cbd|medical marijuana|dronabinol|marinol|disulfiram|antabuse|acamprosate|campral|chantix|
varenicline|nicotine patch
""")

CONDITIONS = _terms("""
diabetes|type 2 diabetes|type 1 diabetes|hypertension|high blood pressure|hyperlipidemia|coronary artery disease|
congestive heart failure|heart failure|atrial fibrillation|myocardial infarction|heart attack|stroke|cva|tia|
copd|asthma|emphysema|sleep apnea|obesity|morbid obesity|hypothyroidism|hyperthyroidism|chronic kidney disease|
ckd|renal failure|dialysis|cirrhosis|hepatitis|hepatitis b|hepatitis c|fatty liver|pancreatitis|crohn's disease|
ulcerative colitis|ibs|irritable bowel|gerd|cancer|carcinoma|lymphoma|leukemia|melanoma|tumor|malignancy|
metastatic|breast cancer|prostate cancer|lung cancer|colon cancer|multiple sclerosis|parkinson's|alzheimer's|
dementia|epilepsy|seizure disorder|seizures|migraine|migraines|fibromyalgia|lupus|rheumatoid arthritis|
osteoarthritis|arthritis|osteoporosis|gout|anemia|sickle cell|hemophilia|chronic pain|chronic pain syndrome|
complex regional pain syndrome|crps|neuropathy|peripheral neuropathy|radiculopathy|sciatica|myelopathy|
spinal stenosis|degenerative disc disease|ddd|spondylosis|spondylolisthesis|scoliosis|herniated disc|
disc herniation|disc bulge|bulging disc|disc protrusion|annular tear|facet arthropathy|cervicalgia|lumbago|
low back pain|neck pain|whiplash|cervical strain|lumbar strain|thoracic strain|sprain|strain|
post-concussion syndrome|post-concussive syndrome|concussion|traumatic brain injury|tbi|mild traumatic brain injury|
mtbi|cognitive impairment|tinnitus|vertigo|chronic fatigue|covid-19|covid|long covid|tuberculosis|
pneumonia|sepsis|mrsa|c. diff|influenza|allergy|anaphylaxis|endometriosis|pcos|infertility|incontinence|
erectile dysfunction|glaucoma|macular degeneration|cataract|blindness|deafness|hearing loss|autism|
asd|adhd|add|down syndrome|cerebral palsy|spina bifida|muscular dystrophy|als|huntington's disease|
cystic fibrosis
""")

INJURIES = _terms("""
fracture|fractures|fractured|broken bone|comminuted fracture|compound fracture|hairline fracture|
compression fracture|dislocation|dislocated|torn acl|acl tear|meniscus tear|torn meniscus|rotator cuff tear|
labral tear|slap tear|tendon rupture|ligament tear|contusion|contusions|laceration|lacerations|abrasion|
abrasions|hematoma|subdural hematoma|epidural hematoma|brain bleed|intracranial hemorrhage|skull fracture|
spinal cord injury|paralysis|paraplegia|quadriplegia|tetraplegia|amputation|degloving|burns|third-degree burns|
second-degree burns|crush injury|internal bleeding|ruptured spleen|punctured lung|pneumothorax|rib fractures|
broken ribs|pelvic fracture|hip fracture|femur fracture|tibia fracture|fibula fracture|wrist fracture|
clavicle fracture|orbital fracture|facial fractures|dental injury|broken teeth|road rash|seatbelt sign|
airbag burns|bruising|swelling|soft tissue injury|soft-tissue injuries|disfigurement|scarring
""")

PROCEDURES = _terms("""
surgery|laminectomy|discectomy|microdiscectomy|spinal fusion|acdf|anterior cervical discectomy and fusion|
lumbar fusion|cervical fusion|kyphoplasty|vertebroplasty|epidural steroid injection|esi|facet injection|
medial branch block|radiofrequency ablation|rfa|trigger point injection|nerve block|spinal cord stimulator|
arthroscopy|arthroscopic|acl reconstruction|knee replacement|hip replacement|total knee arthroplasty|
total hip arthroplasty|rotator cuff repair|orif|open reduction internal fixation|craniotomy|appendectomy|
cholecystectomy|hysterectomy|mastectomy|lumpectomy|c-section|cesarean|colonoscopy|endoscopy|biopsy|
mri|ct scan|cat scan|x-ray|xray|ultrasound|emg|nerve conduction study|ncs|eeg|ekg|ecg|echocardiogram|
stress test|cardiac catheterization|angioplasty|stent|bypass|cabg|pacemaker|dialysis|chemotherapy|
radiation therapy|physical therapy|occupational therapy|chiropractic|chiropractic adjustment|
massage therapy|acupuncture|cognitive therapy|cbt|psychotherapy|ect|electroconvulsive therapy|
intubation|ventilator|tracheostomy|blood transfusion|skin graft|plastic surgery|reconstructive surgery
""")

MENTAL_HEALTH = _terms("""
depression|major depressive disorder|mdd|depressive|anxiety|generalized anxiety disorder|gad|panic disorder|
panic attacks|ptsd|post-traumatic stress disorder|posttraumatic stress|acute stress disorder|ocd|
obsessive-compulsive disorder|bipolar|bipolar disorder|manic|mania|schizophrenia|schizoaffective|psychosis|
psychotic|delusions|hallucinations|paranoia|borderline personality disorder|bpd|personality disorder|
antisocial personality|narcissistic personality|eating disorder|anorexia|bulimia|binge eating|self-harm|
self harm|cutting|suicidal|suicidal ideation|si|suicide attempt|attempted suicide|overdose|suicide|
homicidal ideation|psychiatric|psychiatrist|psychologist|therapist|counseling|counselling|mental health|
mental illness|behavioral health|baker act|involuntary commitment|5150|psychiatric hold|inpatient psychiatric|
psych ward|adjustment disorder|dissociative|insomnia|emotional distress|grief counseling|trauma therapy|
emdr|psychotherapy notes|mood disorder|dysthymia|seasonal affective disorder
""")

SUBSTANCE = _terms("""
substance use disorder|sud|substance abuse|drug abuse|alcohol abuse|alcohol use disorder|alcoholism|alcoholic|
alcohol dependence|opioid use disorder|oud|opioid dependence|opioid addiction|addiction|addicted|drug addiction|
heroin|fentanyl use|cocaine|crack cocaine|methamphetamine|meth|crystal meth|amphetamine use|marijuana use|
cannabis use disorder|benzodiazepine dependence|ivdu|iv drug use|intravenous drug use|polysubstance|
detox|detoxification|withdrawal|rehab|drug rehab|rehabilitation center|treatment center|aa meetings|
alcoholics anonymous|narcotics anonymous|na meetings|sober living|sobriety|relapse|relapsed|recovery program|
methadone clinic|methadone maintenance|medication-assisted treatment|mat|suboxone clinic|buprenorphine treatment|
drug court|positive drug screen|positive for thc|positive for cocaine|uds positive|urine drug screen|
bac|blood alcohol|dui|dwi|intoxicated|under the influence
""")

SEXUAL_REPRO = _terms("""
hiv|hiv positive|hiv-positive|aids|hiv/aids|viral load|cd4 count|std|sti|sexually transmitted|
chlamydia|gonorrhea|syphilis|herpes|hsv-2|hpv|genital warts|trichomoniasis|pregnant|pregnancy|
pregnancy test|positive pregnancy|gestation|weeks pregnant|miscarriage|stillbirth|abortion|terminated pregnancy|
termination of pregnancy|elective abortion|ivf|in vitro fertilization|fertility treatment|infertility|
contraception|birth control|iud|tubal ligation|vasectomy|erectile dysfunction|sexual dysfunction|
sexual assault|rape|sexual abuse|molestation|sane exam|rape kit|sexual assault examination|
gender dysphoria|gender-affirming|hormone therapy|transgender|transition|prep|post-exposure prophylaxis|pep
""")

GENETIC = _terms("""
genetic test|genetic testing|genetic screening|brca|brca1|brca2|carrier status|genetic carrier|
genetic predisposition|genetic mutation|gene mutation|23andme|ancestry dna|dna test|paternity test|
family history of|hereditary|huntington's gene|apoe4|lynch syndrome|genome|genomic|karyotype|
chromosomal abnormality|prenatal genetic|amniocentesis
""")

DISABILITY = _terms("""
disabled|disability|disabilities|permanent disability|total disability|partial disability|ssdi|ssi|
social security disability|handicapped|wheelchair|wheelchair-bound|mobility impairment|impairment rating|
whole person impairment|permanent impairment|ada accommodation|reasonable accommodation|service animal|
blind|legally blind|deaf|hard of hearing|intellectual disability|developmental disability|learning disability|
special education|iep|504 plan|cognitive disability|amputee|prosthesis
""")

CRIMINAL = _terms("""
arrested|arrest record|prior arrest|charged with|convicted|conviction|prior conviction|felony|felon|
misdemeanor|pleaded guilty|pled guilty|plea deal|plea agreement|nolo contendere|probation|on probation|
parole|on parole|incarcerated|incarceration|prison|jail|served time|sentenced|sentence|criminal record|
criminal history|rap sheet|sex offender|registered sex offender|restraining order|protective order|
domestic violence|dv|batterer|warrant|outstanding warrant|bench warrant|indicted|indictment|acquitted|
expunged|expungement|sealed record|juvenile record|juvenile detention|gang member|gang affiliation
""")

IMMIGRATION = _terms("""
undocumented|illegal alien|illegal immigrant|unauthorized immigrant|immigration status|visa status|
overstayed|visa overstay|green card|permanent resident|lawful permanent resident|lpr|daca|dreamer|
asylum|asylee|asylum seeker|refugee|refugee status|tps|temporary protected status|deportation|deported|
removal proceedings|ice detention|immigration detention|naturalization|naturalized citizen|citizenship status|
work permit|ead|employment authorization|h-1b|h1b|f-1 visa|j-1 visa|u visa|t visa|vawa|i-130|i-485|i-589|
not a citizen|non-citizen|noncitizen
""")

SPECIAL = _terms("""
muslim|christian|catholic|jewish|hindu|buddhist|sikh|mormon|lds|jehovah's witness|atheist|agnostic|
evangelical|baptist|methodist|pentecostal|orthodox|scientologist|gay|lesbian|bisexual|homosexual|
queer|lgbt|lgbtq|lgbtq+|same-sex|pansexual|asexual|sexual orientation|democrat|republican|socialist|
communist|libertarian|political affiliation|union member|union membership|labor union|teamsters|afl-cio|
seiu
""")

_LAB = re.compile(
    r"(?i)\b(?:hba1c|a1c|glucose|ldl|hdl|cholesterol|triglycerides|tsh|t4|psa|creatinine|egfr|bun|alt|ast|"
    r"hemoglobin|hgb|hematocrit|hct|wbc|rbc|platelets|plt|inr|pt/inr|ptt|troponin|bnp|cd4|viral\s+load|bmi|"
    r"blood\s+pressure|bp|heart\s+rate|hr|pulse|spo2|o2\s+sat|temp(?:erature)?|weight|crp|esr|vitamin\s+d|"
    r"potassium|sodium|calcium|ferritin|iron|b12|folate|lipase|amylase|bilirubin|albumin|alkaline\s+phosphatase|"
    r"urinalysis|ua|uds|bac|blood\s+alcohol)\b\s*(?:level|count|of|was|is|:|=)?\s*"
    r"(?:<|>|≤|≥)?\s*\d{1,4}(?:\.\d{1,3})?(?:\s*/\s*\d{2,3})?\s*(?:%|mg/dl|mmol/l|g/dl|ng/ml|u/l|iu/l|"
    r"mmhg|bpm|kg|lbs?|copies/ml|cells/mm3|k/ul|x10\^?\d+/l|meq/l|mg/l|pg/ml|°?f|°?c)?"
    r"|\b(?:tested|test(?:ed)?\s+came\s+back|screen(?:ed)?|results?\s+(?:were|was))\s+(?:positive|negative|"
    r"reactive|non-?reactive|abnormal|elevated)\s+for\s+[A-Za-z0-9 -]{2,40}"
    r"|\b(?:positive|negative|reactive|detected|not\s+detected)\s+for\s+(?:hiv|hepatitis|covid|thc|cocaine|"
    r"opiates|amphetamines|benzodiazepines|alcohol|chlamydia|gonorrhea|syphilis|pregnancy|[A-Za-z0-9 -]{2,25})")

_PRIV_MARK = re.compile(
    r"(?i)\b(?:privileged\s*(?:&|and)\s*confidential|attorney[- ]client\s+(?:privilege[d]?|communication)|"
    r"attorney\s+work\s+product|work\s+product|prepared\s+(?:at\s+the\s+direction|in\s+anticipation)\s+of\s+"
    r"(?:counsel|litigation)|confidential\s+(?:legal\s+)?(?:advice|communication)|privileged\s+communication|"
    r"subject\s+to\s+(?:the\s+)?(?:attorney[- ]client\s+)?privilege|legal\s+advice|for\s+settlement\s+purposes\s+"
    r"only|fre\s+408|rule\s+408|mediation\s+privilege|joint\s+defense|common\s+interest)\b")
_MONEY = re.compile(r"(?<![\w])(?:US)?\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?(?:\s?(?:million|billion|thousand|[mkb]))?"
                    r"(?![\w])|\b\d{1,3}(?:,\d{3})+(?:\.\d{2})?\s+(?:dollars|usd)\b|\b\d+(?:\.\d+)?\s+(?:million|"
                    r"thousand)\s+dollars\b", re.I)
_FINANCIAL = re.compile(
    r"(?i)\b(?:salary|wage|wages|hourly\s+rate|annual\s+income|monthly\s+income|gross\s+income|net\s+income|"
    r"income|earnings|net\s+worth|credit\s+score|fico|debt|debts|bankruptcy|chapter\s+(?:7|11|13)|foreclosure|"
    r"lien|garnishment|child\s+support|alimony|spousal\s+support|tax\s+return|w-2|1099|lost\s+wages|"
    r"loss\s+of\s+earning\s+capacity|earns|earned|earning|makes|made|making|paid|pays|bringing\s+home|takes\s+home)\b"
    r"(?:\s+(?:of|is|was|were|:|totaling|totalling|approximately|about|roughly|around))?"
    r"\s*(?:\$\s?\d[\d,]*(?:\.\d{2})?(?:\s*(?:per|/|an|a)\s*(?:hour|hr|week|wk|month|mo|year|yr|annum))?|"
    r"\d{3}(?![\d,]))")
_SETTLEMENT = re.compile(r"(?i)\b(?:settle(?:d|ment)?|offer(?:ed)?|demand(?:ed)?|policy\s+limits?|verdict|award(?:ed)?|"
                         r"judgment|lien|reserve|tender(?:ed)?|counter-?offer)\b[^\n$]{0,60}?(\$\s?\d[\d,]*(?:\.\d{1,2})?"
                         r"(?:\s?(?:million|thousand|[mk]))?)")


def _lexicon_rx(terms: list[str]) -> re.Pattern:
    alts = sorted({re.escape(t) for t in terms}, key=len, reverse=True)
    return re.compile(r"(?i)(?<![\w-])(?:" + "|".join(alts) + r")(?![\w-])")


_LEXICONS: list[tuple[str, re.Pattern, float, str]] = [
    ("SUBSTANCE_USE", _lexicon_rx(SUBSTANCE), 0.8, "substance-use information (42 CFR Part 2 protected)"),
    ("MENTAL_HEALTH", _lexicon_rx(MENTAL_HEALTH), 0.8, "mental-health information"),
    ("SEXUAL_REPRODUCTIVE_HEALTH", _lexicon_rx(SEXUAL_REPRO), 0.8, "sexual / reproductive health information"),
    ("GENETIC", _lexicon_rx(GENETIC), 0.8, "genetic information (GINA)"),
    ("DISABILITY", _lexicon_rx(DISABILITY), 0.7, "disability status"),
    ("MEDICATION", _lexicon_rx(MEDICATIONS), 0.8, "medication"),
    ("MEDICAL_CONDITION", _lexicon_rx(CONDITIONS), 0.75, "medical condition / diagnosis"),
    ("INJURY", _lexicon_rx(INJURIES), 0.7, "injury"),
    ("MEDICAL_PROCEDURE", _lexicon_rx(PROCEDURES), 0.7, "medical procedure / treatment"),
    ("CRIMINAL_HISTORY", _lexicon_rx(CRIMINAL), 0.7, "criminal-history information"),
    ("IMMIGRATION_STATUS", _lexicon_rx(IMMIGRATION), 0.75, "immigration status"),
    ("SPECIAL_CATEGORY", _lexicon_rx(SPECIAL), 0.6, "religion / sexual orientation / political or union affiliation"),
]
# Short, ambiguous terms that need a clinical/legal cue nearby before they count.
_AMBIGUOUS = {"si", "mat", "add", "asd", "als", "ua", "bac", "dv", "na", "prep", "pep", "ead", "lpr", "tps", "esi",
              "ncs", "rfa", "ect", "ssi", "iep", "meth", "lds", "transition", "cutting", "sentence", "prison", "jail",
              "warrant", "orthodox", "christian", "catholic", "baptist", "democrat", "republican", "gay", "blind",
              "deaf", "rehab", "detox", "recovery program", "withdrawal", "strain", "sprain", "swelling", "bruising",
              "stent", "bypass", "sepsis", "transgender", "manic", "dementia", "psychotic", "suicide", "overdose",
              "relapse", "tumor", "cbt", "emdr", "lithium", "soma", "chantix", "insulin", "mri", "x-ray", "xray"}
_CLINICAL_CUE = re.compile(r"(?i)\b(?:diagnos|dx|history\s+of|hx|treat|patient|pt\b|client|presents|reports|denies|"
                           r"complain|assessment|impression|plan|prescri|rx|mg|taking|takes|med(?:ication)?s?|"
                           r"therap|clinic|hospital|admit|discharg|symptom|condition|positive|negative|test|"
                           r"screen|referr|evaluat|exam|counsel|charged|arrest|convict|court|status|record|"
                           r"religio|church|faith|identif|orientation|member|affiliat|imaging|ordered|scan|"
                           r"results?|findings?|surgery|procedure|injur|pain|vehicle|collision|crash|accident)")


_ANATOMY_AFTER = re.compile(r"(?i)\s*(?:joints?|nerve|pain|dysfunction|region|area|fusion|injection|belt|units?|"
                            r"system|unit)\b")


def find_sensitive(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for entity, rx, score, why in _LEXICONS:
        for m in rx.finditer(t):
            term = m.group().lower()
            s, e = m.span()
            if term in _AMBIGUOUS:
                if len(term) <= 3 and _ANATOMY_AFTER.match(t[e:e + 14]):
                    continue  # "SI joint", "ADD unit"
                if len(term) <= 3 and not m.group().isupper() and term not in ("mri",):
                    # very short abbreviations only count in caps and with a clinical cue
                    continue
                if not _CLINICAL_CUE.search(t[max(0, s - 100):e + 100]):
                    continue
            yield _mk(nt, s, e, entity, score, f"lexicon:{entity.lower()}", why)
    for m in _LAB.finditer(t):
        yield _mk(nt, *m.span(), "LAB_RESULT", 0.75, "pattern:lab_result", "lab value / test result")
    for m in _PRIV_MARK.finditer(t):
        # privilege marker: the whole paragraph it heads is privileged
        ls = t.rfind("\n", 0, m.start()) + 1
        le = t.find("\n", m.end())
        le = len(t) if le < 0 else le
        if le - ls < 120:  # the marker is a header line: privileged content starts there
            ps = ls
        else:
            ps = t.rfind("\n\n", 0, m.start())
            ps = 0 if ps < 0 else ps + 2
        pe = t.find("\n\n", le)
        pe = len(t) if pe < 0 else pe
        yield _mk(nt, ps, pe, "PRIVILEGED", 0.7, "pattern:privilege_marker",
                  f"paragraph marked “{m.group()}” — review for privilege")
    for m in _SETTLEMENT.finditer(t):
        yield _mk(nt, *m.span(1), "MONEY", 0.85, "pattern:settlement_amount", "settlement / demand / award amount")
    for m in _MONEY.finditer(t):
        yield _mk(nt, *m.span(), "MONEY", 0.6, "pattern:money", "monetary amount")
    for m in _FINANCIAL.finditer(t):
        if re.search(r"\$\s?0(?:\.00)?$", m.group()):
            continue  # "Foreign tax paid  $ 0.00" says nothing about anyone's finances
        yield _mk(nt, *m.span(), "FINANCIAL_INFO", 0.8, "pattern:financial", "income / financial status")


def _mk(nt: NormText, s: int, e: int, entity: str, score: float, source: str, why: str) -> Span:
    os_, oe = nt.to_original(s, e)
    return Span(os_, oe, entity, score, source, nt.original[os_:oe], why)


def expand_to_sentence(text: str, sp: Span) -> tuple[int, int]:
    """Sentence that contains a span (for "redact the whole sentence" mode on sensitive topics)."""
    a = max(text.rfind(". ", 0, sp.start), text.rfind("\n", 0, sp.start), text.rfind("? ", 0, sp.start),
            text.rfind("! ", 0, sp.start), text.rfind("; ", 0, sp.start))
    a = a + 2 if a >= 0 and text[a] != "\n" else a + 1
    ends = [x for x in (text.find(". ", sp.end), text.find("\n", sp.end), text.find("? ", sp.end),
                        text.find("! ", sp.end), text.find("; ", sp.end)) if x >= 0]
    b = min(ends) + 1 if ends else len(text)
    if b > len(text):
        b = len(text)
    while b > a and text[b - 1] in " \n":
        b -= 1
    return max(a, 0), b


SENSITIVE_CONTENT_ENTITIES = {"MEDICAL_CONDITION", "MEDICATION", "MEDICAL_PROCEDURE", "LAB_RESULT", "MENTAL_HEALTH",
                              "SUBSTANCE_USE", "SEXUAL_REPRODUCTIVE_HEALTH", "GENETIC", "DISABILITY", "INJURY",
                              "CRIMINAL_HISTORY", "IMMIGRATION_STATUS", "SPECIAL_CATEGORY", "FINANCIAL_INFO"}
