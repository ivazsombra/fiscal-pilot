import re
from typing import List, Tuple

DOC_ALIASES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(cpeum|constituci[oó]n|constitucional)\b", re.IGNORECASE),
     "CONSTITUCION_POLITICA_ESTADOS_UNIDOS_MEXICANOS"),
    (re.compile(r"\b(lisr|isr|impuesto sobre la renta|renta)\b", re.IGNORECASE),
     "LEY_DEL_IMPUESTO_SOBRE_LA_RENTA"),
    # Cuando cargues más leyes:
    # (re.compile(r"\b(cff|c[oó]digo fiscal)\b", re.IGNORECASE), "CODIGO_FISCAL_DE_LA_FEDERACION"),
    # (re.compile(r"\b(iva|impuesto al valor agregado)\b", re.IGNORECASE), "LEY_DEL_IMPUESTO_AL_VALOR_AGREGADO"),
]

BASE_LEGAL_DOCS = [
    "CONSTITUCION_POLITICA_ESTADOS_UNIDOS_MEXICANOS",
    "LEY_DEL_IMPUESTO_SOBRE_LA_RENTA",
]

def resolve_candidate_documents(question: str) -> List[str]:
    q = question or ""
    resolved: List[str] = []
    for rx, doc_id in DOC_ALIASES:
        if rx.search(q):
            resolved.append(doc_id)
    return resolved or BASE_LEGAL_DOCS
