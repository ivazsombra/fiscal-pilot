# app/services/retrieval/article_lookup.py
from typing import List, Dict, Any


def try_get_article_chunks(
    conn,
    document_id: str,
    article_number: int,
    article_suffix: str = "",
    suffix_word: str = "",
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Lookup determinístico por artículo usando el esquema Ruta2:
      chunks.norm_kind = 'ARTICLE'
      chunks.norm_id   = '69-B' | '88-TER' | '69-B-BIS' | '137-BIS', etc.
    """
    # Normalización a tu convención de norm_id
    num = str(article_number).strip()
    lit = (article_suffix or "").strip().upper()
    suf = (suffix_word or "").strip().upper()

    norm_id = num
    if lit:
        norm_id += f"-{lit}"
    if suf:
        norm_id += f"-{suf}"

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
      AND c.norm_kind = 'ARTICLE'
      AND c.norm_id = %s
    ORDER BY c.chunk_id ASC
    LIMIT %s
    """

    cur = conn.cursor()
    cur.execute(sql, (document_id, norm_id, limit))
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
