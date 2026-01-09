from typing import List, Dict, Any

def try_get_article_chunks(conn, document_id: str, article_number: int, limit: int = 20) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    sql = """
    SELECT
      c.chunk_id,
      d.source_filename,
      c.text,
      d.doc_type,
      d.published_date,
      c.page_start,
      c.page_end,
      1.0 as score
    FROM public.chunks c
    JOIN public.documents d ON c.document_id = d.document_id
    WHERE c.document_id = %s
      AND (c.metadata->>'article_number') = %s
    ORDER BY c.chunk_id ASC
    LIMIT %s
    """
    cur.execute(sql, (document_id, str(article_number), limit))
    rows = cur.fetchall()
    cur.close()

    evidence: List[Dict[str, Any]] = []
    for r in rows:
        pub_date = r[4].isoformat() if r[4] else "S/F"
        evidence.append({
            "chunk_id": r[0],
            "source_filename": r[1],
            "chunk_text": r[2],
            "doc_type": r[3],
            "published_date": pub_date,
            "page_start": r[5],
            "page_end": r[6],
            "score": float(r[7]),
        })
    return evidence
