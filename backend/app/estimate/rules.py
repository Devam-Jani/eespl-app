"""One rule set for an area's quantity, used by the material estimate and by the drawing's
quotation: the floor less its cut-outs; the upturn (or skirting) as the periphery × its height;
a sunken area's side walls as the periphery × the sunk depth; a vertical item (a retaining wall)
as its length × its height. Every figure in sqm, with the sum written out."""

from dataclasses import dataclass
from decimal import Decimal

D = Decimal
ZERO = D(0)
SQFT_PER_SQM = D("10.7639")


def n(v: Decimal | int | float | None, places: int = 2) -> str:
    if v is None:
        return "—"
    q = D(str(v)).quantize(D(1).scaleb(-places))
    return f"{q:,.{places}f}"


@dataclass
class AreaQty:
    floor_sqm: Decimal  # as drawn
    cutout_sqm: Decimal  # the cut-outs inside it
    periphery_m: Decimal  # the outer edge and the cut-outs' edges
    upturn_m: Decimal  # the height turned up the walls
    sunk_m: Decimal
    wall_length_m: Decimal
    wall_height_m: Decimal

    @property
    def net_floor_sqm(self) -> Decimal:
        return self.floor_sqm - self.cutout_sqm

    @property
    def upturn_sqm(self) -> Decimal:
        return self.periphery_m * self.upturn_m

    @property
    def sunk_sqm(self) -> Decimal:
        return self.periphery_m * self.sunk_m

    @property
    def wall_sqm(self) -> Decimal:
        return self.wall_length_m * self.wall_height_m

    @property
    def total_sqm(self) -> Decimal:
        return self.net_floor_sqm + self.upturn_sqm + self.sunk_sqm + self.wall_sqm

    def formula(self, name: str = "") -> str:
        """ "Terrace L7: 412.30 floor + 86.40 rmt × 0.30 upturn = 438.22 sqm"."""
        bits = []
        if self.floor_sqm:
            fl = n(self.floor_sqm)
            if self.cutout_sqm:
                fl = f"({fl} − {n(self.cutout_sqm)} cut-outs)"
            bits.append(f"{fl} floor")
        if self.upturn_sqm:
            bits.append(f"{n(self.periphery_m)} rmt × {n(self.upturn_m)} upturn")
        if self.sunk_sqm:
            bits.append(f"{n(self.periphery_m)} rmt × {n(self.sunk_m)} sunk")
        if self.wall_sqm:
            bits.append(f"{n(self.wall_length_m)} m × {n(self.wall_height_m)} m wall")
        head = f"{name}: " if name else ""
        return f"{head}{' + '.join(bits) or '0'} = {n(self.total_sqm)} sqm"


def area_quantity(
    floor_sqm,
    periphery_m,
    *,
    cutout_sqm=0,
    upturn_m=0,
    sunk_m=0,
    wall_length_m=0,
    wall_height_m=0,
    use_floor: bool = True,
    use_upturn: bool = True,
) -> AreaQty:
    return AreaQty(
        floor_sqm=D(str(floor_sqm or 0)) if use_floor else ZERO,
        cutout_sqm=D(str(cutout_sqm or 0)) if use_floor else ZERO,
        periphery_m=D(str(periphery_m or 0)),
        upturn_m=D(str(upturn_m or 0)) if use_upturn else ZERO,
        sunk_m=D(str(sunk_m or 0)),
        wall_length_m=D(str(wall_length_m or 0)),
        wall_height_m=D(str(wall_height_m or 0)),
    )


def upturn_height(own_mm, area_type_mm, system_mm, default_mm, sunk_m) -> tuple[Decimal, str]:
    """The upturn: the area's own (its drawing note, or typed), else its area type's, else the
    system's, else the default; a sunken area's side walls are its upturn unless its own says
    otherwise. (metres, where from)"""
    if own_mm is not None:
        return D(str(own_mm)) / 1000, "the drawing"
    if sunk_m:
        return ZERO, "sunk: its side walls instead"
    if area_type_mm:
        return D(str(area_type_mm)) / 1000, "the area type"
    if system_mm:
        return D(str(system_mm)) / 1000, "the system"
    return D(str(default_mm or 0)) / 1000, "the default"
