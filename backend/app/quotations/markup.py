"""The small markup used in the quotation libraries: **bold** (product names), ==highlight==
(notes), a newline for a new paragraph, {placeholders} in letters. Turned into runs for Word and
into HTML for the preview and the PDF."""

import html
import re
from dataclasses import dataclass

TOKEN = re.compile(r"(\*\*|==)")
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


@dataclass
class Run:
    text: str
    bold: bool = False
    highlight: bool = False


def runs(line: str, bold: bool = False) -> list[Run]:
    """One paragraph -> runs. With bold=True the whole paragraph is bold (** then changes
    nothing)."""
    out: list[Run] = []
    b, h = bold, False
    for part in TOKEN.split(line):
        if part == "**":
            if not bold:
                b = not b
        elif part == "==":
            h = not h
        elif part:
            out.append(Run(part, b, h))
    return out


def normalize(text: str) -> str:
    """Balanced markup again (adjacent runs with the same look merged, blank runs plain, spaces
    outside the markers), paragraph by paragraph. An unclosed marker ends at its paragraph."""
    out = []
    for line in (text or "").split("\n"):
        merged: list[Run] = []
        for r in runs(line):
            b, h = (r.bold, r.highlight) if r.text.strip() else (False, False)
            if merged and (merged[-1].bold, merged[-1].highlight) == (b, h):
                merged[-1].text += r.text
            else:
                merged.append(Run(r.text, b, h))
        parts = []
        for r in merged:
            core = r.text.strip()
            if not core:
                parts.append(r.text)
                continue
            lead = r.text[: len(r.text) - len(r.text.lstrip())]
            trail = r.text[len(r.text.rstrip()) :]
            core = f"=={core}==" if r.highlight else core
            core = f"**{core}**" if r.bold else core
            parts.append(lead + core + trail)
        out.append(re.sub(r"[ \t]+", " ", "".join(parts)).strip())
    return "\n".join(out)


def paragraphs(text: str) -> list[str]:
    return [p for p in (text or "").split("\n")]


def plain(text: str) -> str:
    """Without markup (for search, Suggest and diffs)."""
    return re.sub(r"\s+", " ", TOKEN.sub("", text or "")).strip()


def to_html(text: str, bold: bool = False) -> str:
    """Markup -> HTML: each paragraph a <p> (empty lines keep their space)."""
    return "".join(f"<p>{inline_html(p, bold) or '&nbsp;'}</p>" for p in paragraphs(text))


def inline_html(line: str, bold: bool = False) -> str:
    parts = []
    for r in runs(line, bold):
        t = html.escape(r.text)
        if r.highlight:
            t = f"<mark>{t}</mark>"
        if r.bold:
            t = f"<b>{t}</b>"
        parts.append(t)
    return "".join(parts)


def placeholders_in(text: str) -> set[str]:
    return set(PLACEHOLDER.findall(text or ""))


def unknown_placeholders(text: str, allowed) -> list[str]:
    return sorted(placeholders_in(text) - set(allowed))


def fill(text: str, values: dict[str, str]) -> str:
    """Replace the known {placeholders}; unknown ones stay as typed (they are refused on save)."""
    return PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), text or "")
