"""Checksum and structural validators for structured identifiers.

Each validator takes the raw matched string (separators allowed) and returns True when the value
is structurally valid. Validators raise confidence; they are never the only gate for a redaction
when strong context is present, because a typo'd SSN is still an SSN.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")
_NON_DIGIT = re.compile(r"\D")


def digits(s: str) -> str:
    return _NON_DIGIT.sub("", s)


def alnum(s: str) -> str:
    return _NON_ALNUM.sub("", s).upper()


# ---------------------------------------------------------------------------------------------
# Luhn family
# ---------------------------------------------------------------------------------------------

def luhn_ok(number: str) -> bool:
    d = digits(number)
    if not d:
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = ord(ch) - 48
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def luhn_check_digit(partial: str) -> int:
    """Check digit that makes ``partial + digit`` pass Luhn."""
    for c in range(10):
        if luhn_ok(partial + str(c)):
            return c
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------------------------
# Payment cards
# ---------------------------------------------------------------------------------------------

def card_brand(number: str) -> str | None:
    d = digits(number)
    n = len(d)
    if n < 12 or n > 19:
        return None
    p2, p3, p4, p6 = int(d[:2]), int(d[:3]), int(d[:4]), int(d[:6])
    if d[0] == "4" and n in (13, 16, 19):
        return "visa"
    if (51 <= p2 <= 55 or 2221 <= p4 <= 2720) and n == 16:
        return "mastercard"
    if p2 in (34, 37) and n == 15:
        return "amex"
    if (p4 == 6011 or p2 == 65 or 644 <= p3 <= 649 or 622126 <= p6 <= 622925) and 16 <= n <= 19:
        return "discover"
    if 3528 <= p4 <= 3589 and 16 <= n <= 19:
        return "jcb"
    if (300 <= p3 <= 305 or p2 in (36, 38, 39) or p4 == 3095) and 14 <= n <= 19:
        return "diners"
    if p2 == 62 and 16 <= n <= 19:
        return "unionpay"
    if (p4 in (5018, 5020, 5038, 5893, 6304, 6759, 6761, 6762, 6763) or p2 == 67) and 12 <= n <= 19:
        return "maestro"
    if 2200 <= p4 <= 2204 and n == 16:
        return "mir"
    return None


def credit_card_ok(number: str) -> bool:
    d = digits(number)
    if len(set(d)) <= 2:  # 4444 4444 4444 4444-style fillers
        return False
    return card_brand(d) is not None and luhn_ok(d)


# ---------------------------------------------------------------------------------------------
# US government identifiers
# ---------------------------------------------------------------------------------------------

def ssn_ok(value: str) -> bool:
    """SSA structural rules (post-2011 randomisation): area 001-899 except 666, group 01-99,
    serial 0001-9999. Excludes the well-known advertising/test numbers."""
    d = digits(value)
    if len(d) != 9:
        return False
    area, group, serial = int(d[:3]), int(d[3:5]), int(d[5:])
    if area == 0 or area == 666 or area >= 900:
        return False
    if group == 0 or serial == 0:
        return False
    if d in {"078051120", "219099999", "123456789", "111111111", "333333333", "987654320"}:
        return False
    if len(set(d)) == 1:
        return False
    return True


def ssn_plausible(value: str) -> bool:
    """Weaker than :func:`ssn_ok`: right shape and not obviously filler. Used when context says
    SSN, because example/typo SSNs in real documents still have to be redacted."""
    d = digits(value)
    return len(d) == 9 and len(set(d)) > 1


def itin_ok(value: str) -> bool:
    d = digits(value)
    if len(d) != 9 or d[0] != "9":
        return False
    g = int(d[3:5])
    return 50 <= g <= 65 or 70 <= g <= 88 or 90 <= g <= 92 or 94 <= g <= 99


_EIN_PREFIXES = {
    1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14, 15, 16, 20, 21, 22, 23, 24, 25, 26, 27, 30, 31, 32, 33, 34, 35, 36,
    37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64,
    65, 66, 67, 68, 71, 72, 73, 74, 75, 76, 77, 80, 81, 82, 83, 84, 85, 86, 87, 88, 90, 91, 92, 93, 94, 95, 98, 99,
}


def ein_ok(value: str) -> bool:
    d = digits(value)
    return len(d) == 9 and int(d[:2]) in _EIN_PREFIXES and len(set(d)) > 1


def aba_routing_ok(value: str) -> bool:
    d = digits(value)
    if len(d) != 9:
        return False
    prefix = int(d[:2])
    if not (0 <= prefix <= 12 or 21 <= prefix <= 32 or 61 <= prefix <= 72 or prefix == 80):
        return False
    w = [int(c) for c in d]
    chk = 3 * (w[0] + w[3] + w[6]) + 7 * (w[1] + w[4] + w[7]) + (w[2] + w[5] + w[8])
    return chk % 10 == 0 and d != "000000000"


def npi_ok(value: str) -> bool:
    d = digits(value)
    if len(d) != 10 or d[0] not in "12":
        return False
    return luhn_ok("80840" + d)


_DEA_FIRST = set("ABCDEFGHJKLMPRSTUX")


def dea_ok(value: str) -> bool:
    v = alnum(value)
    if len(v) != 9 or v[0] not in _DEA_FIRST or not (v[1].isalpha() or v[1] == "9") or not v[2:].isdigit():
        return False
    n = [int(c) for c in v[2:]]
    chk = (n[0] + n[2] + n[4]) + 2 * (n[1] + n[3] + n[5])
    return chk % 10 == n[6]


_MBI_ALPHA = set("ACDEFGHJKMNPQRTUVWXY")  # excludes S, L, O, I, B, Z


def mbi_ok(value: str) -> bool:
    """Medicare Beneficiary Identifier: C A AN N A AN N A A N N."""
    v = alnum(value)
    if len(v) != 11:
        return False
    a = lambda c: c in _MBI_ALPHA  # noqa: E731
    n = str.isdigit
    an = lambda c: a(c) or c.isdigit()  # noqa: E731
    pattern = [lambda c: c in "123456789", a, an, n, a, an, n, a, a, n, n]
    return all(f(c) for f, c in zip(pattern, v))


# ---------------------------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------------------------

_VIN_MAP = {**{str(i): i for i in range(10)},
            **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))), "P": 7, "R": 9,
            **dict(zip("STUVWXYZ", range(2, 10)))}
_VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def vin_shape_ok(value: str) -> bool:
    v = alnum(value)
    return bool(VIN_RE.match(v)) and sum(c.isdigit() for c in v) >= 5 and sum(c.isalpha() for c in v) >= 2


def vin_checkdigit_ok(value: str) -> bool:
    v = alnum(value)
    if not vin_shape_ok(v):
        return False
    total = sum(_VIN_MAP[c] * w for c, w in zip(v, _VIN_WEIGHTS))
    r = total % 11
    return v[8] == ("X" if r == 10 else str(r))


# ---------------------------------------------------------------------------------------------
# International
# ---------------------------------------------------------------------------------------------

_IBAN_LEN = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22, "BR": 29, "BY": 28,
    "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18,
    "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22,
    "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20,
    "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SC": 31, "SE": 24, "SI": 19,
    "SK": 24, "SM": 27, "ST": 25, "SV": 28, "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20,
}


def iban_ok(value: str) -> bool:
    v = alnum(value)
    if len(v) < 15 or v[:2] not in _IBAN_LEN or len(v) != _IBAN_LEN[v[:2]] or not v[2:4].isdigit():
        return False
    rearranged = v[4:] + v[:4]
    num = "".join(str(int(c, 36)) for c in rearranged)
    return int(num) % 97 == 1


_ISO_COUNTRIES = set(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY "
    "BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM "
    "FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT "
    "JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN "
    "MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT "
    "PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL "
    "TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW XK".split()
)


def swift_ok(value: str) -> bool:
    v = alnum(value)
    return len(v) in (8, 11) and v[:4].isalpha() and v[4:6] in _ISO_COUNTRIES and v[6:8].isalnum()


def ca_sin_ok(value: str) -> bool:
    d = digits(value)
    return len(d) == 9 and d[0] != "8" and luhn_ok(d)  # 0xx = example/fictitious, still redact


_NINO_RE = re.compile(r"^(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\d{6}[A-D]$")


def uk_nino_ok(value: str) -> bool:
    return bool(_NINO_RE.match(alnum(value)))


# ---------------------------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------------------------

def ipv4_ok(value: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return not ip.is_unspecified


def ipv6_ok(value: str) -> bool:
    try:
        ipaddress.IPv6Address(value)
    except ValueError:
        return False
    return value.count(":") >= 2


def mac_ok(value: str) -> bool:
    v = re.sub(r"[^0-9A-Fa-f]", "", value)
    return len(v) == 12 and v not in ("000000000000", "FFFFFFFFFFFF", "ffffffffffff")


# ---------------------------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------------------------

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58decode(s: str) -> bytes | None:
    n = 0
    for c in s:
        i = _B58.find(c)
        if i < 0:
            return None
        n = n * 58 + i
    full = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + full


def btc_base58_ok(value: str) -> bool:
    if not (25 <= len(value) <= 35) or value[0] not in "13":
        return False
    raw = _b58decode(value)
    if raw is None or len(raw) != 25:
        return False
    return hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:]


_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values: list[int]) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def btc_bech32_ok(value: str) -> bool:
    v = value.lower()
    if not v.startswith("bc1") or not (14 <= len(v) <= 74) or value not in (v, value.upper()):
        return False
    hrp, data = v[:2], v[3:]
    if any(c not in _BECH32 for c in data) or len(data) < 6:
        return False
    vals = [_BECH32.index(c) for c in data]
    expanded = [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]
    const = _bech32_polymod(expanded + vals)
    return const in (1, 0x2BC830A3)  # bech32 / bech32m


def eth_ok(value: str) -> bool:
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", value)) and len(set(value[2:].lower())) > 3


# ---------------------------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------------------------

def imei_ok(value: str) -> bool:
    d = digits(value)
    return len(d) == 15 and luhn_ok(d) and len(set(d)) > 2


def gps_ok(lat: float, lon: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0)


def repeated_or_sequential(d: str) -> bool:
    """True for filler numbers like 0000000, 1234567 or 9876543."""
    if len(set(d)) == 1:
        return True
    seq = "01234567890123456789"
    return d in seq or d in seq[::-1]


_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
       [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
       [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
       [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
       [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
       [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_ok(value: str) -> bool:
    """Verhoeff checksum (Aadhaar)."""
    d = digits(value)
    if len(d) != 12:
        return False
    c = 0
    for i, ch in enumerate(reversed(d)):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return c == 0
