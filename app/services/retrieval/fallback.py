# app/services/retrieval/fallback.py
import re
from typing import List, Dict, Any, Tuple
from .article_lookup import try_get_article_chunks
from .doc_router import resolve_candidate_documents
from .vector_retrieval import retrieve_context

ARTICLE_REF_RE = re.compile(r"\b(\d{1,3})\s*[-–]\s*([a-zA-Z])\b(\s*bis)?", re.IGNORECASE)

def retrieve_context_with_fallback(
    conn, query_vec: List[float], ejercicio: int, question: str, top_k: int = 8
) -> Tuple[List[Dict[str, Any]], int]:
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
                # Filtramos el "Bis" si no se pidió expresamente
                if not wants_bis:
                    ev_direct = [e for e in ev_direct if "bis" not in (e.get("chunk_text") or "").lower()]
                return ev_direct, 0

    # 2. BÚSQUEDA VECTORIAL INTELIGENTE (Jerarquía de Prevalencia)
    # Definimos los años a buscar (Prioridad: Ejercicio solicitado -> Años anteriores)
    years_to_check = [ejercicio, 2024, 2023, 2022] if ejercicio >= 2025 else [ejercicio]
    
    all_evidence = []
    final_year = ejercicio

    for y in years_to_check:
        # Traemos candidatos del Router (Leyes, Reglamentos, etc.)
        doc_candidates = resolve_candidate_documents(question)
        
        # Buscamos en los documentos sugeridos
        ev = retrieve_context(conn, query_vec, y, top_k=top_k)
        
        if ev:
            # --- LÓGICA DE ROBUSTEZ PARA RMF Y ANEXOS ---
            # Si hay archivos "Compilados" o "Modificaciones", les damos prioridad
            compilados = [e for e in ev if "compilado" in (e.get("source_filename") or "").lower()]
            modificaciones = [e for e in ev if "modificacion" in (e.get("source_filename") or "").lower()]
            
            if compilados:
                all_evidence = compilados[:top_k]
            elif modificaciones:
                all_evidence = modificaciones[:top_k]
            else:
                all_evidence = ev
                
            final_year = y
            break # Encontramos información válida, dejamos de buscar en años anteriores

    return all_evidence, final_year
