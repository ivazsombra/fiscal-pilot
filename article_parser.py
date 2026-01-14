"""Article header detection & canonical tokenization.

Canonical token rules (Jan 2026):
- Sufijos con guión y en MAYÚSCULAS: 69-B-BIS, 1-A-TER
- Transitorios con prefijo: TRANS-PRIMERO, TRANS-DECIMO
- Se ignoran marcas ordinales: 1o, 1º -> 1

Devuelve un *token canónico* (no incluye ley/version).
La unicidad global se logra con (document_id, token) en la capa de BD.
"""

from __future__ import annotations

import re
import unicodedata

ARTICLE_SUFFIXES = r"(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies)"
TRANS_ORDINALS = r"(?:UNICO|ÚNICO|PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|SEPTIMO|SÉPTIMO|OCTAVO|NOVENO|DECIMO|DÉCIMO)"

ARTICLE_HDR_RE = re.compile(
    rf"""(?mx)
    ^\s*
    Art[ií]culo
    \s+
    (?:
        (?P<num>\d+)
        (?P<ord>[oº])?
        (?:\s*[-–—]\s*(?P<lit>[A-Z]))?
        (?:\s+(?P<suf>{ARTICLE_SUFFIXES}))?
      |
        (?P<trans>{TRANS_ORDINALS})
    )
    \s*
    (?:[.\-–—:])?
    """,
    re.IGNORECASE,
)


def _strip_accents(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(ch)
    )


def parse_article_header(line: str) -> str | None:
    """Return canonical article token if the line is an article header, else None."""
    m = ARTICLE_HDR_RE.match(line or "")
    if not m:
        return None
    gd = m.groupdict()

    if gd.get("trans"):
        trans = _strip_accents(gd["trans"].upper())
        return f"TRANS-{trans}"

    num = gd.get("num") or ""
    lit = (gd.get("lit") or "").upper()
    suf = (gd.get("suf") or "").upper()

    token = f"{num}"
    if lit:
        token += f"-{lit}"
    if suf:
        token += f"-{suf}"
    return token
