import re
from typing import List, Tuple

DOC_ALIASES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(cpeum|constituci[oó]n|constitucional)\b", re.IGNORECASE),
     "CONSTITUCION_POLITICA_ESTADOS_UNIDOS_MEXICANOS"),
    (re.compile(r"\b(lisr|isr|impuesto sobre la renta|renta)\b", re.IGNORECASE),
     "LEY_DEL_IMPUESTO_SOBRE_LA_RENTA"),
     (re.compile(r"\b(cff|c[oó]digo fiscal(?: de la federaci[oó]n)?)\b", re.IGNORECASE),
 "CODIGO_FISCAL_DE_LA_FEDERACION"),
   
]

BASE_LEGAL_DOCS = [
    "CONSTITUCION_POLITICA_ESTADOS_UNIDOS_MEXICANOS",
    "CODIGO_FISCAL_DE_LA_FEDERACION",
    "LEY_DEL_IMPUESTO_SOBRE_LA_RENTA",
]
ARTICLE_RE = re.compile(r"\b(?:art(?:í|i)culo|art)\b|\b\d{1,3}\s*-\s*[A-Za-z]\b", re.IGNORECASE)
CFF_RE = re.compile(r"\b(cff|c[oó]digo fiscal)\b", re.IGNORECASE)
def resolve_candidate_documents(question: str) -> List[str]:
    q = question or ""
    resolved: List[str] = []
    for rx, doc_id in DOC_ALIASES:
        if rx.search(q):
            resolved.append(doc_id)
    return resolved or BASE_LEGAL_DOCS
