import copy
import pytest
from extract import normalize, passenger_status, parse_person, clean, digest
from households import address_key, group_households


@pytest.mark.parametrize(
    "vehicle,seat,injury,expected",
    [
        ("1", "01", "03", "driver already handled"),
        ("", "03", "03", "vehicle association"),
        ("P1", "03", "03", "vehicle association"),
        ("1", "99", "03", "seating"),
        ("1", "03", "05", "no apparent"),
        ("1", "03", "00", "injury evidence"),
        ("2", "12", "04", "injured passenger"),
    ],
)
def test_passenger(vehicle, seat, injury, expected):
    assert expected in passenger_status(vehicle, seat, injury)


def test_valid_and_duplicates(raw):
    m = normalize(raw)
    assert len(m["recipients"]) == 2
    assert m["recipients"][0]["middle"] == "Q"
    raw["pages"].append(copy.deepcopy(raw["pages"][0]))
    raw["pages"][1]["source_page"] = 2
    assert len(normalize(raw)["recipients"]) == 2
    raw["pages"][1]["render_sha256"] = "different"
    assert not normalize(raw)["recipients"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("A_86", "05"),
        ("A_86", "00"),
        ("A_83", "2"),
        ("118b", "02"),
        ("118b", ""),
        ("vehicle1", "3"),
        ("case", ""),
        ("department", ""),
        ("v1_cityzip", "unknown"),
        ("v1_last", ""),
        ("municipality_code", "0000"),
        ("date", "99 99 99"),
        ("date", ""),
    ],
)
def test_uncertainty_holds_driver(raw, key, value):
    raw["pages"][0]["fields"][key]["normalized"] = value
    assert not [p for p in normalize(raw)["recipients"] if p["role"] == "driver"]


def test_occupant_branches(raw):
    f = raw["pages"][0]["fields"]
    for values in [
        ("3", "01", "03", "Sample, Casey-20 Sample St, Watchung, NJ 07069"),
        ("2", "03", "03", "Unparsed person"),
        ("2", "03", "03", "Example, Alex-20 Sample St, Watchung, NJ 07069"),
        ("2", "99", "05", "Unparsed"),
        ("2", "03", "03", ""),
    ]:
        for key, value in zip(("B_83", "B_84", "B_86", "B_95"), values):
            f[key]["normalized"] = value
        assert not [p for p in normalize(raw)["recipients"] if p["role"] == "passenger"]
    f["118a"]["normalized"] = "unknown"
    f["date"]["normalized"] = "081826"
    assert normalize(raw)["reports"][0]["crash_date"] == "2026-08-18"
    raw["pages"][0]["fields"] = {}
    assert not normalize(raw)["recipients"]


def test_person_formats(raw):
    f = raw["pages"][0]["fields"]
    f["v1_given"]["normalized"] = "Alex"
    assert parse_person(f, 1)["middle"] == ""
    f["v1_name"] = {"normalized": "Alex Q Example"}
    assert parse_person(f, 1)["last_name"] == "Example"
    assert clean(" a   b |") == "a b"
    assert len(digest(b"test")) == 64


def test_households(raw):
    people = normalize(raw)["recipients"]
    a = people[0]
    b = copy.deepcopy(a)
    b["id"] = "other"
    b["street_address"] = "10 Sample Street #1"
    assert address_key(a) == address_key(b)
    assert len(group_households([a, b])) == 1
    b["street_address"] = "10 Sample Street Apt 2"
    assert len(group_households([a, b])) == 2
    b["street_address"] = ""
    assert address_key(b)[0] == "unresolved"
    b.update(manual_exception=True, exception_reason="Synthetic approval")
    g = group_households([b])[0]
    assert len(g["notes"]) == 2
