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
Tu misión es dar respuestas técnicas, fundamentadas y fáciles de leer para contadores y fiscalistas.

--- 
🧠 REGLA DE ORO: CONTINUIDAD NORMATIVA
1.  **Prioridad Temporal:** Busca primero disposiciones del año 2025 o 2026.
2.  **Vigencia Extendida:** Si NO encuentras información en 2025, ESTÁS AUTORIZADO a usar documentos de 2022, 2023 o 2024, asumiendo que siguen vigentes salvo que haya una derogación explícita.
3.  **Transparencia:** Si usas una ley de años anteriores, agrega al final: 
    _"Nota: Respuesta basada en normativa [AÑO] por continuidad legal."_

---
📝 REGLAS DE FORMATO (OBLIGATORIO)
1.  **Estructura:** Usa párrafos cortos y listas con viñetas (-) para enumerar requisitos u obligaciones.
2.  **Énfasis:** Usa **negritas** para resaltar:
    * Números de Artículos (ej. **Art. 27 LISR**)
    * Reglas Misceláneas (ej. **Regla 3.5.1**)
    * Fechas clave y plazos.
3.  **Estilo:** Mantén un tono profesional pero directo. No uses saludos excesivos.
4.  Para listar requisitos u obligaciones, SIEMPRE usa viñetas con "-" (no numeración romana) y cita la referencia en negritas, por ejemplo: **Art. 27, fracc. I LISR**.

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

def generate_answer_stream(system_prompt: str, user_prompt: str) -> Generator[str, None, None]:
    stream = client.chat.completions.create(
        model=MODEL_CHAT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2,
        stream=True
    )

    for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content


# =========================
# Orquestador principal esta es la inea original def generate_response_with_rag(question: str, regimen: str = "General", ejercicio: int = 2025) -> str:
# =========================

def generate_response_with_rag(question: str, regimen: str = "General", ejercicio: int = 2025, trace: bool = False):

    conn = None
    try:
        conn = get_db_connection()

        query_vec = embed_text(question)

        evidence, used_year = retrieve_context_with_fallback(
            conn,
            query_vec,
            ejercicio,
            question=question,
            top_k=8
        )

        system_prompt = build_system_message(evidence)

        note_rule = ""
        if used_year not in (ejercicio, 0):
            note_rule = f'\n\nAl final agrega exactamente: "Nota: Respuesta basada en normativa {used_year} por continuidad legal."'

        # ---- regla especial: si es consulta por Artículo, obliga texto literal primero ----
        is_article_query = bool(re.search(r"\b(?:art(?:í|i)culo|art)\.?\s*\d+\b", question or "", re.IGNORECASE))
        literal_rule = ""
        if is_article_query:
            literal_rule = (          
                "INSTRUCCIÓN ESPECIAL (ARTÍCULO): Si la pregunta pide qué 'dice', 'establece' o 'transcribe' un Artículo, "
                "primero reproduce el TEXTO literal del Artículo tal como aparece en el contexto recuperado (sin parafrasear), "
                "en un bloque de cita. "
                "Después agrega una explicación breve en viñetas usando SIEMPRE '-'. "
                "Incluye la referencia exacta en negritas (por ejemplo: **Art. 31, fracc. IV CPEUM**). "
                "No inventes fracciones, numerales ni texto que no esté en el contexto.\n\n"
                "Si el contexto NO contiene explícitamente el número de fracción (I, II, III, IV), indícalo de forma expresa "
                "y cita únicamente el texto disponible.\n\n"
            )

        user_prompt = (
            f"Ejercicio fiscal solicitado: {ejercicio}\n"
            f"Ejercicio de evidencia recuperada: {used_year}\n"
            f"Régimen (si aplica): {regimen}\n"
            f"Pregunta: {question}\n\n"
            f"{literal_rule}"
            f"Responde específicamente a la pregunta usando SOLO el contexto recuperado. "
            f"Si enumeras puntos, usa SIEMPRE viñetas con '-' (no párrafos continuos ni numeración). "
            f"Obligatorio: cita la referencia exacta en negritas (ej. **Art. 27, fracc. I LISR**)."
            f"{note_rule}"
        )

        response_text = ""
        for chunk in generate_answer_stream(system_prompt, user_prompt=user_prompt):
            response_text += chunk

        debug = {}
        if trace:
            debug = {
                "router": {
                    "candidates": resolve_candidate_documents(question),
                    },
                    "retrieval": {
                        "used_year": used_year,
                        "evidence_count": len(evidence),
                        "sources_preview": [
                            {
                                "source_filename": ev.get("source_filename", ""),
                                "doc_type": ev.get("doc_type", ""),
                            }
                            for ev in evidence
                        ],
                    },
            }
        return response_text, debug


    except Exception as e:
        err = f"Error en el motor RAG: {str(e)}"
        if trace:
            return err, {"error": str(e)}
        return err, {}
    finally:
        if conn:
            conn.close()
