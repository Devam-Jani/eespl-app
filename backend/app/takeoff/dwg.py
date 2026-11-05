"""DWG to DXF with LibreDWG's dwg2dxf: a separate command-line tool, run with a timeout and a size
limit, its failures turned into plain messages (never a crash).

The format is read from the file's first bytes (AC1032 is AutoCAD 2018, the newest LibreDWG reads;
our architects' drawings are 2018). A newer one is refused with what to do about it."""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

VERSIONS = {
    "AC1012": "AutoCAD R13", "AC1014": "AutoCAD R14", "AC1015": "AutoCAD 2000",
    "AC1018": "AutoCAD 2004", "AC1021": "AutoCAD 2007", "AC1024": "AutoCAD 2010",
    "AC1027": "AutoCAD 2013", "AC1032": "AutoCAD 2018",
}  # fmt: skip
NEWEST = "AC1032"


class CadError(Exception):
    """A drawing we cannot read, with the message to show."""


@dataclass
class Version:
    code: str
    name: str


def version(head: bytes) -> Version:
    """The DWG format from the file's first six bytes, or a plain error."""
    code = head[:6].decode("ascii", "replace")
    if not code.startswith("AC") or not code[2:].isdigit():
        raise CadError("This is not an AutoCAD drawing (DWG). Upload the .dwg the architect sent.")
    if code in VERSIONS:
        return Version(code, VERSIONS[code])
    if code > NEWEST:
        raise CadError(
            f"This file is in a newer AutoCAD format than 2018 ({code}); save it as AutoCAD 2018 "
            "DWG from AutoCAD (Save As, AutoCAD 2018 Drawing) and upload again."
        )
    raise CadError(
        f"This file is in a very old AutoCAD format ({code}); open it in AutoCAD, save it as "
        "AutoCAD 2018 DWG and upload again."
    )


def check_size(size: int) -> None:
    limit = settings.dwg_max_mb * 1024 * 1024
    if size > limit:
        raise CadError(
            f"The drawing is larger than {settings.dwg_max_mb} MB; ask for one floor per file."
        )


def save_as_dxf(v: Version, note: str | None) -> str:
    """The message for a drawing LibreDWG converts without its contents."""
    said = f" (the converter's last warning: {note[:200]})" if note else ""
    return (
        f"The DWG reader could not read what is drawn in this {v.name} drawing ({v.code}){said}. "
        "Open it in AutoCAD, save it as DXF (Save As, AutoCAD 2013 DXF) and upload the .dxf."
    )


def last_note(log: str) -> str | None:
    """The converter's last warning or error line (what it last complained about)."""
    lines = [ln.strip() for ln in log.splitlines() if ln.lower().startswith(("warning", "error"))]
    return lines[-1] if lines else None


def _run(tool: str, args: list[str], timeout: int) -> str:
    try:
        run = subprocess.run(  # noqa: S603  (a fixed tool on a file we stored)
            [tool, *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise CadError(
            f"Reading the drawing took longer than {timeout} seconds and was stopped; ask "
            "the architect for one floor per file, or try again later."
        ) from exc
    return (run.stdout or "") + (run.stderr or "")


def _pairs(data: bytes) -> list[tuple[bytes, bytes]]:
    """A text DXF as (group code, value) pairs, the codes stripped, the values as written."""
    lines = data.split(b"\n")
    return [(lines[i].strip(), lines[i + 1].rstrip(b"\r")) for i in range(0, len(lines) - 1, 2)]


def _sections(pairs: list[tuple[bytes, bytes]]) -> list[tuple[bytes, list, bool]]:
    """(name, pairs from SECTION to ENDSEC, ended) for each section, in the order written."""

    def name(p: list) -> bytes:
        return p[1][1].strip() if len(p) > 1 else b""

    out: list[tuple[bytes, list, bool]] = []
    cur: list | None = None
    for code, value in pairs:
        if code == b"0" and value == b"SECTION":
            if cur is not None:
                out.append((name(cur), cur, False))
            cur = [(code, value)]
        elif cur is not None:
            cur.append((code, value))
            if code == b"0" and value == b"ENDSEC":
                out.append((name(cur), cur, True))
                cur = None
    if cur is not None:
        out.append((name(cur), cur, False))
    return out


def has_entities(data: bytes) -> bool:
    return any(n == b"ENTITIES" and ended for n, _p, ended in _sections(_pairs(data)))


def splice(full: bytes, minimal: bytes) -> bytes | None:
    """The full DXF (header, layers, blocks) with the minimal DXF's ENTITIES section put in its
    place, or None when the minimal one has none either. The minimal DXF numbers its handles from
    scratch, so they clash with the full one's tables: its handles and owner links are dropped
    and the reader gives the entities new ones."""
    found = _sections(_pairs(minimal))
    ents = next((p for n, p, ended in found if n == b"ENTITIES" and ended), None)
    if ents is None:
        return None
    kept, in_group = [], False
    for code, value in ents:
        if code == b"102":  # {ACAD_REACTORS ... } and the like: owner links
            in_group = value.startswith(b"{")
            continue
        if in_group or code in (b"5", b"330", b"360"):
            continue
        kept.append((code, value))
    sections = [(n, p) for n, p, ended in _sections(_pairs(full)) if ended and n != b"ENTITIES"]
    at = next((i + 1 for i, (n, _p) in enumerate(sections) if n == b"BLOCKS"), len(sections))
    sections.insert(at, (b"ENTITIES", kept))
    nl = b"\r\n" if b"\r\n" in full[:200] else b"\n"
    body = [b"%3s" % c + nl + v for _n, p in sections for c, v in p]
    return nl.join([*body, b"  0" + nl + b"EOF"]) + nl


def to_dxf(dwg: Path, dxf: Path, timeout: int | None = None) -> list[str]:
    """Convert; returns the converter's warnings (LibreDWG warns a lot on real drawings).

    LibreDWG 0.13 writes some drawings without their ENTITIES section (it stops after the blocks
    with no error, so nothing is drawn); its minimal mode (only the entities) still writes them,
    so a second, minimal run's entities are spliced into the first DXF. When that has none either,
    the message says to save the drawing as DXF from AutoCAD."""
    check_size(dwg.stat().st_size)
    with dwg.open("rb") as f:
        v = version(f.read(6))
    tool = settings.dwg2dxf_path
    if not (Path(tool).is_file() or shutil.which(tool)):
        raise CadError("The DWG reader (LibreDWG) is not installed on this server; ask Devam.")
    timeout = timeout or settings.dwg_timeout_s
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.dxf"
        log = _run(tool, ["-y", "-o", str(out), str(dwg)], timeout)
        if not out.is_file() or out.stat().st_size == 0:
            last = " ".join(log.strip().splitlines()[-2:])[:200]
            raise CadError(f"The DWG could not be read (LibreDWG: {last or 'no output'}).")
        data = out.read_bytes()
        if not has_entities(data):
            from app.takeoff.reader import repair  # noqa: PLC0415  (the reader imports this module)

            mini = Path(tmp) / "minimal.dxf"
            _run(tool, ["-y", "-m", "-o", str(mini), str(dwg)], timeout)
            whole = splice(data, repair(mini.read_bytes())[0]) if mini.is_file() else None
            if whole is None:
                raise CadError(save_as_dxf(v, last_note(log)))
            out.write_bytes(whole)
        dxf.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), dxf)
    return [ln for ln in log.splitlines() if "warning" in ln.lower()][:200]
