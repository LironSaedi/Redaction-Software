"""Indirect identifiers (quasi-identifiers).

A phrase can identify someone without naming them: "the night manager at the McDonald's on Bank
Street", "his 7-year-old daughter", "the only Black officer on the overnight shift", "a red 2015 Ford
F-150 with a dented tailgate". Each pattern here produces a span with an explanation of *why* it can
identify a person, and :func:`combine_risk` raises the score when several indirect identifiers point
at the same person in the same sentence (location + role + time is far more identifying than any
one alone).
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from .addresses import DIRECTIONS, STREET_REF, SUFFIXES
from .base import NormText, Span

BRANDS = [
    "McDonald's", "McDonalds", "Burger King", "Wendy's", "Taco Bell", "KFC", "Kentucky Fried Chicken", "Subway",
    "Starbucks", "Dunkin'", "Dunkin", "Dunkin' Donuts", "Chick-fil-A", "Popeyes", "Arby's", "Sonic", "Dairy Queen",
    "Pizza Hut", "Domino's", "Papa John's", "Little Caesars", "Chipotle", "Panera", "Panera Bread", "IHOP",
    "Denny's", "Waffle House", "Cracker Barrel", "Applebee's", "Chili's", "Olive Garden", "Red Lobster",
    "Outback", "Outback Steakhouse", "Buffalo Wild Wings", "Hooters", "Jack in the Box", "Carl's Jr.", "Hardee's",
    "Whataburger", "In-N-Out", "Five Guys", "Culver's", "Zaxby's", "Bojangles", "Raising Cane's", "Wingstop",
    "Panda Express", "Del Taco", "Krispy Kreme", "Tim Hortons", "Jersey Mike's", "Jimmy John's", "Firehouse Subs",
    "Walmart", "Wal-Mart", "Walmart Supercenter", "Target", "Costco", "Sam's Club", "BJ's", "Kroger", "Publix",
    "Safeway", "Albertsons", "Whole Foods", "Trader Joe's", "Aldi", "Lidl", "H-E-B", "HEB", "Meijer",
    "Winn-Dixie", "Food Lion", "Giant", "Giant Eagle", "Stop & Shop", "Wegmans", "ShopRite", "Hy-Vee", "Ralphs",
    "Vons", "Piggly Wiggly", "Harris Teeter", "Fry's", "King Soopers", "Home Depot", "Lowe's", "Menards",
    "Best Buy", "Walgreens", "CVS", "Rite Aid", "Dollar General", "Dollar Tree", "Family Dollar", "7-Eleven",
    "7-11", "Circle K", "Shell", "Exxon", "Mobil", "ExxonMobil", "Chevron", "BP", "Texaco", "Sunoco", "Speedway",
    "Wawa", "Sheetz", "QuikTrip", "QT", "RaceTrac", "Marathon", "Valero", "Citgo", "Love's", "Pilot",
    "YMCA", "YWCA", "Buc-ee's", "Flying J", "Ace Hardware", "Kwik Trip", "Kwik Star", "Casey's", "Road Ranger",
    "Loaf N Jug", "Thorntons", "Holiday", "Cumberland Farms", "Stewart's", "GetGo", "Maverik", "Kum & Go",
    "Family Fare", "Piggly Wiggly", "Save A Lot", "Food 4 Less", "WinCo", "Fred Meyer", "Smith's", "Hannaford",
    "Flying J", "Casey's", "Kum & Go", "Murphy USA", "Buc-ee's", "Kmart", "Sears", "Macy's", "Kohl's",
    "JCPenney", "J.C. Penney", "Nordstrom", "TJ Maxx", "T.J. Maxx", "Marshalls", "Ross", "Burlington",
    "Old Navy", "Gap", "AutoZone", "O'Reilly", "O'Reilly Auto Parts", "Advance Auto Parts", "Jiffy Lube",
    "Planet Fitness", "LA Fitness", "Gold's Gym", "Anytime Fitness", "24 Hour Fitness", "Bank of America",
    "Chase", "Wells Fargo", "Citibank", "PNC", "TD Bank", "U.S. Bank", "Regions", "Truist", "Motel 6",
    "Holiday Inn", "Hampton Inn", "Marriott", "Hilton", "Best Western", "Super 8", "Days Inn", "Red Roof Inn",
    "La Quinta", "Comfort Inn", "Quality Inn", "Extended Stay", "Petco", "PetSmart", "GameStop", "Staples",
    "Office Depot", "FedEx", "UPS Store", "Goodwill", "Salvation Army", "Hobby Lobby", "Michaels", "Ulta",
    "Sephora", "Bed Bath & Beyond", "IKEA", "Big Lots", "Tractor Supply", "Academy Sports", "Dick's Sporting Goods",
    "Bass Pro Shops", "Cabela's", "Barnes & Noble", "Tesla", "Amazon warehouse", "Amazon Fulfillment Center",
]
VENUE_NOUNS = (
    r"Apartments|Apts|Apartment\s+Complex|Condominiums|Condos|Townhomes|Townhouses|Mobile\s+Home\s+Park|"
    r"Trailer\s+Park|RV\s+Park|Motel|Inn|Hotel|Suites|Lodge|Bar|Tavern|Pub|Saloon|Grill|Bar\s+&\s+Grill|"
    r"Diner|Cafe|Café|Coffee|Bakery|Restaurant|Cantina|Taqueria|Pizzeria|Steakhouse|Lounge|Nightclub|Club|"
    r"Church|Chapel|Cathedral|Mosque|Masjid|Synagogue|Temple|Gurdwara|Gym|Fitness|Salon|Barbershop|"
    r"Barber\s+Shop|Spa|Laundromat|Market|Mart|Supermarket|Grocery|Liquor(?:\s+Store)?|Pawn(?:\s+Shop)?|"
    r"Daycare|Day\s+Care|Preschool|Shelter|Plaza|Mall|Shopping\s+Center|Car\s+Wash|Auto\s+Repair|Body\s+Shop|"
    r"Garage|Tire|Smoke\s+Shop|Vape|Dispensary|Arcade|Bowling|Rink|Stadium|Arena|Marina|Warehouse|Factory|"
    r"Plant|Depot|Yard|Farm|Ranch|Dealership|Motors|Tattoo|Nail(?:s|\s+Salon)?|Massage|Cleaners|Florist|"
    r"Pharmacy|Clinic|Urgent\s+Care|Dental\s+(?:Clinic|Office|Care|Group)|Kennel|Stables|Cemetery|Funeral\s+Home|Library|Rec(?:reation)?\s+Center|"
    r"Community\s+Center|Boys\s+&\s+Girls\s+Club|YMCA|Station|Precinct|Firehouse|Farmers\s+Market|Flea\s+Market|"
    r"Learning\s+Center|Child\s*Care(?:\s+Center)?|Distribution\s+Center|Fulfillment\s+Center|Public\s+Library|"
    r"Shopping\s+Strip|Strip|Truck\s+Stop|Travel\s+(?:Center|Stop|Plaza)|Brewery|Icehouse|Food\s+Truck\s+Park|"
    r"Rec\s+Complex|Sports\s+Complex|Aquatic\s+Center|Pavilion|Senior\s+Center|Towing|Auto\s+Body|"
    r"Package\s+Store|Bakehouse|Bakery|Taproom|Cantina"
)
GENERIC_PLACES = (r"gas\s+station|convenience\s+store|corner\s+store|liquor\s+store|grocery\s+store|"
                  r"laundromat|bus\s+stop|bus\s+station|train\s+station|parking\s+lot|parking\s+garage|"
                  r"apartment\s+complex|trailer\s+park|motel|bar|nightclub|church|mosque|synagogue|"
                  r"school|daycare|park|playground|pharmacy|pawn\s+shop|car\s+wash|strip\s+club|"
                  r"homeless\s+shelter|shelter|food\s+bank|clinic|hospital|restaurant|diner|truck\s+stop|"
                  r"rest\s+stop|warehouse|construction\s+site|job\s+site|store|shop|house|home|residence|"
                  r"duplex|townhouse|cul-de-sac|dead\s+end|alley|underpass|overpass|bridge|field|lot|icehouse|"
                  r"beer\s+garden|honky-?tonk|dance\s+hall|brewery|taproom|pool\s+hall|food\s+truck|"
                  r"taco\s+stand|farmers\s+market|flea\s+market")

_BRAND_RX = r"(?:" + "|".join(re.escape(b).replace(r"\'", "['’]?").replace("'", "['’]?") for b in
                              sorted(BRANDS, key=len, reverse=True)) + r")"
_PROPER = r"(?:[A-Z][A-Za-z0-9'’&.-]+)(?:[ \t]+(?:[A-Z][A-Za-z0-9'’&.-]+|&|of|and|the|on|de|la)){0,4}"
_WEEKDAYS = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|January|February|March|April|May|June|July|August|September|October|November|December)"
_PREP_LOC = (r"(?:on|at|off(?:\s+of)?|near|by|along|across\s+from|next\s+to|behind|in\s+front\s+of|beside|"
             r"adjacent\s+to|located\s+(?:on|at)|just\s+(?:off|past|north\s+of|south\s+of|east\s+of|west\s+of)|"
             r"(?:north|south|east|west)\s+of|at\s+the\s+corner\s+of|on\s+the\s+corner\s+of|around\s+the\s+corner\s+from)")
_STREETISH = rf"(?:{STREET_REF}|(?:Route|Rte|Highway|Hwy|State\s+(?:Road|Route|Highway)|SR|US|U\.S\.|County\s+Road|CR|FM|I)[- ]?\d{{1,4}}(?![\w])|(?:Main|Broadway|Market|Bank|Church|High|Park|Mill|Water|Front|Bridge|Elm|Oak|" \
             rf"Pine|Maple|Cedar|Washington|Lincoln|Jefferson|Madison|Franklin|Center|Central)(?![A-Za-z])|" \
             rf"\d{{1,3}}(?:st|nd|rd|th)(?:\s+(?:{SUFFIXES})\.?)?(?![A-Za-z]))"
_INTERSECTION = rf"(?:{_STREETISH}|[A-Z][a-z]+)\s*(?i:and|&|/|at)\s*(?:{_STREETISH}|\d{{3,4}}(?![\d,.]))"

_PLACE_AT_STREET = re.compile(
    rf"(?:\b(?i:the|a|that|this)[ \t]+)?(?<![A-Za-z])(?:(?i:{_BRAND_RX})|{_PROPER}\s+(?:{VENUE_NOUNS})|(?i:{GENERIC_PLACES}))"
    rf"(?:\s+(?i:store|station|restaurant|location|branch|parking\s+lot|drive-?thru|lot))?(?:\s*#\s*\d{{1,6}})?"
    rf"(?:\s*\([^)]{{0,40}}\))?\s+(?i:{_PREP_LOC})\s+(?:(?i:the)\s+)?(?:(?i:corner\s+of)\s+)?"
    rf"(?:{_INTERSECTION}|{_STREETISH}|(?!{_WEEKDAYS})[A-Z][a-z]{{2,}}(?:[ \t][A-Z][a-z]{{2,}})?(?=[\s,.;)]))")
_NUMBERED_STORE = re.compile(rf"(?<![A-Za-z])(?:{_PROPER}[ \t]+)?(?:Pharmacy|[Ss]tore|Market|Station|Supercenter|Branch|Location)"
                             rf"\s*(?:Store\s*)?#\s*\d{{1,6}}")
_SLASH_X = re.compile(rf"(?:(?i:the)[ \t]+)?(?:{STREET_REF}|[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)?)(?:[ \t]+(?:WB|EB|NB|SB))?[ \t]*/[ \t]*"
                      rf"(?:{STREET_REF}|[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)?)(?:[ \t]+(?:WB|EB|NB|SB|intersection))?")
# form vocabulary that looks like "X/Y" streets: "Location type: Street/Highway", "Rdwy Part: Main/Proper Lane"
_GENERIC_ROAD_WORDS = {"street", "highway", "road", "city", "state", "zip", "county", "main", "proper", "lane", "frontage",
                       "service", "ramp", "interstate", "other", "alley", "private", "public", "drive", "avenue",
                       "parking", "lot", "rural", "urban", "type", "intersection", "the", "wb", "eb", "nb", "sb",
                       "driveway", "residential", "commercial", "access", "shoulder", "median", "unknown", "st", "zip",
                       "province", "country", "apt", "unit"}
_INTERSECTION_RX = re.compile(rf"\b(?:(?i:the)\s+)?(?i:corner|intersection|junction|crossroads)\s+(?i:of)\s+"
                              rf"{_INTERSECTION}|(?<![\w])(?:{STREET_REF})\s+(?i:and|&|at|@)\s+(?:{STREET_REF})")
_PROPER_ANY = r"(?:[A-Z][A-Za-z0-9'’&.-]+|[A-Z]{2,})(?:[ \t]{1,2}(?:[A-Z][A-Za-z0-9'’&.-]+|[A-Z]{2,}|&|of|and|the|de|la)){0,4}"
_RYAN_WHITE_RX = re.compile(r"(?i)\bryan\s+white\b")
_NAMED_VENUE = re.compile(rf"(?<![A-Za-z])(?:(?i:the)[ \t]+)?[\x22\u201c]?{_PROPER_ANY}\s+(?i:{VENUE_NOUNS})[\x22\u201d]?(?![A-Za-z])")
# a "proper" part made only of service / specialty words names a kind of place, not a particular one:
# "Trauma clinic", "Women's shelter", "Restaurant Depot", "Pain Management Clinic"
_GENERIC_VENUE_WORDS = {w.lower() for w in """
trauma ortho orthopedic orthopaedic cardiology cardiac neuro neurology neurosurgery pain management wound hand spine
sports medicine surgery surgical follow-up followup infusion dialysis women's womens men's mens pediatric pediatrics
family primary urgent specialty eye vision dental breast cancer oncology sleep allergy rheumatology endocrine
endocrinology diabetes vein physical therapy pt rehab rehabilitation behavioral mental health methadone hiv walk-in
free mobile main outpatient inpatient employee student campus homeless restaurant hospital medical clinic city county
pos purchase checkcard debit card ach online transfer payment pmt recurring plastic bone joint & and of
house home yard work hand spine sports foot ankle skin dermatology podiatry eye vision hearing
state community public local nearest new old big little the a our my your his her their this that same other weight
loss fertility wellness immunization vaccine flu covid testing lab laboratory imaging radiology x-ray mri ct ent
gi gastroenterology pulmonary lung kidney renal liver transplant burn stroke heart memory geriatric senior
""".split()}
_BRAND_ALONE = re.compile(rf"(?<![A-Za-z])(?:the\s+)?{_BRAND_RX}(?:\s+(?:Pharmacy|Store|Supercenter|Station|Market|"
                          rf"Gas|Restaurant|Oil|Express|lot|parking\s+lot|drive-?thru|pumps?))?(?:\s*#\s*\d{{1,6}}|\s+(?:No\.|Store)\s*\d{{1,6}})?(?![A-Za-z])", re.I)
_MERCHANT = re.compile(rf"(?i:{_BRAND_RX})(?:\s+[A-Z]{{2,10}})?\s*#?\s*[A-Z]?\d{{2,6}}\s+[A-Z][A-Z .'-]{{2,30}}?\s+"
                       rf"(?:AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|"
                       rf"NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)(?![A-Za-z])")
_LIVES_ON = re.compile(rf"\b(?i:lives?|lived|living|resides?|resided|residing|stays?|stayed|staying|home|house|"
                       rf"apartment|trailer|place)\s+(?i:is\s+|was\s+)?(?i:(?:over|down|up|out|right)\s+)?"
                       rf"(?i:on|off(?:\s+of)?|near|at\s+the\s+end\s+of)\s+((?:{STREET_REF}))")
_UNIT_REF = re.compile(r"(?i)(?<![\w])(?:apartment|apt\.?|suite|ste\.?|trailer|lot)\s*#?\s*[0-9]{1,5}[a-z]?(?![\w])"
                       r"|(?<![\w])(?:apartment|apt\.?)\s+[A-Z](?![\w])")
# "unit 12" / "room 214" only count with a residential / lodging cue nearby (crash reports use "Unit 1")
_UNIT_SOFT = re.compile(r"(?i)(?<![\w])(?:unit|room|rm\.?|space|cell|bunk|bed)\s*#?\s*[0-9]{1,5}[a-z]?(?![\w])")
_RESIDENTIAL_CUE = re.compile(r"\b(?:[Aa]partments?|[Rr]ent|[Aa]pts|[Cc]ondos?|[Cc]ondominiums?|complex|building|[Bb]ldg|[Mm]otel|"
                              r"[Hh]otel|[Ii]nn|lives?|living|stays?|staying|stayed|resides?|dorm|residence|home|"
                              r"house|shelter|jail|prison|ward|floor|[Tt]ownhomes?|[Vv]illas?|[Tt]ower)\b")

ROLE_NOUNS = (
    r"manager|assistant\s+manager|general\s+manager|shift\s+(?:manager|lead|supervisor)|supervisor|foreman|"
    r"forewoman|owner|co-owner|proprietor|franchisee|cashier|clerk|teller|bartender|barback|bouncer|waiter|"
    r"waitress|server|host|hostess|cook|chef|line\s+cook|dishwasher|janitor|custodian|maintenance\s+(?:man|"
    r"worker|guy)|handyman|security\s+guard|guard|attendant|valet|driver|bus\s+driver|delivery\s+driver|"
    r"mail\s+carrier|mailman|courier|receptionist|secretary|nurse|charge\s+nurse|aide|cna|caregiver|nanny|"
    r"babysitter|tutor|teacher|substitute|principal|vice\s+principal|coach|counselor|librarian|pastor|"
    r"priest|minister|rabbi|imam|deacon|landlord|landlady|property\s+manager|super(?:intendent)?|doorman|"
    r"neighbor|neighbour|roommate|tenant|coworker|co-worker|colleague|employee|intern|trainee|apprentice|"
    r"pharmacist|technician|tech|mechanic|dispatcher|operator|stocker|stock\s+boy|bagger|greeter|"
    r"lifeguard|trainer|instructor|stylist|barber|bartender|dealer|pit\s+boss|usher|clerk|"
    r"officer|deputy|trooper|detective|sergeant|lieutenant|captain|firefighter|paramedic|emt|"
    r"informant|witness|victim|complainant|caller|reporting\s+party|suspect|bystander|passerby|"
    r"customer|patron|regular|resident|student|classmate|teammate"
)
RELATION_NOUNS = (
    r"husband|wife|spouse|ex-husband|ex-wife|ex|fianc[ée]e?|boyfriend|girlfriend|partner|ex-boyfriend|"
    r"ex-girlfriend|son|daughter|stepson|stepdaughter|child|children|kid|kids|baby|infant|twin|twins|"
    r"mother|mom|father|dad|stepmother|stepmom|stepfather|stepdad|parent|parents|grandmother|grandma|"
    r"grandfather|grandpa|grandson|granddaughter|grandchild|brother|sister|half-brother|half-sister|"
    r"stepbrother|stepsister|sibling|aunt|uncle|cousin|niece|nephew|in-law|mother-in-law|father-in-law|"
    r"sister-in-law|brother-in-law|godmother|godfather|godson|goddaughter|guardian|foster\s+(?:child|"
    r"parent|mother|father)|best\s+friend|friend|family\s+friend|pastor|employer|boss"
)
_ROLE_MOD = (r"(?:only|sole|lone|one|night|day|morning|evening|overnight|weekend|graveyard|night-shift|next-door|"
             r"upstairs|downstairs|across-the-hall|across-the-street|"
             r"day-shift|head|lead|senior|chief|assistant|general|store|shift|floor|regional|district|"
             r"former|current|new|longtime|long-time|part-time|full-time|older|younger|oldest|youngest|eldest|"
             r"middle|first|second|third|twin|adopted|biological|estranged|late|\d{1,2}-year-old|roughly|about|"
             r"approximately|around|maternal|paternal|live-in|common-law|adult|grown|baby|"
             r"\d{1,2}[ -]?(?:y/?o|yo|yr-old|month-old|mo-old)|"
             r"(?:white|black|hispanic|latino|latina|asian|female|male|elderly|teenage|pregnant|disabled|"
             r"blind|deaf|wheelchair-bound|transgender|gay|lesbian))")
_SHIFT_ROLE = re.compile(r"(?i)\bworks?(?:ing)?\s+(?:the\s+)?(?:overnight|night|day|evening|weekend|graveyard|swing|early|"
                         r"late|morning)\s+shifts?\s+as\s+(?:an?|the)\s+[A-Za-z][\w/-]*(?:\s+[\w-]+){0,2}?"
                         r"(?:\s+(?:at|for)\s+(?:the\s+)?[A-Z][\w'’&.-]*(?:\s+[A-Za-z][\w'’&.-]*){0,5})?")
_GRADE_TEACHER = re.compile(r"(?i)\b(?:(?:his|her|their|my)\s+)?(?:\d(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|"
                            r"eighth|kindergarten|pre-?k)[- ]grade\s+teacher\b(?:\s+at\s+(?:the\s+)?[A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*){0,3})?")
_IS_THE_ROLE = re.compile(r"(?i)\b(?:she|he|they|who)\s+(?:is|was|works\s+as)\s+the\s+(?:[a-z]+\s+){0,2}(?:manager|supervisor|"
                          r"director|owner|teacher|principal|coach|nurse|pharmacist|clerk|bartender|cook|chef|foreman)\b")
_WORK_WITH = re.compile(r"(?i)\bthe\s+[a-z]+\s+(?:I|she|he|they)\s+works?\s+with\b")
_ROLE_PHRASE = re.compile(
    rf"\b(?i:the|her|his|their|my|our|your|its|whose)\s+(?i:{_ROLE_MOD}[\s,]+){{0,3}}(?i:{ROLE_NOUNS})"
    rf"(?:\s+(?i:at|of|for|from|in|on)\s+(?:(?i:the)\s+)?(?:(?i:{_BRAND_RX})|{_PROPER}))?"
    rf"(?:\s+(?i:and)\s+(?:[a-z-]+\s+)?(?i:partner|friend|coworker|co-worker|roommate|landlord|babysitter|sitter))?(?![A-Za-z])")
# whose relative: a party ("the victim's"), or another relative ("the children's", "her grandson's", "ex-wife's")
_KIN_OWNER = (r"children|child|kids|father|mother|grandson|granddaughter|grandmother|grandfather|son|daughter|boyfriend|"
              r"girlfriend|husband|wife|ex-wife|ex-husband|brother|sister|cousin|aunt|uncle|owner|boss|dock\s+boss|"
              r"landlord|neighbou?r|fianc[ée]e?|partner|stepfather|stepmother|stepdad|stepmom")
_RELATION_PHRASE = re.compile(
    rf"\b(?i:(?:the|her|his|their|my|our|your)\s+(?:{_KIN_OWNER})['’]s|ex-(?:wife|husband)['’]s|(?:pt|patient)['’]s|"
    rf"the\s+(?:victim|plaintiff|defendant|patient|claimant|witness|suspect|decedent|deceased|driver|insured|subject|"
    rf"debtor|member)['’]s|her|his|their|my|our|your|ur)\s+(?i:{_ROLE_MOD}[\s,]+){{0,3}}(?i:{RELATION_NOUNS})"
    rf"(?![A-Za-z-])")
# an age standing for the child: "she drops off her 4-year-old at the daycare"
_AGE_AS_CHILD = re.compile(r"\b(?i:her|his|their|my|our)\s+\d{1,2}[ -](?i:year|yr|month)[ -](?i:old)(?=\s*[,.;:)]|\s+(?:at|to|"
                           r"from|in|with|who|and|is|was|has|had|for|on)\b)")
_POSSESSIVE_RELATION = re.compile(
    rf"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)['’]s\s+(?i:{_ROLE_MOD}[\s,]+){{0,3}}(?i:{RELATION_NOUNS})(?![A-Za-z-])")
_UNIQUE = re.compile(r"(?i)\b(?:the\s+only|the\s+sole|the\s+lone|the\s+one\s+(?:who|that)|the\s+last|"
                     r"the\s+first|the\s+single|nobody\s+else|no\s+one\s+else)\b")

_EMPLOYER = re.compile(
    rf"\b(?i:works?|worked|working|employed|employment|job|jobs|hired|fired|terminated|laid\s+off|"
    rf"interns?|interned|volunteers?|volunteered|clocks?\s+in|shift)"
    rf"(?:\s+(?i:days|nights|weekends|mornings|evenings|afternoons|overnights|part-time|full-time|there|now|"
    rf"(?:on\s+)?(?:mon|tues|wednes|thurs|fri|satur|sun)days?(?:\s+(?:mornings|nights|evenings))?)){{0,2}}"
    rf"\s+(?:(?i:as)\s+(?i:an?|the)\s+[A-Za-z][A-Za-z'/ -]{{2,30}}?\s+)?"
    rf"(?i:at|for|by|with)\s+(?:(?i:the)\s+)?({_PROPER}|(?i:{_BRAND_RX}))")
# "I started at Swiftline", "I drove for Caliche Transport", "W-2 ... from Brightline CPA Group LLC",
# "She's an accountant, at Brightline CPA"
_EMPLOYER_MORE = re.compile(
    rf"\b(?:(?i:started|start|starting|began|begun)\s+(?:(?i:work(?:ing)?|driving|there)\s+)?(?i:at)|"
    rf"(?i:drove|drive|drives|driving|deliver(?:s|ed|ing)?|cook(?:s|ed|ing)?|clean(?:s|ed|ing)?)\s+(?i:for)|"
    rf"(?i:W-?2s?|W2s?|1099s?|pay\s*stubs?|paystubs?|wage\s+statements?|payroll\s+records)(?:\s+[A-Za-z'’]+){{0,4}}?\s+(?i:from|issued\s+by))"
    rf"\s+(?:(?i:the)\s+)?({_PROPER})")
# "my manager Gina Castellano at Cumberland Dental Lab", "DBA ZAYTOON KITCHEN & CATERING", "for work at 5am at X"
_BOSS_AT = re.compile(rf"\b(?i:my|his|her|their)\s+(?i:manager|boss|supervisor|foreman|employer|coworker|co-worker|"
                      rf"shift\s+lead|owner)\s+(?:[A-Z][a-z'’-]+\s+){{0,3}}(?i:at|from)\s+(?:(?i:the)\s+)?({_PROPER})")
_DBA = re.compile(r"\b(?:DBA|D/B/A|d/b/a|doing\s+business\s+as)[:\s]+([A-Z][A-Za-z0-9&.,'’ -]{2,60}?)(?=\s{2,}|\n|$|,)")
_FOR_WORK = re.compile(rf"\b(?i:for|to|from)\s+(?i:work|my\s+shift)\s+(?:(?i:at)\s+\d{{1,2}}(?::\d{{2}})?\s*(?i:am|pm|a\.m\.|p\.m\.)?\s+)?"
                       rf"(?i:at)\s+(?:(?i:the)\s+)?({_PROPER})")
_OCCUPATION_AT = re.compile(
    rf"\b(?i:an?|the|as\s+an?)\s+(?i:{'|'.join(sorted(('accountant', 'bookkeeper', 'cashier', 'clerk', 'nurse', 'teacher', 'engineer', 'mechanic', 'technician', 'manager', 'supervisor', 'driver', 'server', 'bartender', 'cook', 'chef', 'paralegal', 'receptionist', 'analyst', 'electrician', 'plumber', 'welder', 'lineman', 'pharmacist', 'hygienist', 'assistant', 'associate', 'agent', 'adjuster', 'dispatcher', 'stocker', 'loader', 'warehouse\\s+worker', 'sales\\s+associate', 'programmer', 'developer', 'consultant', 'therapist', 'caregiver', 'aide'), key=len, reverse=True))})"
    rf"\s*,?\s+(?i:at|for|with)\s+(?:(?i:the)\s+)?({_PROPER})")
# "I own a food truck. Seoul Food ATX." / "we run a small bakery called Sweet Bee"
_OWN_BUSINESS = re.compile(
    rf"\b(?i:I|we|she|he|they)\s+(?i:own|owns|run|runs|operate|operates|have|has|started)\s+(?i:a|an|my\s+own|our\s+own|"
    rf"her\s+own|his\s+own)\s+(?:[a-z-]+\s+){{0,2}}(?i:business|company|truck|food\s+truck|shop|store|restaurant|salon|"
    rf"firm|practice|bakery|cafe|café|bar|studio|gym|daycare|agency|landscaping|cleaning\s+service)\b"
    rf"(?:\s*[.,:;-]+\s*|\s+(?i:called|named)\s+)(?:(?i:it's|it\s+is|called|named)\s+)?({_PROPER})")
_CARRIER_KV = re.compile(r"(?i)(?<![a-z])(?:motor\s+)?carrier(?:\s+name)?\s*:\s*([A-Z][A-Za-z0-9&.,' -]{2,60}?)(?=\s{2,}|\n|$)")
NON_NAME_WORDS_LITE = {"the", "a", "an", "home", "least", "most", "first", "all", "noon", "night", "midnight", "monday",
                       "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "about", "approximately"}
_HR_LETTERHEAD = re.compile(r"(?m)^[ \t]*([A-Z][A-Za-z0-9&.,' -]{2,60}?)[ \t]*\n[ \t]*(?:Human\s+Resources|HR|Payroll|"
                            r"Personnel|Benefits)(?:\s+(?:Department|Dept\.?|Office|Division))?[ \t]*$")
_EMPLOYER_KV = re.compile(r"(?im)(?<![a-z])(?:employer|employment|employed\s+by|place\s+of\s+employment|company\s+name|"
                          r"business\s+name|name\s+of\s+(?:business|employer)|d/?b/?a|doing\s+business\s+as|"
                          r"employer\s+name|occupation/employer|current\s+employer|previous\s+employer|"
                          r"work\s+place|workplace)\s*[:]\s*([^\n]{2,80}?)(?=\s{2,}|\n|$)")
_PAYROLL = re.compile(r"(?i:payroll|direct\s+dep(?:osit)?|dir\s+dep|ach\s+credit|salary|payroll\s+direct\s+dep)\s+"
                      r"(?i:from\s+)?([A-Z][A-Z0-9&.,' -]{3,40}?)\s+(?:PPD|ACH|DIR|PAYROLL|ID:|CO\s+ID)")
# "Perth Amboy High, ninth grade", "he goes to Park Forest Middle", "HAWTHORNE RIDGE HIGH SCHOOL",
# "drives her to Peakview\n School", "the car-rider line at Sycamore Run"
_SCHOOL_MORE = re.compile(
    r"((?:[A-Z][A-Za-z'’-]+\s+){1,3}(?:High|Middle|Elementary|Intermediate|Junior\s+High))(?=\s*,?\s*(?:\d{1,2}(?:st|nd|rd|th)|"
    r"ninth|tenth|eleventh|twelfth|freshman|sophomore|junior|senior|first|second|third|fourth|fifth|sixth|seventh|"
    r"eighth|kindergarten)\s+(?:grade|year)\b|\s*[.,;)]|$)"
    r"|((?:[A-Z][A-Z'’.-]+\s+){1,4}(?:HIGH|MIDDLE|ELEMENTARY|INTERMEDIATE|PRIMARY|CHARTER|PREPARATORY)\s+(?:SCHOOL|ACADEMY))\b"
    r"|(?:(?i:goes\s+to|attends|attended|drives\s+(?:her|him|them)\s+to|takes?\s+(?:her|him|them)\s+to|"
    r"picks?\s+(?:her|him|them)\s+up\s+(?:at|from)|car-rider\s+line\s+at|bus\s+to|enrolled\s+(?:at|in))\s+)"
    r"((?:[A-Z][A-Za-z'’-]+(?:[ \t]+|\n[ \t]*)){0,3}(?:[A-Z][A-Za-z'’-]+))(?=\s*(?:School|Academy)?\b)"
    r"(?:\s+(?:School|Academy))?", re.M)
_SCHOOL = re.compile(
    rf"(?<![A-Za-z])(?:(?:[A-Z][A-Za-z.'’-]+\s{{1,9}}){{1,4}}(?:Elementary|Middle|High|Junior\s+High|Senior\s+High|"
    rf"Intermediate|Primary|Secondary|Charter|Montessori|Christian|Catholic|Magnet|Day|Preparatory|Prep)\s{{1,9}}(?:School|Academy)"
    rf"|(?:[A-Z][A-Za-z.'’-]+(?:[ ]|\n[ \t]{{0,12}})){{1,3}}Elementary(?![ ]School)"
    rf"|\b(?:UT|UC|SUNY|CUNY|UNC|Texas\s+A&M|A&M)[ -](?:Austin|Dallas|Arlington|El\s+Paso|"
    rf"San\s+Antonio|Tyler|Health|Southwestern|Rio\s+Grande\s+Valley|Berkeley|Davis|Irvine|San\s+Diego|Commerce|Kingsville|"
    rf"Corpus\s+Christi|Galveston|Chapel\s+Hill|Charlotte|Buffalo|Albany)(?![\w&])"
    rf"|\b(?:UCLA|LSU|TCU|SMU|UTEP|UTSA|UTRGV|UTHealth|Texas\s+A&M)(?![\w&])"
    rf"|(?:[A-Z][A-Za-z.'’-]+[ ]){{1,4}}(?:Academy|Preparatory\s+School)"
    rf"|(?:University|College|Institute)\s+of\s+(?:[A-Z][A-Za-z]+[ ]?){{1,4}}"
    rf"|(?:[A-Z][A-Za-z.'’-]+[ ]){{1,4}}(?:University|College|Community\s+College|State\s+University|"
    rf"Technical\s+College|Seminary))(?![A-Za-z])")
_SCHOOL_CTX = re.compile(r"(?i)\b(?:attends?|attended|attending|student|enrolled|graduated|grade|freshman|"
                         r"sophomore|junior|senior|class\s+of|transferred|expelled|suspended|teaches|taught)\b")

COLORS = (r"white|black|silver|gray|grey|red|blue|green|yellow|orange|gold|tan|beige|brown|maroon|burgundy|"
          r"purple|pink|teal|navy|dark|light|charcoal|champagne|bronze|copper|cream|ivory|lime|magenta|turquoise")
MAKES = (r"Acura|Alfa\s+Romeo|Audi|BMW|Buick|Cadillac|Chevrolet|Chevy|Chrysler|Dodge|Fiat|Ford|Genesis|GMC|"
         r"Honda|Hummer|Hyundai|Infiniti|Isuzu|Jaguar|Jeep|Kia|Land\s+Rover|Lexus|Lincoln|Mazda|Mercedes(?:-Benz)?|"
         r"Mercury|Mini|Mitsubishi|Nissan|Oldsmobile|Plymouth|Pontiac|Porsche|Ram|Rivian|Saab|Saturn|Scion|"
         r"Subaru|Suzuki|Tesla|Toyota|Volkswagen|VW|Volvo|Harley(?:-Davidson)?|Kawasaki|Yamaha|Ducati|"
         r"Freightliner|Peterbilt|Kenworth|Mack|International|Volvo\s+Truck")
_VEHICLE = re.compile(
    rf"\b(?:(?:19|20)\d{{2}}\s+)?(?:(?:{COLORS})(?:[\s-](?:{COLORS}|metallic|colored|coloured))?\s+)?"
    rf"(?:(?:19|20)\d{{2}}\s+)?(?:{MAKES})(?:\s+(?:[A-Z][A-Za-z0-9-]+|F-?\d{{3}}|[A-Z]?\d{{1,4}}[a-z]?)){{0,2}}"
    rf"(?:\s+(?:with|bearing)\s+[^.,;\n]{{3,60}})?", re.I)

_PHYSICAL = re.compile(
    r"\b(?:(?:a|an|the|his|her|their)\s+)?(?:[\w\x22'’-]+\s+){0,3}(?:tattoos?|tattooed|tats?|scars?|scarring|birthmarks?|"
    r"birth\s+marks?|keloid|moles?|piercings?|gold\s+(?:tooth|teeth|grill|grills|crown|cap|caps)|dreadlocks|dreads|"
    r"prosthetic\s+\w+|(?:below|above)[- ](?:the[- ])?(?:knee|elbow)\s+prosthesis|amputated\s+\w+|shaved\s+head|"
    r"missing\s+(?:the\s+)?(?:(?:tip|tips|end|top|last|first|two|three|both|upper|lower|front|middle|ring|index|pinky|"
    r"little|left|right)\s+){0,4}(?:of\s+(?:his|her|the)\s+(?:(?:left|right)\s+)?(?:\w+\s+)?)?(?:finger|fingers|toe|toes|"
    r"tooth|teeth|eye|leg|arm|hand|ear)|"
    r"(?:full|half)\s+sleeve(?:\s+of\s+[\w\s-]{1,30}?tattoos?)?|(?:long|waist-length)\s+(?:[\w-]+\s+){0,2}(?:braids?|"
    r"ponytail|dreads|dreadlocks|locs)|"
    r"(?:(?:big|long|white|gray|grey|red|black|blond|blonde|braided|handlebar|walrus|bushy|full|scraggly|forked|thick|"
    r"pointed|waxed)[\s-]+){1,3}(?:mustache|moustache|beard|goatee)|"
    r"(?:purple|pink|blue|green|red|white|blonde?|teal|gray|grey|silver)\s+streak\s+in\s+(?:his|her|their)\s+(?:\w+\s+)?hair|"
    r"vitiligo\s+patch(?:es)?|hook\s+where\s+(?:his|her)\s+(?:\w+\s+)?hand\s+should\s+be|"
    r"glass\s+eye|eye\s+patch|burn\s+scars?|"
    r"port[- ]wine\s+stain|cleft\s+(?:lip|palate)|limp|hearing\s+aid|"
    r"facial\s+hair|(?:(?<=with )|(?<=wears )|(?<=has a )|(?<=wearing )|(?<=a full )|(?<=thick )|(?<=long )|(?<=short ))(?:goatee|mustache|beard|dreadlocks|"
    r"cornrows|mohawk))(?![a-z/:])"
    r"(?:\s+(?:of|on|across|above|below|under|over|reading|that\s+(?:says|reads|splits|runs|wraps)|depicting|with|near|"
    r"behind|in|wrapping|running|covering|along|down|from|around|inside|spanning|stretching|extending|splitting|"
    r"tied\s+up\s+in|down\s+to|to)\s+[^.;\n]{1,60}(?:\n[ \t]*[^.;\n]{1,40})?|\s+(?:up\s+front|in\s+front))?", re.I)
# the way someone walks: "walks with a hitch on the right side", "walks with a quad cane on her right side"
_GAIT = re.compile(r"\b(?:walks|walked|walking)\s+with\s+(?:a|an)\s+(?:(?:slight|bad|noticeable|pronounced|heavy|quad|"
                   r"visible|permanent)\s+)?(?:limp|hitch|cane|quad\s+cane|walker|crutch|shuffle|brace)\b(?:\s+(?:on|in|"
                   r"favoring)\s+(?:his|her|the|their)\s+(?:left|right)(?:\s+(?:side|leg|foot|knee|hip|hand))?)?"
                   r"|\bdrags?\s+(?:his|her|their)\s+(?:left|right)\s+(?:foot|leg)\b", re.I)
# scars / marks / tattoos recorded as codes: "SMT-1   TAT L FARM \"SHIPROCK\" W/ EAGLE FEATHER"
_SMT_ROW = re.compile(r"(?m)^[ \t]*SMT[- ]?\d{1,2}[ \t]*[:.)-]?[ \t]+(\S[^\n]{2,80}?)[ \t]*$")
# a bulleted identification list: "- Tattoo L inner forearm, Arabic script", "- Gold crown on upper L canine"
_MARK_BULLET = re.compile(
    r"(?im)^[ \t]*(?:[-•*]|\d{1,2}[.)])[ \t]+((?:(?:healed|old|fresh|faded|small|large|well-healed|linear|raised)\s+)?"
    r"(?:[\w-]+\s+){0,2}(?:tattoos?|scars?|birthmarks?|amputation|gold\s+(?:crown|tooth|teeth|cap)|piercings?|moles?|"
    r"keloid|prosthe\w+|missing\s+\w+)\b[^\n]{0,90})$")
_SMT = re.compile(r"(?m)\b(?:TATTOO|TAT|SCAR|SC|BIRTHMARK|MOLE|PIERCING|PRC|MARK)\b[ A-Z]{0,20}--\s*[^;\n]{2,70}")
_SMT_FIELD = re.compile(r"(?im)^[ \t]*(?:SMT|scars\s*/\s*marks\s*/\s*tattoos|identifying\s+marks|scars|tattoos)\s*:\s*(.*)$")
_HEIGHT_WEIGHT = re.compile(r"\b(?:[4-7]\s*(?:'|ft\.?|feet|foot)\s*(?:\d{1,2}\s*(?:\"|in\.?|inches)?)?|"
                            r"[4-7]'\d{1,2}\"?)\s*(?:,|and|/)?\s*(?:\d{2,3}\s*(?:lbs?\.?|pounds))?", re.I)


def _mk(nt: NormText, s: int, e: int, entity: str, score: float, source: str, why: str) -> Span:
    while s < e and nt.text[s] in " ,":
        s += 1
    while e > s and nt.text[e - 1] in " ,." and not re.search(r"(?:Inc|Co|Corp|Ltd|Jr|Sr|St|Bros|L\.L\.C|P\.C)\.$",
                                                                 nt.text[s:e]):
        e -= 1
    os_, oe = nt.to_original(s, e)
    return Span(os_, oe, entity, score, source, nt.original[os_:oe], why)


def find_indirect(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for m in _PLACE_AT_STREET.finditer(t):
        if re.match(rf"(?i)an?\s+(?:{GENERIC_PLACES})\b", m.group()):
            continue  # "a clinic on Northside Drive" — any clinic on that road, not a particular one
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.85, "quasi:place_at_street",
                  "a specific business or place on a named street can identify the people there")
    for m in _NUMBERED_STORE.finditer(t):
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.65, "quasi:numbered_store", "a specific numbered store location")
    for m in _SLASH_X.finditer(t):
        a = m.group()
        if not (re.search(r"(?i)\b(?:blvd|st|ave|rd|dr|ln|hwy|street|avenue|road|drive|boulevard|lane|highway|intersection|"
                          r"wb|eb|nb|sb)\b", a)):
            continue  # "and/or", "his/her" — only street-like pairs
        if all(w.lower() in _GENERIC_ROAD_WORDS for w in re.findall(r"[A-Za-z]+", a)):
            continue  # "Street/Highway", "Main/Proper Lane" — form categories
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.8, "quasi:intersection", "a named intersection pinpoints a location")
    for m in _INTERSECTION_RX.finditer(t):
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.8, "quasi:intersection",
                  "a named intersection pinpoints a location")
    for m in _LIVES_ON.finditer(t):
        yield _mk(nt, *m.span(1), "INDIRECT_LOCATION", 0.75, "quasi:lives_on_street",
                  "street of residence narrows a person to a few households")
    for m in _NAMED_VENUE.finditer(t):
        name = m.group()
        first = name.split()[1] if name.lower().startswith("the ") and len(name.split()) > 1 else name.split()[0]
        sb = re.search(r"^.*[a-z0-9]\.\s+(?=[A-Z])", name)
        if sb and not re.search(r"(?:\b[A-Z]|St|Dr|Mt|Ft|Co|Inc|Jr|Sr)\.\s+$", name[:sb.end()]):
            continue  # "Part-time. I'm the church" — two sentences, not one name
        words = re.findall(r"[A-Za-z0-9'’.&-]+", name)
        proper_words = [w.lower().strip(".") for w in words[:-1] if w.lower() != "the"]
        if not proper_words or all(w in _GENERIC_VENUE_WORDS or re.fullmatch(VENUE_NOUNS, w, re.I) for w in proper_words):
            continue
        if re.search(r"\d", first) or _RYAN_WHITE_RX.search(name):
            continue  # "Q4 grill", "Ryan White Clinic" (a federal program)
        line = t[t.rfind("\n", 0, m.start()) + 1:(t.find("\n", m.end()) + 1 or len(t) + 1) - 1]
        if len(first.strip(".")) <= 5 and first.isupper() and len(proper_words) <= 1 and not words[-1].isupper() \
                and re.search(r"[a-z]{3}", line):
            continue  # "ID Clinic", "CODAC clinic", "the RMTD garage" — an agency acronym, not a place name
        if re.match(r"(?i)(?:the\s+)?(?:police|fire|sheriff|state|county|city|federal|united|memorial|"
                    r"general|regional|university|community|medical)\b", name):
            continue
        if re.match(r"\s+(?:Mutual|Insurance|Bureau|Credit|Bank)\b", t[m.end():m.end() + 12]):
            continue
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.6, "quasi:named_venue",
                  "a named venue (apartment complex, bar, church, motel…) can identify those connected to it")
    for m in _MERCHANT.finditer(t):
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.75, "quasi:merchant",
                  "card-transaction merchant and city place a person at a specific store")
    for m in _BRAND_ALONE.finditer(t):
        if re.sub(r"^(?i:the)\s+", "", m.group())[:1].islower():
            continue  # "loves", "target", "giant" in running text
        tail = t[m.end():m.end() + 40]
        if re.match(r"\s+(?:on|at|off|near|by|in|across|behind|next|located|just|store|station|parking|in)\b",
                    tail, re.I):
            continue  # covered by the place-at-street pattern above
        if re.match(r"(?i)(?:the\s+)?(?:target|giant|ross|chase|regions|pilot|marathon|shell|subway|sonic|"
                    r"mobil|gap|amazon|mini|ram|express|quality)\b", m.group()) and not \
                re.search(r"(?i)\b(?:store|station|restaurant|gas|shop|worked|works|at\s+the|parking)\b",
                          t[max(0, m.start() - 40):m.end() + 40]):
            continue  # common English words that are also brand names
        if re.fullmatch(r"(?i)bp", m.group().strip()) and re.match(r"\s*[:=]?\s*[\dOl]{2,3}\s*/", tail):
            continue  # a blood pressure
        numbered = bool(re.search(r"#\s*\d|No\.\s*\d|Store\s*\d", m.group()))
        # "the back row of the Meijer lot": a particular spot at the store, not just its name
        spot = bool(re.search(r"(?i)\s(?:lot|parking\s+lot|pumps?|drive-?thru)$", m.group()))
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.65 if numbered else 0.6 if spot else 0.45, "quasi:business",
                  "a specific numbered store location" if numbered else
                  "a named business location — identifying when combined with time or role")
    for m in _UNIT_REF.finditer(t):
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.6, "quasi:unit",
                  "apartment / unit / room number identifies a household")
    for m in _UNIT_SOFT.finditer(t):
        if _RESIDENTIAL_CUE.search(t[max(0, m.start() - 50):m.start()]):
            yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.6, "quasi:unit",
                      "unit / room number identifies a household")
    for m in _ROLE_PHRASE.finditer(t):
        phrase = m.group()
        pm = re.search(r"\s(?:at|of|for|from|in|on)\s+(?:the\s+)?(.+)$", phrase)
        has_place = bool(pm) and not re.match(r"(?i)(?:unit|vehicle|car|bus|truck|record|the|p\.?\s?o\.?\s*box)\b",
                                              pm.group(1))
        if pm and re.match(r"(?i)(?:unit|vehicle|car|bus|truck|p\.?\s?o\.?\s*box)\b", pm.group(1)):
            continue  # "the driver of Unit 2" is a crash-report role, not a person-identifying place
        end = m.end()
        tm = re.match(r"\s+(?:there|here)\b", t[m.end():m.end() + 8])
        if tm:
            has_place = True  # "the manager there" — refers back to a specific place
            end = m.end() + tm.end()
        unique = bool(_UNIQUE.search(t[max(0, m.start() - 20):m.end()])) or \
            bool(re.search(r"(?i)\b(?:only|sole|lone|head|general|night|overnight|graveyard|next-door|upstairs|downstairs|"
                           r"across-the-hall|across-the-street)\b", phrase))
        score = 0.8 if (has_place or unique) else 0.42
        why = "a role tied to a specific place or shift identifies one person" if score > 0.5 else \
            "role description — identifying in combination with place or time"
        yield _mk(nt, m.start(), end, "INDIRECT_ROLE", score, "quasi:role", why)
    for rx, sc, why in ((_SHIFT_ROLE, 0.75, "job and shift at a workplace single out one person"),
                        (_GRADE_TEACHER, 0.65, "a child's specific teacher identifies the class / school"),
                        (_IS_THE_ROLE, 0.55, "a specific position held at a workplace"),
                        (_WORK_WITH, 0.6, "a co-worker identified by role")):
        for m in rx.finditer(t):
            yield _mk(nt, *m.span(), "INDIRECT_ROLE", sc, "quasi:role", why)
    for m in _RELATION_PHRASE.finditer(t):
        phrase = m.group()
        # a bare "her husband" is not identifying on its own — suggestion only; modifiers make it identifying
        # "the children's maternal grandmother", "her grandson's girlfriend" — but not a heading-like "Son's father"
        nested = re.match(rf"(?i)(?:the|her|his|their|my|our|your)\s+(?:{_KIN_OWNER})['’]s\b|ex-(?:wife|husband)['’]s",
                          phrase)
        score = 0.65 if nested or re.search(r"\d{1,2}[ -]?(?:-year-old|year-old|yr-old|y/?o\b)|only|twin|oldest|"
                                            r"youngest|eldest|step|ex-|ex\b|estranged|late|\bnew\b|maternal|paternal|"
                                            r"live-in", phrase, re.I) else 0.4
        yield _mk(nt, *m.span(), "INDIRECT_ROLE", score, "quasi:relationship",
                  "a family relationship to a known party identifies that relative")
    for m in _AGE_AS_CHILD.finditer(t):
        yield _mk(nt, *m.span(), "INDIRECT_ROLE", 0.65, "quasi:relationship", "a child known by age")
    for m in _POSSESSIVE_RELATION.finditer(t):
        if _LEGAL_POSSESSOR.match(m.group(1)) or m.group(1).isupper():
            # "Client's 8-year-old daughter", "Pt's 6 y/o son": an age makes the relative identifiable
            aged = re.search(r"(?i)\d{1,2}[ -]?(?:-year-old|y/?o|yo|yr-old|month-old|mo-old)", m.group())
            yield _mk(nt, *m.span(), "INDIRECT_ROLE", 0.65 if aged else 0.4, "quasi:relationship",
                      "relationship of a party — identifying in combination")
            continue
        strong = re.search(r"(?i)\d{1,2}[ -]?(?:-year-old|y/?o|yo)|only|twin|oldest|youngest|eldest|estranged", m.group())
        yield _mk(nt, *m.span(), "INDIRECT_ROLE", 0.7 if strong else 0.45, "quasi:named_relationship",
                  "relationship to a named person identifies the relative")
    for m in _HR_LETTERHEAD.finditer(t):
        yield _mk(nt, *m.span(1), "EMPLOYER", 0.8, "quasi:employer_letterhead", "employer letterhead")
    for m in _EMPLOYER.finditer(t):
        org = m.group(1)
        if org.lower() in ("the", "a", "home", "night", "day", "least", "most", "times", "first", "all"):
            continue
        if _AGENCY.search(org) and _OFFICIAL_CTX.search(t[max(0, m.start() - 150):m.end() + 80]):
            continue  # an officer's agency is public, not a private employer
        yield _mk(nt, *m.span(1), "EMPLOYER", 0.8, "quasi:employer", "employer name — workplace identifies a person")
    for rx in (_EMPLOYER_MORE, _OCCUPATION_AT, _OWN_BUSINESS, _BOSS_AT, _DBA, _FOR_WORK):
        for m in rx.finditer(t):
            # "Seoul Food ATX. Korean barbecue" stops at the sentence; "St. David's" does not
            org = re.split(r"(?<!\bSt)(?<!\bDr)(?<!\bMt)(?<!\bFt)(?<!\bCo)(?<!\bJr)(?<!\bSr)(?<!\b[A-Z])\.(?=\s)", m.group(1))[0]
            if org.split()[0].lower() in NON_NAME_WORDS_LITE or _AGENCY.search(org) and _OFFICIAL_CTX.search(
                    t[max(0, m.start() - 150):m.end() + 80]):
                continue
            yield _mk(nt, m.start(1), m.start(1) + len(org), "EMPLOYER", 0.78, "quasi:employer",
                      "employer name — workplace identifies a person")
    for m in _CARRIER_KV.finditer(t):
        # a motor carrier on a crash report is the commercial driver's employer (insurance "carrier" is not)
        line_s, line_e = t.rfind("\n", 0, m.start()) + 1, t.find("\n", m.end())
        ctx = t[max(0, line_s - 200):(len(t) if line_e < 0 else line_e) + 120]
        if re.search(r"(?i)usdot|\bdot\s*#|\bmc\s*#|commercial\s+motor\s+vehicle|\bcmv\b|gvwr|tractor|trailer", ctx):
            yield _mk(nt, *m.span(1), "EMPLOYER", 0.85, "kv:employer", "motor carrier operating the commercial vehicle")
    for m in _EMPLOYER_KV.finditer(t):
        from .labels import cut_at_next_label
        raw = cut_at_next_label(m.group(1))
        raw = re.split(r"\s+--\s+|\s\(|;", raw)[0]
        val = raw.strip()
        if not val or val[0].islower():
            continue
        if val and not re.match(r"(?i)(?:n/?a|none|unemployed|retired|self|self-employed|student|disabled)$", val):
            yield _mk(nt, m.start(1), m.start(1) + len(raw.rstrip()), "EMPLOYER", 0.88, "kv:employer",
                      "value of an employer field")
    for m in _PAYROLL.finditer(t):
        yield _mk(nt, *m.span(1), "EMPLOYER", 0.8, "quasi:payroll", "payroll deposit names the employer")
    for m in _SCHOOL_MORE.finditer(t):
        g = next(i for i in (1, 2, 3) if m.group(i))
        if g == 3 and not re.search(r"\s+(?:School|Academy)\b", m.group()) and (
                len(m.group(3).split()) < 2 or re.match(_WEEKDAYS, m.group(3))):
            continue  # "attends Friday prayers" — a one-word name needs "School" after it
        yield _mk(nt, *m.span(g), "SCHOOL", 0.8, "quasi:school", "school a person attends")
    for m in _SCHOOL.finditer(t):
        name = m.group()
        after = t[m.end():m.end() + 30]
        if re.match(r"(?i)(?:the\s+)?(?:international|american|national|royal|european|world)\b", name) and \
                re.match(r"\s+of\s+[A-Z]", after):
            continue  # "International Academy of Life Care Planners" — a professional body
        if re.match(r"(?i)\s*(?:sticker|decal|shirt|t-shirt|hat|cap|jersey|hoodie|flag|fan|game|football|license\s+plate"
                    r"\s+frame|mug|keychain)", after):
            yield _mk(nt, *m.span(), "SCHOOL", 0.45, "quasi:school", "school named on merchandise — shown for review")
            continue
        ctx = _SCHOOL_CTX.search(t[max(0, m.start() - 80):m.end() + 40])
        yield _mk(nt, *m.span(), "SCHOOL", 0.8 if ctx else 0.6, "quasi:school", "school or university attended")
    for m in _VEHICLE.finditer(t):
        v = m.group()
        if not re.search(r"(?:19|20)\d{2}|" + COLORS, v, re.I):
            continue  # a bare make ("Ford") is too generic
        if re.match(r"(?i)^(?:ford|lincoln|ram|mini|international|mercury|saturn|genesis)$", v.strip()):
            continue
        yield _mk(nt, *m.span(), "VEHICLE_DESCRIPTION", 0.75, "quasi:vehicle",
                  "year/colour/make/model description of a person's vehicle")
    for m in _PHYSICAL.finditer(t):
        if re.fullmatch(r"(?i)(?:the\s+)?(?:tattoos|scars|marks|piercings|moles|cane|walker|wheelchair)", m.group().strip()):
            continue  # a section heading / a mobility aid, not a description
        phrase = m.group()
        around = t[max(0, m.start() - 15):m.end() + 15]
        if re.search(r"(?:SCARS|TATTOOS|MARKS)\s*[/:]", t[m.start():m.end() + 2]):
            continue  # the "SCARS/MARKS/TATTOOS:" field label itself
        if re.search(r"(?i)\b(?:scar\s+tissue|scarring\s+of\s+the\s+(?:l\d|c\d|t\d|disc|lung|liver)|post-?op|incision|"
                     r"walker\s+boot|scar\s+(?:is|was)\s+healing)\b", around) and not re.search(r"(?i)tattoo|birthmark", phrase):
            continue  # clinical findings, handled as medical content instead
        ps, pe = m.span()
        lead = re.match(r"(?i)(?:(?:she|he|they|it|who|has|had|have|is|was|were|with|and|also|of|on|in|including)\s+)+",
                        t[ps:pe])
        if lead and lead.end() < pe - ps:
            ps += lead.end()
        yield _mk(nt, ps, pe, "PHYSICAL_DESCRIPTOR", 0.75, "quasi:physical",
                  "distinguishing physical feature identifies a person")
    for m in _GAIT.finditer(t):
        yield _mk(nt, *m.span(), "PHYSICAL_DESCRIPTOR", 0.7, "quasi:physical", "a distinctive way of walking")
    for m in _SMT_ROW.finditer(t):
        if not re.search(r"(?i)\b(?:none|n/a|unk)\b", m.group(1)):
            yield _mk(nt, *m.span(1), "PHYSICAL_DESCRIPTOR", 0.85, "quasi:smt", "scars / marks / tattoos record")
    for m in _MARK_BULLET.finditer(t):
        if re.search(r"(?i)\b(?:incision|post-?op|surgical\s+site|dressing|sutures?|staples)\b", m.group(1)):
            continue
        yield _mk(nt, *m.span(1), "PHYSICAL_DESCRIPTOR", 0.75, "quasi:physical", "distinguishing mark in an identification list")
    for m in _SMT.finditer(t):
        if re.search(r"(?i)none|n/a", m.group()[-8:]):
            continue
        yield _mk(nt, *m.span(), "PHYSICAL_DESCRIPTOR", 0.85, "quasi:smt", "scars / marks / tattoos record")
    for m in _HEIGHT_WEIGHT.finditer(t):
        if re.search(r"(?i)lbs|pounds|\"|inches", m.group()):
            yield _mk(nt, *m.span(), "PHYSICAL_DESCRIPTOR", 0.45, "quasi:height_weight", "height/weight description")


_LEGAL_POSSESSOR = re.compile(r"(?i)^(?:respondent|petitioner|applicant|plaintiff|defendant|claimant|pt|patient|"
                              r"client|victim|suspect|decedent|state|department|county|city|court)\b")
# law-enforcement / prosecuting agencies: public when named as an *official's* employer
_AGENCY = re.compile(r"(?i)\b(?:police|sheriff'?s?|district\s+attorney|attorney\s+general|marshal'?s?|constable|"
                     r"state\s+department|records\s+&\s+quality|quality\s+assurance)\b")
_OFFICIAL_CTX = re.compile(r"(?i)\b(?:officer|deputy|badge|tcole|peace\s+officer|affiant|detective|trooper|sergeant|"
                           r"assigned\s+to|sworn|commissioned|prepared\s+for|transcribed\s+by)\b")


# ---- more place shapes ---------------------------------------------------------------------------
_PARK_ACTIVITY = re.compile(
    r"(?i:game|games|practice|team|league|tournament|playground|picnic|walk|walks|jog|run|t-ball|tee-ball|soccer|"
    r"baseball|softball|football|basketball|tennis|swim|swimming|party|birthday|coaching|coach|played|plays|"
    r"dog\s+park|festival)[^.\n]{0,40}?\b(?i:at)\s+((?:[A-Z][a-z]+\s+){1,2}Park)\b")
_BOUND = re.compile(rf"\b(?i:north|south|east|west)bound\s+(?:(?i:on|the)\s+)?(?:{STREET_REF}|(?:I-\d+|US\s*\d+|"
                    rf"SH\s*\d+|FM\s*\d+|Loop\s*\d+|(?!{_WEEKDAYS})[A-Z][A-Za-z0-9-]{{2,}})(?:\s+[A-Z][A-Za-z0-9-]+)?)")
_VILLAS = re.compile(rf"(?:\b(?i:the)\s+)?(?:Villas|Lofts|Residences|Commons|Gardens|Estates|Townhomes|Flats|Reserve|"
                     rf"Landing|Crossing|Apartments|Suites)\s+(?i:at|of|on)\s+{_PROPER}")
_BUILDING_REF = re.compile(rf"(?<![A-Za-z])((?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)?)\s*,\s*(?i:building|bldg\.?)\s*#?\s*[A-Z0-9]{{1,4}}\b")
_UNIT_SPOKEN = re.compile(r"\b(?:in|it's|it’s|is|at)\s+(\d{1,4}[A-Z])\b(?![\w-])")
_BRAND_FACILITY = re.compile(rf"(?<![A-Za-z])(?:(?i:the)[ \t]+)?(?i:{_BRAND_RX})\s+(?:DC|D\.C\.|(?i:distribution\s+center|fulfillment\s+center|"
                             rf"warehouse|depot|plant|yard|terminal))\b(?:\s+(?:in\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)?")
_BRAND_IN_CITY = re.compile(rf"(?:\b(?i:a|the|that)[ \t]+)?(?<![A-Za-z])(?i:{_BRAND_RX})(?:\s*#\s*\d+)?\s+in\s+"
                            rf"(?!{_WEEKDAYS})[A-Z][a-z]{{1,}}(?:\s+[A-Z][a-z]{{2,}})?")
# a named place with no venue word, pinned to a street: "the Rusty Anchor on Ruston Way", "at Kozak's Collision on
# Broadway" — after "the" or a locative preposition, so a person's name is not taken for a place
_NAMED_ON_STREET = re.compile(
    rf"(?:\b(?P<the>(?i:the))\s+|\b(?i:at|inside|outside|behind|near|into|toward|towards|past|across\s+from|in\s+front\s+of|"
    rf"(?:bay|lot|back|rear|front|side|basement|dock|door|kitchen|office|room|garage|yard|porch|steps)\s+of)\s+)"
    rf"(?P<p>(?!{_WEEKDAYS}\b)[A-Z][A-Za-z0-9'’&.-]+(?:[ \t]+(?:[A-Z][A-Za-z0-9'’&.-]+|&|of|de|la)){{0,3}})"
    rf"(?:\s+(?:crib|place|house|spot|shop|garage|trailer|apartment|apt))?\s+(?i:on|off(?:\s+of)?|just\s+off|at\s+the\s+corner\s+of|on\s+the\s+corner\s+of)\s+(?:(?i:the)\s+)?"
    rf"(?:{_INTERSECTION}|{_STREETISH})")
_NOT_PLACE_PROPER = re.compile(
    r"(?i)^(?:court|state|plaintiff|defendant|department|dept|city|county|police|officer|unit|vehicle|veh|witness|victim|"
    r"suspect|respondent|petitioner|patient|pt|claimant|company|agency|board|government|united|federal|national|employer|"
    r"employee|insured|member|customer|client|lender|borrower|debtor|creditor|trustee|decedent|executor|caller|"
    r"complainant|applicant|tenant|landlord|owner|driver|mr|mrs|ms|dr|i|we|he|she|they|it|my|our|his|her|their|"
    r"am|pm|a\.m|p\.m|noon|midnight|night|approximately|approx|about|exit|mile|block|lane)\b")
# "the old Archuleta place", "the Henderson farm"
_FAMILY_PLACE = re.compile(r"\b(?i:the)\s+(?:(?i:old)\s+)?(?!(?:Court|State|Plaintiff|Defendant|Estate|Company|County|City)\b)"
                           r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+(?i:place|farm|ranch|homestead)\b")
# a recurring group / service someone attends at a named place: "my Thursday night Celebrate Recovery group at
# Southland Christian", "AA meetings at First Methodist"
_GROUP_AT = re.compile(r"(?:\b(?i:the|a|my|her|his|their|our)[ \t\n]+(?:[\w.:'’-]+[ \t\n]+){0,4}?)?"
                       r"\b(?i:group|meetings?|services?|mass|bible\s+study|class(?:es)?|lessons|program|practice|"
                       r"league|rehearsals?|choir|fish\s+fry|circle|bingo|potluck|club|study)[ \t]+(?:at|in)[ \t]+"
                       r"(?:(?i:the)[ \t]+)?(?:(?i:basement|parish\s+hall|fellowship\s+hall|gym|back\s+room)\s+of\s+)?"
                       rf"(?P<p>(?!{_WEEKDAYS}\b)[A-ZÀ-Ý][\w'’.-]+(?:[ \t]+(?:[A-ZÀ-Ý][\w'’.-]+|of|the|de|la)){{0,3}})"
                       r"(?:[ \t]+(?i:senior\s+center|community\s+center|rec(?:reation)?\s+center|center|hall|church|"
                       r"chapel|library|gym|park))?")
# a branch / office named by its spot: "the Greenhaven branch by my school", "Channelside branch two blocks from …"
_BRANCH_NEAR = re.compile(
    r"\b(?:(?i:the)\s+)?(?:[A-Z][A-Za-z0-9'’.-]+\s+){1,3}(?i:branch|location|office|store)\s+"
    r"(?=(?i:by|near|next\s+to|across\s+(?:the\s+street\s+)?from|behind|around\s+the\s+corner\s+from|"
    r"(?:\w+\s+)?(?:blocks?|miles?|doors?)\s+(?:from|down\s+from|past))\b)")
# "Branch: Dearborn - Michigan Ave #0221" (a branch named by its street)
# mail held for someone without an address: "c/o General Delivery, Bayou La Batre post office"
_GENERAL_DELIVERY = re.compile(r"\b(?i:general\s+delivery)\b[ \t]*,?[ \t]*(?:[A-Z][\w'’.-]*[ \t]+){0,4}(?:(?i:post\s+office))?")
_BRANCH_KV = re.compile(rf"(?im)^[ \t]*(?:[\w ]{{0,30}}\s{{2,}})?branch(?:\s+(?:name|location))?[ \t]*:[ \t]*([^\n]{{3,60}}?)(?=\s{{2,}}|\n|$)")


def find_more_places(nt: NormText) -> Iterator[Span]:
    t = nt.text
    for m in _PARK_ACTIVITY.finditer(t):
        yield _mk(nt, *m.span(1), "INDIRECT_LOCATION", 0.65, "quasi:park", "a park where a person regularly goes")
    for m in _BOUND.finditer(t):
        # in a crash report's unit narrative ("Unit 1 was traveling northbound on Oak Street") the road is the
        # public crash location: shown for review; elsewhere (medical notes) it places the patient
        crash = re.search(r"\bUnit\s+\d\b|\bV\d\b|\bVeh(?:icle)?\s*#?\s*\d\b", t[max(0, m.start() - 160):m.start()])
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.45 if crash else 0.7, "quasi:travel_location",
                  "where a vehicle was travelling")
    for m in _VILLAS.finditer(t):
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.7, "quasi:named_venue", "a named residential complex")
    for m in _BUILDING_REF.finditer(t):
        if m.group(1).lower() in ("the", "a", "this", "that", "same", "main", "office", "admin"):
            continue
        sp = _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.65, "quasi:named_venue", "a named complex and building")
        sp.meta["core"] = m.group(1)  # "Pinecrest" also identifies "Is that the Pinecrest?"
        yield sp
    for m in _UNIT_SPOKEN.finditer(t):
        if _RESIDENTIAL_CUE.search(t[max(0, m.start() - 120):m.end() + 60]) or \
                re.search(r"(?i)next\s+door|upstairs|downstairs|apartment|apt\b|unit\b", t[max(0, m.start() - 120):m.end() + 60]):
            yield _mk(nt, *m.span(1), "INDIRECT_LOCATION", 0.6, "quasi:unit", "apartment / unit number")
    for m in _BRAND_FACILITY.finditer(t):
        if re.sub(r"^(?i:the)\s+", "", m.group())[:1].islower():
            continue
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.7, "quasi:business", "a specific company facility")
    for m in _BRAND_IN_CITY.finditer(t):
        if re.sub(r"^(?i:a|the|that)\s+", "", m.group())[:1].islower():
            continue
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.7, "quasi:business", "a store in a named town")
    for m in _NAMED_ON_STREET.finditer(t):
        p = m.group("p")
        if _NOT_PLACE_PROPER.match(p) or re.fullmatch(STREET_REF, p) or p.isupper() and len(p) <= 3:
            continue
        s = m.start() if m.group("the") else m.start("p")
        yield _mk(nt, s, m.end(), "INDIRECT_LOCATION", 0.8, "quasi:place_at_street",
                  "a named business or place on a named street can identify the people there")
    for m in _FAMILY_PLACE.finditer(t):
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.7, "quasi:family_place", "a homestead known by a family name")
    for m in _GROUP_AT.finditer(t):
        p = m.group("p")
        if _NOT_PLACE_PROPER.match(p) or re.match(r"(?i)(?:zoom|teams|person|home|school|town)\b", p):
            continue
        yield _mk(nt, m.start(), m.end(), "INDIRECT_LOCATION", 0.6, "quasi:group_place",
                  "a place someone goes regularly for a group or service")
    for m in _BRANCH_NEAR.finditer(t):
        e = m.end() + len(re.match(r"[^,.;:\n()]{3,50}", t[m.end():]).group() if re.match(r"[^,.;:\n()]{3,50}", t[m.end():])
                          else "")
        yield _mk(nt, m.start(), e, "INDIRECT_LOCATION", 0.7, "quasi:branch", "a branch / office pinned to a landmark")
    for m in _GENERAL_DELIVERY.finditer(t):
        yield _mk(nt, *m.span(), "INDIRECT_LOCATION", 0.75, "quasi:general_delivery",
                  "general-delivery mail pins a person without an address to one post office")
    for m in _BRANCH_KV.finditer(t):
        if re.search(rf"\b(?:{SUFFIXES})\b\.?|\b(?:ST|AVE|RD|BLVD|DR|HWY)\b", m.group(1)):
            yield _mk(nt, *m.span(1), "INDIRECT_LOCATION", 0.7, "kv:branch", "a branch named by its street")


# ---- growing a place into its full location phrase ---------------------------------------------------
_GROW_TARGET = (rf"(?:(?:(?:NE|NW|SE|SW|(?i:north|south|east|west|northeast|northwest|southeast|southwest))\s+)?"
                rf"(?i:corner\s+of)\s+(?:{_INTERSECTION}|(?!{_WEEKDAYS}\b)[A-Z][a-z]+\s*(?:and|&|/)\s*[A-Z][a-z]+(?![\w'’]))|"
                rf"{STREET_REF}|(?:(?i:north|south)?(?i:east|west)?|(?i:north|south)|NE|NW|SE|SW)\s*(?i:corner)|"
                rf"(?:(?i:old|new|former|abandoned|closed|big|little)\s+)?"
                rf"(?!{_WEEKDAYS}\b)(?:{_PROPER_ANY})(?:\s+(?i:{VENUE_NOUNS}|lot|parking\s+lot|exit|ramp|corner|station|"
                rf"store|restaurant|brewery|park|pool|field|campus|building|plant|warehouse|interchange|overpass))?|"
                rf"(?i:my|his|her|their|our)\s+(?:[a-z-]+['’]s\s+)?(?i:office|school|work|job|house|home|apartment|building|"
                rf"church|gym|store|shop)\b|"
                rf"(?i:the)\s+(?:[a-z]+\s+)?(?i:{GENERIC_PLACES}|restaurant|brewery|corner|exit|pool|gym|mailboxes|"
                rf"laundry\s+room|elevators?|stairs|stairwell|dumpsters?|playground|interstate|highway|tracks|"
                rf"railroad\s+tracks|river|creek|lake|quarry|fence|gate))")
_GROW_RIGHT = re.compile(
    rf"[ \t]*(?:\n[ \t]*)?,?[ \t]*(?i:on|at|off(?:\s+of)?|by|near|across\s+(?:the\s+street\s+)?from|next\s+to|behind|"
    rf"beside|in\s+front\s+of|around\s+the\s+corner\s+from|down\s+the\s+(?:street|road|block)\s+from|"
    rf"(?:\w+\s+)?(?:blocks?|miles?|doors?)\s+(?:from|down\s+from|past|north\s+of|south\s+of|east\s+of|west\s+of)|in|"
    rf"just\s+(?:past|off|before|after|north\s+of|south\s+of|east\s+of|west\s+of)|past|outside(?:\s+of)?)"
    rf"(?:[ \t]+(?:\n[ \t]*)?|[ \t]*\n[ \t]*)(?:(?i:the)[ \t]+(?:\n[ \t]*)?)?(?:{_GROW_TARGET})")
_GROW_UNIT = re.compile(
    r"(?:[ \t]*\((?i:job|site|store|project|unit|lot)\s*#?\s*[A-Za-z0-9-]{1,15}\))?(?:[ \t]*,[ \t]*(?:(?i:building|bldg\.?|"
    r"unit|floor|suite|ste\.?|apt\.?|apartment|room|rm\.?|lot|pump|bay|dock|gate|door|section|row|space|booth|table|"
    r"stall|site|pad)\s*#?\s*[A-Z0-9][A-Z0-9-]{0,5}\b|\d{1,2}(?:st|nd|rd|th)\s+floor(?:\s+(?i:north|south|east|west|rear|"
    r"front))?(?:\s+(?i:balcony|stairwell|hallway|lobby|landing|breezeway|patio|deck|office|bathroom|kitchen))?|"
    r"(?i:upstairs|downstairs)(?:\s+(?i:rear|front|left|right))?|(?i:top|bottom|ground|basement)\s+(?i:floor|unit)"
    r"(?:\s+(?i:on\s+the\s+(?:end|left|right|corner)))?|(?i:on\s+the\s+end|end\s+unit|corner\s+unit)|"
    r"(?i:north|south|east|west)bound(?:\s+[a-z]+){0,2}?\s+(?i:lane|shoulder|ramp)))+")
_GROW_PAREN_CITY = re.compile(r"[ \t]*\(([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\)")
# "…, blue roof", "…, the one with the chain-link fence"
_GROW_FEATURE = re.compile(r"[ \t]*,[ \t]*(?:(?i:the\s+one\s+with\s+(?:the|a)\s+)?(?:[a-z-]+\s+)?)?(?i:roof|door|fence|gate|"
                           r"awning|trim|siding|shutters|mailbox|porch|garage\s+door|carport|boat\s+in\s+the\s+yard)\b"
                           r"(?<=\w)")
# "the Speedway at Tates Creek and Gainesway": the cross street of an "at" location
_GROW_CROSS = re.compile(rf"[ \t]+(?:and|&)[ \t]+(?:{STREET_REF}|[A-Z][a-z]+(?![\w'’]))")
_GROW_TAIL_NOUN = re.compile(r"[ \t]+(?:(?i:pool|gym|field|courts?|playground|parking\s+lot|lobby|entrance|pumps?|patio|"
                             r"loading\s+dock|exit|ramp|on-ramp|off-ramp|interchange|overpass|underpass)|(?:NE|NW|SE|SW|"
                             r"(?i:north|south)(?i:east|west)?|(?i:east|west))[ \t]+(?i:corner|side|end|lot))\b")
_GROW_LEFT = re.compile(
    r"(?:(?i:pump|bay|dock|gate|lane|booth|table|seat|space|lot|row|stall|aisle|slip|pew|berth|bed|site|pad|locker|plot|"
    r"bunk)\s*#?\s*\d{1,3}\s+(?i:of|at)\s+(?:(?i:the)\s+)?"
    r"|(?<![A-Za-z'’])(?:(?i:the)\s+)?(?i:back\s+row|front\s+row|lot|parking\s+lot|loading\s+dock|back\s+door|side\s+door|"
    r"front\s+door|back|front|rear|side|dumpsters?|drive-?thru|bathroom|restroom|alley|entrance|basement|bus\s+stop|"
    r"bus\s+shelter|break\s+room|stockroom|kitchen)\s+(?i:of|behind|outside|at|in\s+front\s+of|beside|next\s+to)\s+"
    r"(?:(?i:the)\s+)?"
    r"|(?<![A-Za-z'’])(?:(?i:my|her|his|their|our)\s+(?:[a-z-]+['’]s\s+)?|[A-Z][a-z]+['’]s\s+)(?:[a-z-]+\s+){0,2}"
    r"(?i:home|house|apartment|condo|place|trailer|room|unit|office|shop|garage)\s+(?i:at|in|on|behind)\s+(?:(?i:the)\s+)?"
    r"|(?<![A-Za-z'’])(?:(?i:the|a|an|his|her|their|my|our)\s+)?(?:[A-Za-z-]+\s+){0,4}(?i:program|class|classes|camp|"
    r"group|meetings?|services?|lessons?)\s+(?i:at|in)\s+(?:(?i:the)\s+)?"
    r"|(?i:a|an|the)\s+(?:[a-z-]+\s+){0,2}(?i:home|house|trailer|apartment|place|room|unit|bar|lot|store|shop|restaurant|"
    r"office|clinic|practice|salon|studio|suite|booth|kiosk|stand|branch|"
    r"icehouse|cantina|club|warehouse|yard|stand)\s+(?:(?i:at|in|on)\s+the\s+(?i:back|front|end|corner|rear|edge)\s+of\s+"
    r"|(?i:at|in|on|of|behind)\s+)(?:(?i:the)\s+)?)$")
_GROW_MAX = 110


_GROW_WRAPPED_STREET = re.compile(r"[ \t]*\n[ \t]*(?:the\s+)?[A-Z][a-z]+(?:[ \t]+(?:[A-Z][a-z]+|Rd|St|Ave|Blvd|Dr|Hwy|Pkwy|"
                                  r"Road|Street|Avenue|Boulevard|Drive|Highway|Parkway|Lane|Ln))*")
_GROW_ADDRESS_CITY = re.compile(r",[ \t]*([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,2})(?=[ \t]*(?:[.;\n]|,[ \t]*[A-Z]{2}\b|$))")
NON_PLACE_WORDS = {"he", "she", "they", "we", "i", "and", "but", "then", "which", "who", "where", "when", "yes", "no",
                   "okay", "ok", "correct", "right", "sir", "ma'am", "please", "thanks", "thank", "the", "that", "this"}


def grow_locations(text: str, spans: list[Span]) -> None:
    """Extend confident place spans over the location phrase around them ("pump 6 of the Shell station on the
    northeast corner", "the bar on Cincinnati Ave across from the UTEP lot", "…, Building C, 3rd floor east
    balcony") so the whole description is redacted, then join places that touch."""
    places = sorted((sp for sp in spans if sp.entity == "INDIRECT_LOCATION" and sp.score >= 0.5), key=lambda s: s.start)
    for sp in places:
        start0, end0 = sp.start, sp.end
        if sp.text[:1].islower():
            # "the Shady Acres park": a generic place word takes the proper name in front of it
            pm = re.search(r"(?<![A-Za-z'’])((?:[A-Z][A-Za-z'’-]+[ \t]+){1,3})$", text[max(0, sp.start - 50):sp.start])
            if pm and pm.group(1).split()[0].lower() not in ("the", "a", "an", "i", "my", "our"):
                sp.start -= len(pm.group(1))
        for _ in range(4):
            rest = text[sp.end:sp.end + 120]
            m = _GROW_UNIT.match(rest) or _GROW_PAREN_CITY.match(rest) or _GROW_TAIL_NOUN.match(rest) or \
                _GROW_RIGHT.match(rest) or _GROW_FEATURE.match(rest) or \
                (re.search(r"\b(?i:at)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?$", text[sp.start:sp.end]) and _GROW_CROSS.match(rest))
            if not m or m.end() == 0 or sp.end + m.end() - start0 > _GROW_MAX + (end0 - start0):
                break
            sp.end += len(m.group().rstrip(" \t\n.,;"))
        lm = _GROW_LEFT.search(text[max(0, sp.start - 80):sp.start])
        if lm and lm.group().strip():
            sp.start -= len(lm.group()) - (len(lm.group()) - len(lm.group().lstrip()))
        if (sp.start, sp.end) != (start0, end0):
            sp.text = text[sp.start:sp.end]
            sp.meta["grown"] = True
    for sp in places:
        # an intersection wrapped onto the next line: "the CVS at North Decatur Rd and\n       Clairmont"
        if re.search(r"(?:\band|&)[ \t]*$", sp.text):
            m = _GROW_WRAPPED_STREET.match(text, sp.end)
            if m:
                sp.end = m.end()
                sp.text = text[sp.start:sp.end]
    for sp in spans:
        if sp.score < 0.5:
            continue
        if sp.entity == "ADDRESS":
            # "116 Kearny Avenue, second floor, Perth Amboy." — the city after a unit / floor
            m = _GROW_ADDRESS_CITY.match(text, sp.end)
            if m and m.group(1).split()[0].lower() not in NON_PLACE_WORDS:
                sp.end = m.end(1)
                sp.text = text[sp.start:sp.end]
        elif sp.entity in ("INDIRECT_LOCATION", "EMPLOYER", "INDIRECT_ROLE", "ORGANIZATION", "SCHOOL") and \
                sp.text.count("(") > sp.text.count(")"):
            # "the Hamburg urgent care (Baptist Health Urgent Care -- Hamburg, 2365 …)": finish the name in brackets
            m = re.compile(r"[^(),;\n]{1,60}?(?=\s*[,)]|\s*$)").match(text, sp.end)
            if m and m.group().strip():
                sp.end += len(m.group().rstrip())
                sp.text = text[sp.start:sp.end]
    # join places separated only by ", " / " (" / " -- "
    places.sort(key=lambda s: s.start)
    for a, b in zip(places, places[1:]):
        if 0 <= b.start - a.end <= 4 and re.fullmatch(r"[ \t]*[,(]?[ \t]*", text[a.end:b.start]) and b.start > a.start:
            a.end = max(a.end, b.end)
            a.text = text[a.start:a.end]


def combine_risk(text: str, spans: list[Span]) -> None:
    """Raise indirect-identifier scores when several co-occur in one sentence (in place)."""
    indirect = [s for s in spans if s.entity in ("INDIRECT_LOCATION", "INDIRECT_ROLE", "EMPLOYER", "SCHOOL",
                                                 "VEHICLE_DESCRIPTION", "PHYSICAL_DESCRIPTOR", "DEMOGRAPHIC",
                                                 "AGE")]
    if len(indirect) < 2:
        return
    def sentence_of(sp: Span) -> tuple[int, int]:
        a = max(text.rfind(". ", 0, sp.start), text.rfind("\n\n", 0, sp.start), text.rfind("? ", 0, sp.start)) + 1
        b_candidates = [x for x in (text.find(". ", sp.end), text.find("\n\n", sp.end), text.find("? ", sp.end))
                        if x >= 0]
        return a, (min(b_candidates) if b_candidates else len(text))
    groups: dict[tuple[int, int], list[Span]] = {}
    for sp in indirect:
        groups.setdefault(sentence_of(sp), []).append(sp)
    for group in groups.values():
        kinds = {s.entity for s in group if s.score >= 0.5}
        if len(kinds) >= 2:
            for s in group:
                if s.score < 0.5:
                    continue  # a generic "her son" stays a suggestion even next to other details
                s.score = min(0.95, s.score + 0.15 * (len(kinds) - 1))
                if "combination" not in s.explanation:
                    s.explanation += f" — combined with {', '.join(sorted(kinds - {s.entity})).lower()} " \
                                     f"in the same sentence (combination re-identification risk)"
