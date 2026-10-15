"""The systems Ankur Sir named in the director's review (12 Oct): Cemguard and Cemguard Plus
("Samgard" in the meeting is Bronco Cemguard), Ultra Flex and Hybrid PU, with the products our
data has for them (the products master and rate library v2), and the suitable systems per area
type (sunken, toilet, terrace).

Consumption and coats are left blank and marked "to confirm" wherever our data does not give them:
never guessed. Where our data gives a figure in another form (a coverage per pack, two offers that
disagree), it is quoted in the note for whoever confirms it, not turned into a number here.

Plain SQL on a connection, so the migration and the tests run the same seed. Safe to run again.
"""

from sqlalchemy import text
from sqlalchemy.engine import Connection

NOT_FOUND = (
    "Named by Ankur Sir in the director's review (12 Oct). Not in the products master or rate "
    "library v2: its products, consumption and coats are to confirm."
)

CEMGUARD_NOTE = (
    'Bronco Cemguard ("Samgard" in the director\'s meeting, 12 Oct). Not described in our offers '
    "(they use Cemguard Plus and Cemguard CTE-HB): coats and consumption to confirm."
)
CEMGUARD_PLUS_NOTE = (
    "Bronco Cemguard Plus: two-component acrylic polymer elastomeric coating, as in our bungalow "
    "offer (Deep Vyana). Consumption to confirm."
)

NAMED = [
    {
        "code": "CEMGUARD",
        "name": "Cemguard",
        "note": CEMGUARD_NOTE,
        "products": [
            {
                "code": "BRONCO-CEMGUARD",
                "new": {"name": "BRONCO CEMGUARD", "brand": "Bronco", "unit": "kg",
                        "pack_size": None, "pack_unit": None},
                "aliases": ["SAMGARD"],
                "coats": None,
                "note": "No price and no consumption in our data: to confirm.",
            }
        ],
    },
    {
        "code": "CEMGUARD-PLUS",
        "name": "Cemguard Plus",
        "note": CEMGUARD_PLUS_NOTE,
        "products": [
            {
                "code": "BRONCO-CEMGUARD-PLUS",
                "new": {"name": "BRONCO CEMGUARD PLUS", "brand": "Bronco", "unit": "kg",
                        "pack_size": None, "pack_unit": None},
                "aliases": ["SAMGARD PLUS", "SAMGARD"],
                "coats": 2,  # "1st coat ... 2nd & final coat of BRONCO CEMGUARD PLUS" (our offers)
                "note": "Our offers: 1st coat, then 2nd & final coat (in toilets over one coat of "
                "Bronco Cemcrystal Plus, with fibre mesh). Consumption per sqm to confirm.",
            }
        ],
    },
    {
        "code": "ULTRA-FLEX",
        "name": "Ultra Flex",
        "note": "Named by Ankur Sir (12 Oct). Our BOQs use Brushbond Ultraflex (Fosroc) for "
        "toilets, sunken slabs and wet areas.",
        "products": [
            {
                "code": "BRUSHBOND-ULTRAFLEX",
                "new": {"name": "BRUSHBOND ULTRAFLEX", "brand": "Fosroc", "unit": "kg",
                        "pack_size": 25, "pack_unit": "pack"},
                "coats": 2,  # "Supplying & applying 2 two coats of Brushbond Ultraflex" (library)
                "note": "Rate library v2: 2 coats to 1 mm wet film, coverage about 15-16 sqm per "
                "25 kg pack. Consumption per sqm to confirm.",
            }
        ],
    },
    {
        "code": "HYBRID-PU",
        "name": "Hybrid PU",
        "note": "Named by Ankur Sir (12 Oct). Bronco Hybrid PU, as in our terrace offers.",
        "products": [
            {
                "code": "BRONCO-HYBRID-PU",
                "new": {"name": "BRONCO HYBRID PU", "brand": "Bronco", "unit": "kg",
                        "pack_size": None, "pack_unit": None},
                "coats": None,
                "note": "Our offers disagree: primer 1:1 at 5-6 sqm then 2 coats, overall 1.2 kg "
                "(Deep Vyana); 3 coats at 1.4 kg per sqm (Ladani). Coats and consumption to "
                "confirm.",
            }
        ],
    },
]  # fmt: skip

# area type -> (the default suggestion, the suitable systems). Sunken = Cemguard Plus with the
# other three to choose from (the director's meeting); our library treats toilets with sunken
# slabs and wet areas; terrace: Hybrid PU, as in our terrace offers.
AREA_TYPES = {
    "Sunken slab": ("CEMGUARD-PLUS", ["CEMGUARD-PLUS", "CEMGUARD", "ULTRA-FLEX", "HYBRID-PU"]),
    "Toilet / bathroom": (None, ["ULTRA-FLEX", "CEMGUARD", "CEMGUARD-PLUS", "HYBRID-PU"]),
    "Terrace": ("HYBRID-PU", ["HYBRID-PU"]),
}


def seed(conn: Connection) -> dict[str, int]:
    """Add the named systems (and the products found for them) once; fill the area types."""
    ids: dict[str, int] = {}
    for s in NAMED:
        sid = conn.execute(
            text("SELECT id FROM systems WHERE code = :c"), {"c": s["code"]}
        ).scalar()
        if sid is None:
            sid = conn.execute(
                text(
                    "INSERT INTO systems (code, name, unit, to_confirm, note) "
                    "VALUES (:c, :n, 'sqm', true, :note) RETURNING id"
                ),
                {"c": s["code"], "n": s["name"], "note": s["note"]},
            ).scalar()
        # every run: the products found for it and their link (never a price)
        for p in s["products"]:
            pid = conn.execute(
                text("SELECT id FROM products WHERE code = :c"), {"c": p["code"]}
            ).scalar()
            if pid is None:
                new = p["new"]
                pid = conn.execute(
                    text(
                        "INSERT INTO products (code, name, brand, unit, pack_size, pack_unit) "
                        "VALUES (:c, :n, :b, :u, :ps, :pu) RETURNING id"
                    ),
                    {
                        "c": p["code"],
                        "n": new["name"],
                        "b": new["brand"],
                        "u": new["unit"],
                        "ps": new["pack_size"],
                        "pu": new["pack_unit"],
                    },
                ).scalar()
            for alias in p.get("aliases", []):  # "Samgard" still finds it
                conn.execute(
                    text(
                        "UPDATE products SET aliases = array_append(aliases, :a) "
                        "WHERE id = :p AND NOT (:a = ANY(aliases))"
                    ),
                    {"a": alias, "p": pid},
                )
            if not conn.execute(
                text("SELECT 1 FROM system_components WHERE system_id = :s AND product_id = :p"),
                {"s": sid, "p": pid},
            ).scalar():
                conn.execute(
                    text(
                        "INSERT INTO system_components (system_id, product_id, "
                        "consumption_per_unit, wastage_percent, coats, to_confirm, note) "
                        "VALUES (:s, :p, NULL, 0, :coats, true, :note)"
                    ),
                    {"s": sid, "p": pid, "coats": p["coats"], "note": p["note"]},
                )
        ids[s["code"]] = sid
    for name, (default, suitable) in AREA_TYPES.items():
        conn.execute(
            text(
                "UPDATE area_types SET suitable_system_ids = :ids, "
                "default_system_id = coalesce(default_system_id, :d) WHERE name = :n"
            ),
            {"ids": [ids[c] for c in suitable], "d": ids[default] if default else None, "n": name},
        )
    return ids


# the rest of the Bronco range in our offers: in the products master, with no price
RANGE = [
    {"code": "BRONCO-CEMCRYSTAL-PLUS", "name": "BRONCO CEMCRYSTAL PLUS",
     "brand": "Bronco", "unit": "kg"},
]  # fmt: skip


def cemguard(conn: Connection) -> dict[str, int]:
    """Samgard and Samgard Plus are Bronco Cemguard and Cemguard Plus (the rate working review):
    rename them, link the Bronco products (added when missing, never with a price), keep "Samgard"
    as an alias, and add Cemcrystal Plus to the products master."""
    for old, new, name, note in (
        ("SAMGARD", "CEMGUARD", "Cemguard", CEMGUARD_NOTE),
        ("SAMGARD-PLUS", "CEMGUARD-PLUS", "Cemguard Plus", CEMGUARD_PLUS_NOTE),
    ):
        conn.execute(
            text("UPDATE systems SET code = :new, name = :n, note = :note WHERE code = :old"),
            {"new": new, "n": name, "note": note, "old": old},
        )
    for r in RANGE:
        if not conn.execute(
            text("SELECT 1 FROM products WHERE code = :c"), {"c": r["code"]}
        ).scalar():
            conn.execute(
                text("INSERT INTO products (code, name, brand, unit) VALUES (:c, :n, :b, :u)"),
                {"c": r["code"], "n": r["name"], "b": r["brand"], "u": r["unit"]},
            )
    return seed(conn)
