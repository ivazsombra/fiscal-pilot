# app/services/retrieval/rmf_rule_lookup.py
import re
from typing import List, Dict, Any, Optional


def try_get_rmf_rule_chunks(
    conn,
    ejercicio: int,
    rule_id: str,
    prefer_document_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Lookup determinístico RMF por norm_id (ej: '2.1.1', '2.7.1.46').

    Requisitos en DB:
      - documents.doc_type = 'rmf'
      - documents.exercise_year = ejercicio
      - chunks.norm_kind = 'RULE'
      - chunks.norm_id = rule_id
    """

    rule_id = (rule_id or "").strip()

    sql = """
    SELECT
      c.chunk_id,
      c.document_id,
      c.norm_kind,
      c.norm_id,
      d.source_filename,
      c.text,
      d.doc_type,
      d.published_date,
      c.page_start,
      c.page_end,
      1.0 as score
    FROM public.chunks c
    JOIN public.documents d ON c.document_id = d.document_id
    WHERE d.doc_type = 'rmf'
      AND d.exercise_year = %s
      AND c.norm_kind = 'RULE'
      AND c.norm_id = %s
    ORDER BY
      CASE WHEN %s IS NOT NULL AND c.document_id = %s THEN 0 ELSE 1 END,
      c.page_start NULLS LAST,
      c.chunk_id ASC
    LIMIT %s
    """

    cur = conn.cursor()
    cur.execute(sql, (ejercicio, rule_id, prefer_document_id, prefer_document_id, limit))
    rows = cur.fetchall()
    cur.close()

    evidence: List[Dict[str, Any]] = []
    for r in rows:
        pub_date = r[7].isoformat() if r[7] else "S/F"
        evidence.append({
            "chunk_id": r[0],
            "document_id": r[1],
            "norm_kind": r[2],
            "norm_id": r[3],
            "source_filename": r[4],
            "chunk_text": r[5],
            "doc_type": r[6],
            "published_date": pub_date,
            "page_start": r[8],
            "page_end": r[9],
            "score": float(r[10]),
            "source": "rmf_rule_lookup",
        })
        # ------------------------------------------------------------
    # Post-proceso: preferir el "cuerpo" de la regla (inicia con "2.x.x.")
    # y evitar encabezados/índices tipo "regla 2.x.x."
    # ------------------------------------------------------------
    body_pat = re.compile(rf"(?im)^\s*{re.escape(rule_id)}\.\s")

    body = [e for e in evidence if body_pat.search((e.get("chunk_text") or ""))]
    if body:
        evidence = body
    
    return evidence
