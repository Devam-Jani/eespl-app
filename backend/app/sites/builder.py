"""Site builder presets: "add tower T1 with B2..G..14, 4 flats per floor, 2 toilets + 1 kitchen +
1 balcony per flat, terrace on top, OHT on the terrace, 2 lift pits, UG tank" in one call.

The tree it makes:
    T1 (tower)
    ├── B2, B1 (basement)            no flats in basements
    ├── G, Floor 1 … Floor 14 (floor)
    │   └── G01 / 101 … (flat)       flats_per_floor, from `flats_from` up
    │       └── Toilet 1, Toilet 2, Kitchen, Balcony
    ├── Terrace (terrace)            level top + 1
    │   └── OHT 1 (oh_tank)
    ├── Lift pit 1, Lift pit 2 (lift_pit)
    └── UG tank 1 (ug_tank)
"""

from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.sites.models import SiteNode

ROOM_KINDS = {"toilet": "Toilet", "kitchen": "Kitchen", "balcony": "Balcony"}


class TowerPreset(BaseModel):
    name: str = Field(default="T1", min_length=1, max_length=50)
    parent_id: int | None = None  # put the tower under a wing or another node
    basements: int = Field(default=0, ge=0, le=10)
    ground: bool = True
    upper_floors: int = Field(default=0, ge=0, le=150)
    flats_per_floor: int = Field(default=0, ge=0, le=50)
    flats_from: str = Field(default="G", pattern=r"^(G|1)$")  # flats on G and above, or 1 and up
    rooms_per_flat: dict[str, int] = Field(default_factory=lambda: {"toilet": 2, "kitchen": 1})
    terrace: bool = True
    oh_tanks: int = Field(default=0, ge=0, le=10)  # on the terrace (or under the tower)
    lift_pits: int = Field(default=0, ge=0, le=20)
    ug_tanks: int = Field(default=0, ge=0, le=10)


@dataclass
class Spec:
    kind: str
    name: str
    level_no: int | None = None
    children: list["Spec"] = field(default_factory=list)


def _floor_name(level: int) -> str:
    return "G" if level == 0 else (f"B{-level}" if level < 0 else f"Floor {level}")


def _flat_name(level: int, n: int) -> str:
    return f"G{n:02d}" if level == 0 else f"{level}{n:02d}"


def tower_spec(p: TowerPreset) -> Spec:
    tower = Spec("tower", p.name)
    levels = (
        list(range(-p.basements, 0))
        + ([0] if p.ground else [])
        + list(range(1, p.upper_floors + 1))
    )
    first_flat_level = 0 if p.flats_from == "G" else 1
    for level in levels:
        floor = Spec("basement" if level < 0 else "floor", _floor_name(level), level)
        if level >= first_flat_level:
            for n in range(1, p.flats_per_floor + 1):
                flat = Spec("flat", _flat_name(level, n), level)
                for kind, label in ROOM_KINDS.items():
                    count = p.rooms_per_flat.get(kind, 0)
                    for i in range(1, count + 1):
                        name = f"{label} {i}" if count > 1 else label
                        flat.children.append(Spec(kind, name, level))
                floor.children.append(flat)
        tower.children.append(floor)
    top = (max(levels) + 1) if levels else 1
    tanks = [Spec("oh_tank", f"OHT {i}", top) for i in range(1, p.oh_tanks + 1)]
    if p.terrace:
        tower.children.append(Spec("terrace", "Terrace", top, tanks))
    else:
        tower.children.extend(tanks)
    bottom = min(levels) if levels else 0
    tower.children.extend(
        Spec("lift_pit", f"Lift pit {i}", bottom) for i in range(1, p.lift_pits + 1)
    )
    tower.children.extend(Spec("ug_tank", f"UG tank {i}", bottom) for i in range(1, p.ug_tanks + 1))
    return tower


def count(spec: Spec) -> Counter:
    c = Counter({spec.kind: 1})
    for child in spec.children:
        c += count(child)
    return c


def preview(p: TowerPreset) -> dict[str, int]:
    c = count(tower_spec(p))
    return {"total": sum(c.values()), **dict(sorted(c.items()))}


def create(db: Session, site_id: int, p: TowerPreset, user_id, sort_start: int = 0) -> int:
    """Insert the tower's nodes; returns how many were made."""
    made = 0

    def add(spec: Spec, parent_id: int | None, order: int) -> None:
        nonlocal made
        node = SiteNode(
            site_id=site_id,
            parent_id=parent_id,
            kind=spec.kind,
            name=spec.name,
            sort_order=order,
            level_no=spec.level_no,
            created_by=user_id,
        )
        db.add(node)
        db.flush()
        made += 1
        for i, child in enumerate(spec.children):
            add(child, node.id, i)

    add(tower_spec(p), p.parent_id, sort_start)
    return made
