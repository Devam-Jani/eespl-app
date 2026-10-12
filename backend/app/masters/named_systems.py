"""The systems Ankur Sir named in the director's review (12 Oct): Samgard, Samgard Plus, Ultra Flex
and Hybrid PU, with the products our data has for them (the products master and rate library v2),
and the suitable systems per area type (sunken, toilet, terrace).

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

NAMED = [
    {"code": "SAMGARD", "name": "Samgard", "note": NOT_FOUND, "products": []},
    {"code": "SAMGARD-PLUS", "name": "Samgard Plus", "note": NOT_FOUND, "products": []},
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

# area type -> (the default suggestion, the suitable systems). Sunken = Samgard Plus with the
# other three to choose from (the director's meeting); our library treats toilets with sunken
# slabs and wet areas; terrace: Hybrid PU, as in our terrace offers.
AREA_TYPES = {
    "Sunken slab": ("SAMGARD-PLUS", ["SAMGARD-PLUS", "SAMGARD", "ULTRA-FLEX", "HYBRID-PU"]),
    "Toilet / bathroom": (None, ["ULTRA-FLEX", "SAMGARD", "SAMGARD-PLUS", "HYBRID-PU"]),
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
