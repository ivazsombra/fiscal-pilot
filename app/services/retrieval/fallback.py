# app/services/retrieval/fallback.py
# VERSIÓN 2.0 - Con búsqueda híbrida (vectorial + keywords)

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
    """
    if not keywords:
        return []
    
    # Construir condiciones OR para cada keyword
    conditions = []
    for kw in keywords:
        safe_kw = kw.replace("'", "''").replace("%", "\\%")
        conditions.append(f"c.text ILIKE '%{safe_kw}%'")
    
    where_keywords = " OR ".join(conditions)
    
    query = f"""
        SELECT 
            c.text AS chunk_text,
            c.document_id,
            d.source_filename,
            d.doc_type,
            d.exercise_year,
            c.metadata
        FROM chunks c
        JOIN documents d ON c.document_id = d.document_id
        WHERE ({where_keywords})
          AND (d.exercise_year = %s OR d.exercise_year = 0 OR d.exercise_year IS NULL)
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
                    "chunk_text": row[0],
                    "document_id": row[1],
                    "source_filename": row[2],
                    "doc_type": row[3],
                    "exercise_year": row[4],
                    "metadata": row[5],
                    "source": "keyword"  # Marcamos el origen
                })
            return results
    except Exception as e:
        print(f"Error en búsqueda por keywords: {e}")
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
        text_hash = hash(r.get("chunk_text", "")[:200])
        if text_hash not in seen_texts:
            seen_texts.add(text_hash)
            r["source"] = "vector"
            merged.append(r)
    
    # Luego agregamos resultados por keyword que no estén duplicados
    for r in keyword_results:
        text_hash = hash(r.get("chunk_text", "")[:200])
        if text_hash not in seen_texts:
            seen_texts.add(text_hash)
            merged.append(r)
    
    return merged[:top_k]


def retrieve_context_with_fallback(
    conn, 
    query_vec: List[float], 
    ejercicio: int, 
    question: str, 
    top_k: int = 12,
    keywords: Optional[List[str]] = None  # NUEVO parámetro
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Recuperación de contexto con fallback jerárquico y búsqueda híbrida.
    
    Args:
        conn: Conexión a la base de datos
        query_vec: Vector de embedding de la consulta
        ejercicio: Año fiscal
        question: Pregunta original del usuario
        top_k: Número máximo de resultados
        keywords: Lista de palabras clave para búsqueda complementaria
    
    Returns:
        Tuple con lista de evidencia y año utilizado
    """
    q = (question or "").lower()
    
    # 1. CAMINO RÁPIDO: Búsqueda por Artículo Directo
    m = ARTICLE_REF_RE.search(question or "")
    if m:
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

    for y in years_to_check:
        # Búsqueda vectorial principal
        ev_vector = retrieve_context(conn, query_vec, y, top_k=top_k)
        
        # NUEVO: Búsqueda complementaria por keywords
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
