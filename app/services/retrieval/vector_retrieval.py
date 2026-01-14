from typing import List, Dict, Any

def _vec_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"

def retrieve_context(
    conn,
    query_vec: List[float],
    ejercicio: int,
    top_k: int = 8,
    prefer_doc_type: str | None = None,
    exclude_doc_type: str | None = None,
    include_base_year0: bool = True,
    include_null_year: bool = True,
) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    qv = _vec_literal(query_vec)

    year_clause = "d.exercise_year = %s"
    if include_base_year0 and include_null_year:
        year_clause = "(d.exercise_year = %s OR d.exercise_year = 0 OR d.exercise_year IS NULL)"
    elif include_base_year0:
        year_clause = "(d.exercise_year = %s OR d.exercise_year = 0)"
    elif include_null_year:
        year_clause = "(d.exercise_year = %s OR d.exercise_year IS NULL)"

    sql = f"""
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
        1 - (c.embedding <=> %s::vector) as score
    FROM public.chunks c
    JOIN public.documents d ON c.document_id = d.document_id
    WHERE {year_clause}
      AND (%s IS NULL OR d.doc_type = %s)
      AND (%s IS NULL OR d.doc_type <> %s)
    ORDER BY c.embedding <=> %s::vector
    LIMIT %s
    """

    cur.execute(
        sql,
        (qv, ejercicio, prefer_doc_type, prefer_doc_type, exclude_doc_type, exclude_doc_type, qv, top_k)
    )
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
            "source": "vector",
        })

    return evidence
