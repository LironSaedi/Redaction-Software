import pytest

from obscura.detection.text.addresses import find_addresses
from obscura.detection.text.base import NormText


def addrs(t):
    return [s for s in find_addresses(NormText(t)) if s.score >= 0.5]


POS = ["4417 Oakridge Dr, Apt 3B, Austin, TX 78745", "1600 Pennsylvania Avenue NW, Washington, DC 20500",
       "99 W. 5th St., Ste 200\nNew York, NY 10001-1234", "PO Box 4471, Tulsa, OK 74103", "P.O. Box 65193",
       "8816 Johnson Fords Apt. 120, Lake Michael, NV 89012", "123 Main Street", "12 Bank Street", "742 Evergreen Terrace",
       "350 Fifth Avenue", "1 Infinite Loop, Cupertino, CA 95014", "221B Baker Street", "10 Downing St",
       "4500 Highway 101", "123 County Road 45", "2401 State Route 9", "Rural Route 2 Box 15", "RR 3, Box 117",
       "18524 N. Deer Creek Road", "77 Martin Luther King Jr Blvd", "5021 Hill Key, Key West, FL 33040",
       "13432 Prairie View Ln, Kilgore, TX 75662", "300 E Main St #4", "56 Old Mill Rd Unit 12", "1200 112th Ave NE",
       "15 Rue Mission, Dallas, TX 75201", "Austin, TX 78745", "Toronto, ON M5V 3L9", "4417 OAKRIDGE DR"]


@pytest.mark.parametrize("t", POS)
def test_address_positive(t):
    a = addrs(f"Lives at {t}.")
    assert a, t
    assert max(len(x.text) for x in a) >= min(len(t), 10)


NEG = ["filed in 2023 District Court", "12 Superior Court judges", "Page 3 Main Street Act", "3   Q.  Is there anything else?",
       "RR 18  Temp 98.4", "about 30 Golf Club members", "Exhibit 4 Court", "Visits 12 Park", "2019 Yacht Club gala",
       "Section 12 Main Street", "flexion 45 Hill"]


@pytest.mark.parametrize("t", NEG)
def test_address_negative(t):
    assert not addrs(t), [(x.text, x.score) for x in addrs(t)]
