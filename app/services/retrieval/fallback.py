# app/services/retrieval/fallback.py
# VERSIÓN 3.0 - Corregido error "tuple index out of range" y lógica de vigencia.

import re
from typing import List, Dict, Any, Tuple, Optional
from .article_lookup import try_get_article_chunks
from .doc_router import resolve_candidate_documents
from .vector_retrieval import retrieve_context

ARTICLE_REF_RE = re.compile(r"\b(\d{1,3})\s*[-–]\s*([a-zA-Z])\b(\s*bis)?", re.IGNORECASE)


def retrieve_by_keywords(conn, keywords: List[str], ejercicio: int, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Búsqueda complementaria por palabras clave (ILIKE).
    Útil cuando la búsqueda vectorial no encuentra términos específicos.
    
    Nota: exercise_year = 0 indica leyes federales (vigentes siempre)
    """
    if not keywords:
        return []
    
    # Construir condiciones OR para cada keyword
    conditions = []
    for kw in keywords:
        safe_kw = kw.replace("'", "''").replace("%", "\\%")
        conditions.append(f"c.text ILIKE '%{safe_kw}%'")
    
    where_keywords = " OR ".join(conditions)
    
    # Query con lógica de vigencia: exercise_year = 0 (leyes) o año específico
    query = f"""
        SELECT 
            c.text,
            c.document_id,
            COALESCE(d.source_filename, '') as source_filename,
            COALESCE(d.doc_type, '') as doc_type,
            COALESCE(d.exercise_year, 0) as exercise_year
        FROM chunks c
        LEFT JOIN documents d ON c.document_id = d.document_id
        WHERE ({where_keywords})
          AND (d.exercise_year = 0 OR d.exercise_year = %s OR d.exercise_year IS NULL)
        ORDER BY 
            CASE WHEN d.doc_type = 'ley' THEN 1
                 WHEN d.doc_type = 'rmf' THEN 2
                 ELSE 3 END,
            d.exercise_year DESC
        LIMIT %s
    """
    
    try:
        with conn.cursor() as cur:
            cur.execute(query, (ejercicio, limit))
            rows = cur.fetchall()
            
            results = []
            for row in rows:
                results.append({
                    "chunk_text": row[0] if len(row) > 0 else "",
                    "document_id": row[1] if len(row) > 1 else "",
                    "source_filename": row[2] if len(row) > 2 else "",
                    "doc_type": row[3] if len(row) > 3 else "",
                    "exercise_year": row[4] if len(row) > 4 else 0,
                    "metadata": {},
                    "source": "keyword"
                })
            return results
    except Exception as e:
        print(f"Error en búsqueda por keywords: {e}")
        import traceback
        traceback.print_exc()
        return []


def merge_results(vector_results: List[Dict], keyword_results: List[Dict], top_k: int) -> List[Dict]:
    """
    Combina resultados de búsqueda vectorial y por keywords.
    Elimina duplicados y prioriza resultados vectoriales.
    """
    seen_texts = set()
    merged = []
    
    # Primero agregamos resultados vectoriales (mayor relevancia)
    for r in vector_results:
        text_preview = (r.get("chunk_text") or "")[:200]
        if text_preview and text_preview not in seen_texts:
            seen_texts.add(text_preview)
            r["source"] = "vector"
            merged.append(r)
    
    # Luego agregamos resultados por keyword que no estén duplicados
    for r in keyword_results:
        text_preview = (r.get("chunk_text") or "")[:200]
        if text_preview and text_preview not in seen_texts:
            seen_texts.add(text_preview)
            merged.append(r)
    
    return merged[:top_k]


def retrieve_context_with_fallback(
    conn, 
    query_vec: List[float], 
    ejercicio: int, 
    question: str, 
    top_k: int = 12,
    keywords: Optional[List[str]] = None
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Recuperación de contexto con fallback jerárquico y búsqueda híbrida.
    
    Nota sobre vigencia:
    - exercise_year = 0: Leyes federales (vigentes siempre)
    - exercise_year = 2025: RMF, Anexos del ejercicio 2025
    """
    q = (question or "").lower()
    has_regla = bool(re.search(r"(?i)\bregla\b", question or ""))
    has_rmf = bool(re.search(r"(?i)\brmf\b", question or ""))    

    # 1. CAMINO RÁPIDO: Búsqueda por Artículo Directo
    m = ARTICLE_REF_RE.search(question or "")
    if m:
    #    IMPORTANTE: si el usuario dice "Regla ...", NO debemos confundirlo con Artículo N-A.
     m = ARTICLE_REF_RE.search(question or "")
     if m and not has_regla:    
        art_num = int(m.group(1))
        art_suffix = (m.group(2) or "").upper().strip()
        wants_bis = bool(m.group(3))
        
        for doc_id in resolve_candidate_documents(question):
            ev_direct = try_get_article_chunks(conn, doc_id, art_num, art_suffix, limit=12)
            if ev_direct:
                if not wants_bis:
                    ev_direct = [e for e in ev_direct if "bis" not in (e.get("chunk_text") or "").lower()]
                return ev_direct, 0

    # 2. BÚSQUEDA VECTORIAL INTELIGENTE (Jerarquía de Prevalencia)
    years_to_check = [ejercicio, 2024, 2023, 2022] if ejercicio >= 2025 else [ejercicio]
    
    all_evidence = []
    final_year = ejercicio
    # Preferencias para vector según intención:
    prefer_doc_type = None
    include_base_year0 = True
    include_null_year = True
    if has_regla or has_rmf:
        prefer_doc_type = "rmf"
        include_base_year0 = False
        include_null_year = False

    for y in years_to_check:
        # Búsqueda vectorial principal
        ev_vector = retrieve_context(
            conn,
            query_vec,
            y,
            top_k=top_k,
            prefer_doc_type=prefer_doc_type,
            include_base_year0=include_base_year0,
            include_null_year=include_null_year,
        )
        
        # Búsqueda complementaria por keywords (incluye leyes con year=0)
        ev_keywords = []
        if keywords:
            ev_keywords = retrieve_by_keywords(conn, keywords, y, limit=top_k // 2)
        
        # Combinar resultados
        ev = merge_results(ev_vector, ev_keywords, top_k)
        
        if ev:
            # --- LÓGICA DE ROBUSTEZ PARA RMF Y ANEXOS ---
            compilados = [e for e in ev if "compilado" in (e.get("source_filename") or "").lower()]
            modificaciones = [e for e in ev if "modificacion" in (e.get("source_filename") or "").lower()]
            
            if compilados:
                all_evidence = compilados[:top_k]
            elif modificaciones:
                all_evidence = modificaciones[:top_k]
            else:
                all_evidence = ev
                
            final_year = y
            break

    return all_evidence, final_year
