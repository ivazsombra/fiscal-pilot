import re
from typing import List, Dict, Any, Tuple

from .article_lookup import try_get_article_chunks
from .doc_router import resolve_candidate_documents
from .vector_retrieval import retrieve_context

ARTICLE_REF_RE = re.compile(
    r"\b(\d{1,3})\s*[-–]\s*([a-zA-Z])\b(\s*bis)?",
    re.IGNORECASE
)
ARTICLE_CODE_RE = re.compile(r"\b(\d{1,3})\s*[-–]\s*([a-zA-Z])\b(\s*bis)?", re.IGNORECASE)

def retrieve_context_with_fallback(
    conn,
    query_vec: List[float],
    ejercicio: int,
    question: str,
    top_k: int = 8
) -> Tuple[List[Dict[str, Any]], int]:
    q = (question or "").lower()

    # Fast path: Artículo N (genérico por doc_router)
    m = ARTICLE_REF_RE.search(question or "")
    m2 = ARTICLE_CODE_RE.search(question or "")

    if m or m2:
        if m:
            art_num = int(m.group(1))
            art_suffix = (m.group(2) or "").upper().strip()
            wants_bis = False
        else:
            art_num = int(m2.group(1))
            art_suffix = (m2.group(2) or "").upper().strip()
            wants_bis = bool(m2.group(3))

        for doc_id in resolve_candidate_documents(question):
            ev_direct = try_get_article_chunks(
                conn,
                document_id=doc_id,
                article_number=art_num,
                article_suffix=art_suffix,
                limit=max(12, top_k)
            )

            # Si el usuario NO pidió "bis", filtra chunks que claramente sean "Bis"
            if ev_direct and not wants_bis:
                ev_direct = [
                    ev for ev in ev_direct
                    if not re.search(rf"\b{art_num}\s*[-–]?\s*{art_suffix}\s+bis\b", (ev.get("chunk_text") or "").lower())
                ]

            if ev_direct:
                return ev_direct, 0

    # --- resto: tu lógica actual RMF/Anexo/DOF + continuidad ---
    wants_rmf = ("rmf" in q) or ("miscel" in q) or ("miscelánea" in q)
    mentions_anexo = ("anexo" in q)
    mentions_dof = ("dof" in q) or ("diario oficial" in q)

    general_deductions = any(k in q for k in [
        "requisitos", "deduccion", "deducciones", "deducción", "deducible", "autorizada",
        "estrictamente indispensable", "cfdi", "comprobante", "forma de pago", "isr", "lisr", "impuesto sobre la renta"
    ])

    prefer_doc_type = "rmf" if wants_rmf else None

    if general_deductions:
        prefer_doc_type_first = "ley"
        prefer_doc_type_second = "rmf"
    else:
        prefer_doc_type_first = "rmf" if wants_rmf else None
        prefer_doc_type_second = None

    exclude_doc_type_first_pass = None
    if not mentions_anexo and not mentions_dof:
        exclude_doc_type_first_pass = "anexo"

    candidates: List[int] = [ejercicio, 2024, 2023, 2022] if ejercicio in (2025, 2026) else [ejercicio]

    for y in candidates:
        if prefer_doc_type_first:
            ev = retrieve_context(conn, query_vec, y, top_k=top_k, prefer_doc_type=prefer_doc_type_first, exclude_doc_type=exclude_doc_type_first_pass)
            if ev:
                return ev, y

        if prefer_doc_type_second:
            ev = retrieve_context(conn, query_vec, y, top_k=top_k, prefer_doc_type=prefer_doc_type_second, exclude_doc_type=exclude_doc_type_first_pass)
            if ev:
                return ev, y

        ev = retrieve_context(conn, query_vec, y, top_k=top_k, prefer_doc_type=prefer_doc_type, exclude_doc_type=exclude_doc_type_first_pass)
        if ev:
            return ev, y

        if prefer_doc_type:
            ev = retrieve_context(conn, query_vec, y, top_k=top_k, prefer_doc_type=prefer_doc_type, exclude_doc_type=None)
            if ev:
                return ev, y

        ev = retrieve_context(conn, query_vec, y, top_k=top_k, prefer_doc_type=None, exclude_doc_type=None)
        if ev:
            return ev, y

    return [], ejercicio
