# app/services/rag_engine.py

import os
import re
import psycopg2
from typing import List, Dict, Any, Generator

from openai import OpenAI

from app.core.config import OPENAI_API_KEY, DIRECT_URL, MODEL_EMBED, MODEL_CHAT
from app.services.retrieval.fallback import retrieve_context_with_fallback  # <- modular
from app.services.retrieval.doc_router import resolve_candidate_documents


client = OpenAI(api_key=OPENAI_API_KEY)

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

# --- REEMPLAZO EN app/services/rag_engine.py ---

def generate_answer_stream(system_prompt: str, user_prompt: str, history: List[Dict[str, str]] = None) -> Generator[str, None, None]:
    # Construimos los mensajes incluyendo el historial previo
    messages = [{"role": "system", "content": system_prompt}]
    
    if history:
        # Añadimos los últimos 4 mensajes para mantener contexto sin saturar
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

def generate_response_with_rag(question: str, regimen: str = "General", ejercicio: int = 2025, trace: bool = False, history: List[Dict[str, str]] = None):
    conn = None
    try:
        conn = get_db_connection()
        query_vec = embed_text(question)

        # El fallback ahora usa nuestra nueva lógica jerárquica
        evidence, used_year = retrieve_context_with_fallback(
            conn, query_vec, ejercicio, question=question, top_k=8
        )

        system_prompt = build_system_message(evidence)
        
        # Reglas de formato y notas (se mantienen igual)
        note_rule = f'\n\nNota: Basado en normativa {used_year}.' if used_year not in (ejercicio, 0) else ""
        
        user_prompt = (
            f"Pregunta actual: {question}\n"
            f"Contexto: Ejercicio {ejercicio}, Régimen {regimen}.\n"
            f"Responde usando SOLO el contexto recuperado y mantén la continuidad de la charla."
            f"{note_rule}"
        )

        response_text = ""
        # Pasamos el historial a la generación
        for chunk in generate_answer_stream(system_prompt, user_prompt, history):
            response_text += chunk

        debug = {"used_year": used_year, "evidence_count": len(evidence)} if trace else {}
        return response_text, debug

    except Exception as e:
        return f"Error: {str(e)}", {"error": str(e)}
    finally:
        if conn: conn.close()

