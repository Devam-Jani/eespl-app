# ruff: noqa: E501
"""Reading a product data sheet (TDS PDF): the technical properties with their test standards
("Elongation at break, 14 days, ASTMD 412 150%", "Pot life, ASTMD 1640 45 mins"), the coverage
and the standards it complies with. Only what the sheet says is kept; nothing is guessed."""

import re
from pathlib import Path

from app.config import settings as app_settings
from app.methodology import vocab

SKIP = re.compile(
    r"colou?r|appearance|toxicity|ph\b|specific\s*gravity|application\s*temp|shelf|packing|mixing",
    re.I,
)


def text_of(path: Path) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages[:4])
    except Exception:  # noqa: BLE001  (a broken PDF reads as nothing)
        return ""


def read_values(text: str, source: str = "") -> tuple[dict, list[str]]:
    """{property: {value, num, unit, op, standard, source, all}} and the standards named."""
    values: dict[str, dict] = {}
    lines = [vocab.clean(x) for x in text.splitlines()]
    for i, ln in enumerate(lines):
        if not ln or len(ln) > 140 or SKIP.search(ln):
            continue
        prop = "coverage" if "coverage" in ln.lower() else vocab.property_of(ln)
        if not prop or prop in ("consumption", "mesh_gsm"):
            continue
        if (
            prop != "coverage"
            and not vocab.standard_of(ln)
            and (
                len(ln) > 80
                or re.search(
                    r"\b(shall|should|do not|not apply|apply|per layer|use|mix|add|range)\b",
                    ln,
                    re.I,
                )
            )
        ):
            continue  # a sentence of the instructions, not a property
        rest = ln
        std = vocab.standard_of(ln)
        if std:
            rest = ln[ln.upper().replace("ASTMD", "ASTM D").find(std.split()[0]) :]
            rest = vocab.STANDARD_RE.sub("", rest, count=1)
        if prop == "coverage":
            prev = lines[i - 1] if i else ""
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            m = None
            for cand in (
                ln,
                nxt,
                prev,
            ):  # the value is on the line, under it or (in a table) above it
                m = re.search(
                    r"(\d+(?:\.\d+)?\s*(?:[-–]|to)\s*\d+(?:\.\d+)?\s*(?:kg\s*/\s*m2|kg\s*/\s*m²|m2|m²|sq\.?\s*(?:m|ft)\w*)[^.;]*)",
                    cand,
                    re.I,
                )
                if m:
                    break
            if m:
                values.setdefault(
                    "coverage",
                    {
                        "value": vocab.clean(m.group(1)),
                        "num": None,
                        "unit": "",
                        "standard": None,
                        "source": source,
                    },
                )
            continue
        if prop == "pot_life":
            m = re.search(r"(\d+\s*(?:[-–]\s*\d+\s*)?(?:mins?|minutes|hrs?|hours))", rest, re.I)
            if m:
                values.setdefault(
                    "pot_life",
                    {
                        "value": m.group(1),
                        "num": None,
                        "unit": "",
                        "standard": std,
                        "source": source,
                    },
                )
            continue
        # the label's own numbers ("7 days", "1.5mm thickness") are not the value
        body = re.sub(r"\b\d+\s*days?\b|\(\s*[\d.]+\s*mm\s*thickness\s*\)", "", rest, flags=re.I)
        lim = vocab.limit_of(body, prop)
        if lim is None or (prop == "elongation" and lim.unit not in ("%", "")):
            continue
        entry = {
            "value": lim.text(),
            "num": lim.num,
            "op": lim.op,
            "unit": lim.unit,
            "standard": std,
            "source": source,
            "line": ln,
        }
        old = values.get(prop)
        if old is None:
            values[prop] = entry
        else:  # the lowest of several (elongation at 7 and 14 days): the safe one, both kept
            entry["all"] = old.get("all", [old["value"]]) + [entry["value"]]
            if lim.num < (old.get("num") or 0):
                values[prop] = entry
            else:
                old["all"] = entry["all"]
    standards = sorted(
        {vocab.standard_of(m.group(0)) or "" for m in vocab.STANDARD_RE.finditer(text)} - {""}
    )
    return values, standards


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower().replace("®", " ")).replace(" tds ", " ").strip()


def find_tds(name: str, root: Path | None = None) -> Path | None:
    """The data sheet whose file name names the product (TDS_BRONCO® CEMGUARD PLUS.pdf for
    "BRONCO CEMGUARD PLUS"); the shortest such name, so "CEMGUARD" does not take "CEMGUARD PLUS"."""
    root = root or Path(app_settings.data_dir) / "boq-knowledge" / "files"
    if not root.exists():
        return None
    want = _norm(name)
    best: tuple[int, Path] | None = None
    for p in _tds_files(str(root)):
        stem = _norm(p.stem.replace("TDS", " ").replace("tds", " "))
        stem = re.sub(r"\b(?:rev\d*|r\d+|india\d*)\b", "", stem).strip()
        if stem == want or stem == want.replace("bronco ", "") or ("bronco " + stem) == want:
            if best is None or len(p.name) < best[0]:
                best = (len(p.name), p)
    return best[1] if best else None


_CACHE: dict[str, list[Path]] = {}


def _tds_files(root: str) -> list[Path]:
    if root not in _CACHE:
        _CACHE[root] = sorted(
            p
            for p in Path(root).rglob("*")
            if p.suffix.lower() == ".pdf" and "tds" in p.name.lower()
        )
    return _CACHE[root]
