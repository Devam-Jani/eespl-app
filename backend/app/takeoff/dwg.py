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


def to_dxf(dwg: Path, dxf: Path, timeout: int | None = None) -> list[str]:
    """Convert; returns the converter's warnings (LibreDWG warns a lot on real drawings)."""
    check_size(dwg.stat().st_size)
    with dwg.open("rb") as f:
        version(f.read(6))
    tool = settings.dwg2dxf_path
    if not (Path(tool).is_file() or shutil.which(tool)):
        raise CadError("The DWG reader (LibreDWG) is not installed on this server; ask Devam.")
    timeout = timeout or settings.dwg_timeout_s
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.dxf"
        try:
            run = subprocess.run(  # noqa: S603  (a fixed tool on a file we stored)
                [tool, "-y", "-o", str(out), str(dwg)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CadError(
                f"Reading the drawing took longer than {timeout} seconds and was stopped; ask "
                "the architect for one floor per file, or try again later."
            ) from exc
        log = (run.stdout or "") + (run.stderr or "")
        if not out.is_file() or out.stat().st_size == 0:
            last = " ".join(log.strip().splitlines()[-2:])[:200]
            raise CadError(f"The DWG could not be read (LibreDWG: {last or 'no output'}).")
        dxf.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), dxf)
    return [ln for ln in log.splitlines() if "warning" in ln.lower()][:200]
