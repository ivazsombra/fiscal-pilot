# app/services/rag_engine.py
# VERSIÓN 2.0 - Con Query Expansion y top_k dinámico

import os
import re
import psycopg2
from typing import List, Dict, Any, Generator

from openai import OpenAI

from app.core.config import OPENAI_API_KEY, DIRECT_URL, MODEL_EMBED, MODEL_CHAT

from app.services.retrieval.fallback import retrieve_context_with_fallback
from app.services.retrieval.doc_router import resolve_candidate_documents
from app.services.retrieval.query_expansion import expand_query  # NUEVO
from app.services.retrieval.rmf_rule_lookup import try_get_rmf_rule_chunks


client = OpenAI(api_key=OPENAI_API_KEY)

# Obtener top_k de variables de entorno (default 12)
TOP_K = int(os.getenv("TOP_K_DEFAULT", 12))

SYSTEM_PROMPT = """
Eres un Asesor Fiscal Experto (IA) especializado en la legislación mexicana para el ejercicio 2025.
Tu misión es dar respuestas técnicas, fundamentadas y con continuidad lógica.

--- 
🧠 REGLA DE ORO: CONTINUIDAD Y MEMORIA
1.  **Anclaje de Contexto:** Si el usuario pregunta por una "fracción", "inciso" o "párrafo" sin mencionar el artículo, ASUME que se refiere al ÚLTIMO artículo o tema discutido en la conversación previa.
2.  **Prioridad de Régimen:** Si el tema es "Régimen General", prioriza siempre la LISR y el CFF. Solo menciona otras leyes (como Aduanera o IVA) si la pregunta lo exige explícitamente.
3.  **Vigencia:** Si usas normativa de años anteriores (2022-2024), acláralo con la nota de continuidad legal.

---
📝 REGLAS DE FORMATO Y RESPUESTA
1.  **Cita Literal:** Si se pide un artículo, primero transcribe el fragmento relevante en un bloque de cita.
2.  **Estructura:** Usa párrafos cortos y listas con viñetas (-).
3.  **Énfasis:** Usa **negritas** para artículos (ej. **Art. 27 LISR**) y reglas (ej. **Regla 3.5.1**).
4.  **Antialucinación:** Si el contexto recuperado no contiene la respuesta, di: "No cuento con el fragmento específico en mi base de datos actual", y sugiere al usuario el artículo o ley donde podría encontrarlo.

---
CONTEXTO RECUPERADO DE LA BASE DE DATOS:
{context}
"""



# =========================
# DB + Embeddings
# =========================

def get_db_connection():
    conn_str = DIRECT_URL or os.getenv("DATABASE_URL")
    if not conn_str:
        raise ValueError("No se encontró la cadena de conexión a la base de datos.")
    return psycopg2.connect(conn_str)


def embed_text(text: str) -> List[float]:
    clean_text = (text or "").replace("\n", " ")
    resp = client.embeddings.create(input=[clean_text], model=MODEL_EMBED)
    return resp.data[0].embedding


# =========================
# Prompt build
# =========================

def build_system_message(evidence: List[Dict[str, Any]]) -> str:
    context_parts: List[str] = []
    char_limit = 400000
    current_chars = 0

    for i, ev in enumerate(evidence, 1):
        txt = (
            f"\n--- DOCUMENTO {i} ---\n"
            f"Fuente: {ev.get('source_filename','')}\n"
            f"Tipo: {ev.get('doc_type','')}\n"
            f"Texto:\n{ev.get('chunk_text','')}\n"
        )
        if current_chars + len(txt) < char_limit:
            context_parts.append(txt)
            current_chars += len(txt)
        else:
            context_parts.append("... [Límite de seguridad alcanzado] ...")
            break

    full_context_str = "\n".join(context_parts) or "No se encontró información específica en la base de conocimientos para este ejercicio."
    return SYSTEM_PROMPT.format(context=full_context_str)


# =========================
# LLM streaming
# =========================

def generate_answer_stream(system_prompt: str, user_prompt: str, history: List[Dict[str, str]] = None) -> Generator[str, None, None]:
    messages = [{"role": "system", "content": system_prompt}]
    
    if history:
        messages.extend(history[-4:])
        
    messages.append({"role": "user", "content": user_prompt})

    stream = client.chat.completions.create(
        model=MODEL_CHAT,
        messages=messages,
        temperature=0.2,
        stream=True
    )

    for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content


def generate_response_with_rag(
    question: str,
    regimen: str = "General",
    ejercicio: int = 2025,
    trace: bool = False,
    history: List[Dict[str, str]] = None
):
    conn = None
    try:
        conn = get_db_connection()

        evidence: List[Dict[str, Any]] = []
        used_year: int = ejercicio
        expanded_question: str = question
        keywords: List[str] = []

        # ------------------------------------------------------------
        # 1) RMF: lookup exacto si la pregunta menciona "Regla X.X.X"
        # ------------------------------------------------------------
        m_rule = re.search(r"(?i)\bregla\s+(\d+(?:\.\d+){1,5})\b", question or "")
        if m_rule:
            rule_id = m_rule.group(1)

            # Opcional: si quieres forzar un RMF base por año desde env:
            # set RMF_BASE_DOC_ID_2025=RMF_2025-30122024, etc.
            prefer_doc = os.getenv(f"RMF_BASE_DOC_ID_{ejercicio}", None)

            evidence = try_get_rmf_rule_chunks(
                conn,
                ejercicio=ejercicio,
                rule_id=rule_id,
                prefer_document_id=prefer_doc,
                limit=TOP_K,
            )
            if evidence:
                used_year = ejercicio
                expanded_question = question
                keywords = []

        # ------------------------------------------------------------
        # 2) Si no hubo match exacto, seguimos con vector + fallback
        # ------------------------------------------------------------
        if not evidence:
            expanded_question, keywords = expand_query(question)
            query_vec = embed_text(expanded_question)

            evidence, used_year = retrieve_context_with_fallback(
                conn,
                query_vec,
                ejercicio,
                question=question,
                top_k=TOP_K,
                keywords=keywords
            )

        # ------------------------------------------------------------
        # 3) Construcción de prompt + respuesta
        # ------------------------------------------------------------
        system_prompt = build_system_message(evidence)

        note_rule = f"\n\nNota: Basado en normativa {used_year}." if used_year not in (ejercicio, 0) else ""

        user_prompt = (
            f"Pregunta actual: {question}\n"
            f"Contexto: Ejercicio {ejercicio}, Régimen {regimen}.\n"
            f"Responde usando SOLO el contexto recuperado y mantén la continuidad de la charla."
            f"{note_rule}"
        )

        response_text = ""
        for chunk in generate_answer_stream(system_prompt, user_prompt, history):
            response_text += chunk

        debug = {}
        if trace:
            route_used = "vector_fallback"
            if any((e.get("source") == "rmf_rule_lookup") for e in evidence):
                route_used = "rmf_rule_lookup"
            elif any((e.get("source") == "article_lookup") for e in evidence):
                route_used = "article_lookup"

            debug = {
                "route_used": route_used,
                "used_year": used_year,
                "evidence_count": len(evidence),
                "expanded_query": expanded_question,
                "keywords": keywords,
                "sources": [
                    {
                        "chunk_id": e.get("chunk_id"),
                        "document_id": e.get("document_id"),
                        "norm_kind": e.get("norm_kind"),
                        "norm_id": e.get("norm_id"),
                        "doc_type": e.get("doc_type"),
                        "source_filename": e.get("source_filename"),
                        "page_start": e.get("page_start"),
                        "page_end": e.get("page_end"),
                        "score": e.get("score"),
                        "source": e.get("source"),
                        "excerpt": (e.get("chunk_text") or "")[:200],
                    }
                    for e in evidence[:8]
                ],
            }

        return response_text, debug

    except Exception as e:
        return f"Error: {str(e)}", {"error": str(e)}
    finally:
        if conn:
            conn.close()


