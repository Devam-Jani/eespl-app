import pytest

from app.masters.units import DEFAULT_ALIASES, build_alias_map, normalise_unit


@pytest.mark.parametrize(
    ("text", "code"),
    [
        # the examples from the M1 spec
        ("Sq.m", "sqm"), ("SQM", "sqm"), ("Smt", "sqm"),
        ("RMT", "rmt"), ("Rm", "rmt"), ("Rmt", "rmt"),
        ("CUMT", "cum"), ("Cum", "cum"),
        ("Nos", "nos"), ("No", "nos"), ("Each", "nos"),
        ("LS", "ls"), ("Lumpsum", "ls"),
        # spellings seen in real BOQs
        ("Sq.mt.", "sqm"), ("sq .mt", "sqm"), ("Sq. Meter", "sqm"), ("M2", "sqm"), ("m²", "sqm"),
        ("SǪM", "sqm"), ("sqm (RO)", "sqm"), ("Sqmtr", "sqm"),
        ("Sq. ft.", "sqft"), ("SFT", "sqft"), ("SQF", "sqft"),
        ("R.mt.", "rmt"), ("Rn.Mtr", "rmt"), ("Metre", "rmt"), ("mtr", "rmt"),
        ("R Ft", "rft"), ("RFT", "rft"),
        ("Cu.m", "cum"), ("M3", "cum"), ("Cu mt", "cum"),
        ("KG", "kg"), ("Kgs", "kg"),
        ("Litres", "ltr"), ("Ltr", "ltr"),
        ("Per NO", "nos"), ("Ea.", "nos"), ("NOS.", "nos"),
        ("Set", "set"), ("Rolls", "roll"), ("Lump sum", "ls"), ("ADHOK", "ls"),
        ("  sqm  ", "sqm"),
    ],
)  # fmt: skip
def test_known_spellings(text, code):
    assert normalise_unit(text) == code


@pytest.mark.parametrize("text", [None, "", "  ", "-", "RO", "Nos OR Sq Ft", "CM", "5", "Hectare"])
def test_blank_and_ambiguous_units_are_not_guessed(text):
    assert normalise_unit(text) is None


def test_aliases_can_come_from_the_database():
    aliases = build_alias_map([("sqm", ["square mtr"]), ("bag", ["bags", "Bg"])])
    assert normalise_unit("Square Mtr.", aliases) == "sqm"
    assert normalise_unit("BG", aliases) == "bag"
    assert normalise_unit("sqm", aliases) == "sqm"  # the code is always its own alias
    assert normalise_unit("Sqmt", aliases) is None  # not in this map


def test_every_default_alias_maps_to_one_unit():
    # A key claimed by two units would make normalisation depend on dict order.
    from app.masters.units import DEFAULT_UNITS, unit_key

    owners: dict[str, set[str]] = {}
    for code, (_, aliases) in DEFAULT_UNITS.items():
        for alias in [code, *aliases]:
            owners.setdefault(unit_key(alias), set()).add(code)
    assert {k: v for k, v in owners.items() if len(v) > 1} == {}
    assert set(DEFAULT_ALIASES.values()) == set(DEFAULT_UNITS)
