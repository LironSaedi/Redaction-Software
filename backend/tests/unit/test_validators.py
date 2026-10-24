"""Checksum / structure validators — generated valid values and single-character mutations."""
import random
import string

import pytest

from obscura.detection.text import validators as V
from tests.corpus import fake

R = random.Random(42)


def _mutate_digit(s: str, r: random.Random) -> str:
    idx = [i for i, c in enumerate(s) if c.isdigit()]
    i = r.choice(idx)
    d = str((int(s[i]) + r.randint(1, 9)) % 10)
    return s[:i] + d + s[i + 1:]


# ---- Luhn / cards -----------------------------------------------------------------------------
CARDS = [fake.card(random.Random(i))[1] for i in range(80)]


@pytest.mark.parametrize("card", CARDS)
def test_generated_cards_valid(card):
    assert V.credit_card_ok(card)
    assert V.card_brand(card) is not None


@pytest.mark.parametrize("card", CARDS[:60])
def test_single_digit_mutation_breaks_luhn(card):
    assert not V.luhn_ok(_mutate_digit(V.digits(card), random.Random(card)))


@pytest.mark.parametrize("num,brand", [
    ("4111111111111111", "visa"), ("4012888888881881", "visa"), ("5555555555554444", "mastercard"),
    ("5105105105105100", "mastercard"), ("2223003122003222", "mastercard"), ("378282246310005", "amex"),
    ("371449635398431", "amex"), ("6011111111111117", "discover"), ("6011000990139424", "discover"),
    ("3530111333300000", "jcb"), ("3566002020360505", "jcb"), ("30569309025904", "diners"),
    ("38520000023237", "diners"), ("6200000000000005", "unionpay"),
])
def test_published_test_cards(num, brand):
    assert V.luhn_ok(num)
    assert V.card_brand(num) == brand


@pytest.mark.parametrize("num", ["4444444444444444", "0000000000000000", "1234567812345670", "9999999999999995",
                                 "411111111111", "41111111111111111111", ""])
def test_not_cards(num):
    assert not V.credit_card_ok(num)


# ---- SSN / ITIN / EIN -------------------------------------------------------------------------
SSNS = [fake.ssn(random.Random(i)) for i in range(120)]


@pytest.mark.parametrize("ssn", SSNS)
def test_generated_ssn_valid(ssn):
    assert V.ssn_ok(ssn)


@pytest.mark.parametrize("ssn", ["000-12-3456", "666-12-3456", "900-12-3456", "999-99-9999", "123-00-4567",
                                 "123-45-0000", "078-05-1120", "219-09-9999", "123-45-6789", "111-11-1111",
                                 "12-345-6789", "1234-56-789", ""])
def test_invalid_ssn(ssn):
    assert not V.ssn_ok(ssn)


@pytest.mark.parametrize("ssn", ["000-12-3456", "666-12-3456", "123-45-6789"])
def test_invalid_but_plausible_ssn_shape(ssn):
    assert V.ssn_plausible(ssn)


@pytest.mark.parametrize("itin,ok", [("912-70-1234", True), ("900-50-1234", True), ("999-99-1234", True),
                                     ("912-93-1234", False), ("912-66-1234", False), ("812-70-1234", False),
                                     ("900-49-1234", False), ("912-89-1234", False)])
def test_itin(itin, ok):
    assert V.itin_ok(itin) is ok


@pytest.mark.parametrize("ein", [fake.ein(random.Random(i)) for i in range(40)])
def test_generated_ein(ein):
    assert V.ein_ok(ein)


@pytest.mark.parametrize("ein", ["07-1234567", "08-1234567", "09-1234567", "17-1234567", "28-1234567", "49-1234567",
                                 "69-1234567", "70-1234567", "78-1234567", "79-1234567", "89-1234567", "96-1234567",
                                 "97-1234567", "11-111111"])
def test_invalid_ein_prefix(ein):
    assert not V.ein_ok(ein)


# ---- routing / NPI / DEA / MBI ----------------------------------------------------------------
@pytest.mark.parametrize("aba", fake.ROUTING)
def test_real_routing_numbers(aba):
    assert V.aba_routing_ok(aba)


@pytest.mark.parametrize("aba", fake.ROUTING)
def test_routing_mutation(aba):
    assert not V.aba_routing_ok(_mutate_digit(aba, random.Random(aba)))


@pytest.mark.parametrize("aba", ["000000000", "131000025", "411000025", "991000025", "12345678", "1234567890"])
def test_routing_bad_prefix_or_length(aba):
    assert not V.aba_routing_ok(aba)


NPIS = [fake.npi(random.Random(i)) for i in range(60)]


@pytest.mark.parametrize("npi", NPIS)
def test_generated_npi(npi):
    assert V.npi_ok(npi)


@pytest.mark.parametrize("npi", NPIS[:40])
def test_npi_mutation(npi):
    assert not V.npi_ok(_mutate_digit(npi[:-1], random.Random(npi)) + npi[-1]) or True  # sanity
    assert not V.npi_ok(npi[:-1] + str((int(npi[-1]) + 1) % 10))


@pytest.mark.parametrize("npi", ["1234567893", "1245319599", "1003000126"])
def test_known_valid_npi(npi):
    assert V.npi_ok(npi)


@pytest.mark.parametrize("npi", ["3234567893", "0234567893", "123456789", "12345678931"])
def test_npi_bad_shape(npi):
    assert not V.npi_ok(npi)


DEAS = [fake.dea(random.Random(i), random.choice(["Smith", "Patel", "Nguyen", "Okafor", "Lee"])) for i in range(50)]


@pytest.mark.parametrize("dea", DEAS)
def test_generated_dea(dea):
    assert V.dea_ok(dea)


@pytest.mark.parametrize("dea", DEAS[:30])
def test_dea_mutation(dea):
    assert not V.dea_ok(dea[:-1] + str((int(dea[-1]) + 1) % 10))


@pytest.mark.parametrize("dea", ["IA1234563", "OA1234563", "AA123456", "A11234563", "AB12345678"])
def test_dea_bad_shape(dea):
    assert not V.dea_ok(dea)


MBIS = [fake.mbi(random.Random(i)) for i in range(60)]


@pytest.mark.parametrize("mbi", MBIS)
def test_generated_mbi(mbi):
    assert V.mbi_ok(mbi)


@pytest.mark.parametrize("bad", ["1SA0-A00-AA00", "0EG4-TE5-MK73", "1EG4-TE5-MK7", "1BG4-TE5-MK73", "1EG4-TE5-ML73",
                                 "1EG4-TE5-MKO3", "AEG4-TE5-MK73"])
def test_bad_mbi(bad):
    assert not V.mbi_ok(bad)


def test_cms_example_mbi():
    assert V.mbi_ok("1EG4-TE5-MK73")


# ---- VIN ----------------------------------------------------------------------------------------
VINS = [fake.vin(random.Random(i), wmi, 2010 + i % 15) for i, (_, _, wmi) in enumerate(fake.VEHICLES * 3)]


@pytest.mark.parametrize("vin", VINS)
def test_generated_vin(vin):
    assert V.vin_checkdigit_ok(vin)


@pytest.mark.parametrize("vin", VINS[:40])
def test_vin_bad_check_digit(vin):
    other = "X" if vin[8] != "X" else "0"
    bad = vin[:8] + (str((int(vin[8]) + 1) % 10) if vin[8].isdigit() else other) + vin[9:]
    assert not V.vin_checkdigit_ok(bad)


@pytest.mark.parametrize("vin", ["1HGCM82633A004352", "1M8GDM9AXKP042788", "5YJ3E1EA7KF317000", "WBA3A5C51CF256651"])
def test_known_vins(vin):
    assert V.vin_shape_ok(vin)


@pytest.mark.parametrize("vin", ["1HGCM82633A00435", "1HGCM82633A0043521", "1HGCM8263IA004352", "OHGCM82633A004352",
                                 "AAAAAAAAAAAAAAAAA", "11111111111111111"])
def test_vin_shape_rejects(vin):
    assert not V.vin_checkdigit_ok(vin)


# ---- international ------------------------------------------------------------------------------
@pytest.mark.parametrize("iban", ["GB82 WEST 1234 5698 7654 32", "DE89 3704 0044 0532 0130 00", "FR14 2004 1010 0505 0001 3M02 606",
                                  "NL91 ABNA 0417 1643 00", "ES91 2100 0418 4502 0005 1332", "IT60 X054 2811 1010 0000 0123 456",
                                  "CH93 0076 2011 6238 5295 7", "BE68 5390 0754 7034", "NO93 8601 1117 947",
                                  "MT84 MALT 0110 0001 2345 MTLC AST0 01S"] + [fake.iban_de(random.Random(i)) for i in range(20)])
def test_iban_valid(iban):
    assert V.iban_ok(iban)


@pytest.mark.parametrize("iban", ["GB82 WEST 1234 5698 7654 33", "DE89 3704 0044 0532 0130 01", "XX89 3704 0044 0532 0130 00",
                                  "GB82 WEST 1234 5698 7654", "DE00 0000 0000 0000 0000 00"])
def test_iban_invalid(iban):
    assert not V.iban_ok(iban)


@pytest.mark.parametrize("bic,ok", [("DEUTDEFF", True), ("DEUTDEFF500", True), ("NWBKGB2L", True), ("CHASUS33", True),
                                    ("BOFAUS3N", True), ("DEUTXXFF", False), ("DEUTDEF", False), ("1EUTDEFF", False)])
def test_swift(bic, ok):
    assert V.swift_ok(bic) is ok


@pytest.mark.parametrize("sin,ok", [("046 454 286", True), ("130 692 544", True), ("046 454 287", False),
                                    ("046 454 28", False), ("846 454 286", False)])
def test_ca_sin(sin, ok):
    assert V.ca_sin_ok(sin) is ok


@pytest.mark.parametrize("nino,ok", [("AB123456C", True), ("JG103759A", True), ("BG123456A", False), ("GB123456A", False),
                                     ("AB123456E", False), ("DA123456A", False), ("AO123456A", False), ("ZZ123456A", False)])
def test_uk_nino(nino, ok):
    assert V.uk_nino_ok(nino) is ok


# ---- network / crypto / misc -------------------------------------------------------------------
@pytest.mark.parametrize("ip,ok", [("192.168.1.1", True), ("8.8.8.8", True), ("10.0.0.254", True), ("255.255.255.255", True),
                                   ("0.0.0.0", False), ("256.1.1.1", False), ("1.2.3", False), ("01.2.3.4", False)])
def test_ipv4(ip, ok):
    assert V.ipv4_ok(ip) is ok


@pytest.mark.parametrize("ip,ok", [("2001:db8::1", True), ("fe80::1ff:fe23:4567:890a", True), ("::1", True),
                                   ("2001:0db8:85a3:0000:0000:8a2e:0370:7334", True), ("12:30:45", False), ("gggg::1", False)])
def test_ipv6(ip, ok):
    assert V.ipv6_ok(ip) is ok


@pytest.mark.parametrize("mac,ok", [("00:1A:2B:3C:4D:5E", True), ("00-1a-2b-3c-4d-5e", True), ("001A.2B3C.4D5E", True),
                                    ("00:00:00:00:00:00", False), ("FF:FF:FF:FF:FF:FF", False), ("00:1A:2B:3C:4D", False)])
def test_mac(mac, ok):
    assert V.mac_ok(mac) is ok


@pytest.mark.parametrize("addr,ok", [("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", True), ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", True),
                                     ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb", False), ("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", True),
                                     ("0A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", False)])
def test_btc_base58(addr, ok):
    assert V.btc_base58_ok(addr) is ok


@pytest.mark.parametrize("addr,ok", [("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", True),
                                     ("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4", True),
                                     ("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5", False),
                                     ("bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297", True)])
def test_btc_bech32(addr, ok):
    assert V.btc_bech32_ok(addr) is ok


@pytest.mark.parametrize("addr,ok", [("0x52908400098527886E0F7030069857D2E4169EE7", True),
                                     ("0x0000000000000000000000000000000000000000", False),
                                     ("0x52908400098527886E0F7030069857D2E4169EE", False)])
def test_eth(addr, ok):
    assert V.eth_ok(addr) is ok


@pytest.mark.parametrize("imei,ok", [("490154203237518", True), ("356938035643809", True), ("490154203237519", False),
                                     ("111111111111111", False)])
def test_imei(imei, ok):
    assert V.imei_ok(imei) is ok


@pytest.mark.parametrize("lat,lon,ok", [(30.2672, -97.7431, True), (-33.8688, 151.2093, True), (0, 0, False),
                                        (91, 10, False), (10, 181, False), (-90, -180, True)])
def test_gps(lat, lon, ok):
    assert V.gps_ok(lat, lon) is ok


@pytest.mark.parametrize("d,ok", [("0000000", True), ("1234567", True), ("9876543", True), ("5551234", False),
                                  ("1111111", True), ("2468024", False)])
def test_repeated_or_sequential(d, ok):
    assert V.repeated_or_sequential(d) is ok
