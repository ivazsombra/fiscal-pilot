import os
import psycopg2
from typing import List, Dict, Any, Generator, Tuple
from openai import OpenAI

from app.core.config import OPENAI_API_KEY, DIRECT_URL, MODEL_EMBED, MODEL_CHAT

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
    clean_text = text.replace("\n", " ")
    resp = client.embeddings.create(input=[clean_text], model=MODEL_EMBED)
    return resp.data[0].embedding

def _vec_literal(vec: List[float]) -> str:
    # pgvector literal: [0.1,0.2,0.3]
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"

# =========================
# Retrieval (año exacto)
# =========================

def retrieve_context(conn, query_vec: List[float], ejercicio: int, top_k: int = 8) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    qv = _vec_literal(query_vec)

    sql = """
    SELECT 
        c.chunk_id,
        d.source_filename,
        c.text,
        d.doc_type,
        d.published_date,
        c.page_start,
        c.page_end,
        1 - (c.embedding <=> %s::vector) as score
    FROM public.chunks c
    JOIN public.documents d ON c.document_id = d.document_id
    WHERE d.exercise_year = %s
    ORDER BY c.embedding <=> %s::vector
    LIMIT %s
    """

    cur.execute(sql, (qv, ejercicio, qv, top_k))
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

# =========================
# Continuidad normativa (fallback)
# =========================

def retrieve_context_with_fallback(
    conn,
    query_vec: List[float],
    ejercicio: int,
    top_k: int = 8
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Intenta recuperar evidencia:
      - Primero el ejercicio solicitado
      - Si no hay evidencia y el ejercicio es 2025/2026 -> fallback 2024, 2023, 2022
      - Si es otro año -> fallback hacia atrás hasta 2022
    Devuelve: (evidence, used_year)
    """

    candidates: List[int] = []

    # Prioridad temporal en tu producto (2025/2026), con fallback 2024..2022
    if ejercicio in (2025, 2026):
        candidates.append(ejercicio)
        # Si quisieras intentar el "otro" cercano, descomenta:
        # candidates.append(2026 if ejercicio == 2025 else 2025)
        candidates.extend([2024, 2023, 2022])
    else:
        candidates.append(ejercicio)
        candidates.extend([y for y in range(ejercicio - 1, 2021, -1)])  # hasta 2022

    for y in candidates:
        ev = retrieve_context(conn, query_vec, y, top_k=top_k)
        if ev:
            return ev, y

    return [], ejercicio

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
            f"Fuente: {ev['source_filename']}\n"
            f"Tipo: {ev.get('doc_type','')}\n"
            f"Texto:\n{ev['chunk_text']}\n"
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
# Orquestador principal
# =========================

def generate_response_with_rag(question: str, regimen: str = "General", ejercicio: int = 2025) -> str:
    conn = None
    try:
        conn = get_db_connection()

        # 1) Embed de la pregunta
        query_vec = embed_text(question)

        # 2) Retrieval con continuidad normativa
        evidence, used_year = retrieve_context_with_fallback(conn, query_vec, ejercicio, top_k=8)

        # 3) System prompt con contexto
        system_prompt = build_system_message(evidence)

        # 4) User prompt: AQUÍ va la pregunta real (CAMBIO #1)
        #    + exige nota si el año usado es distinto (CAMBIO #2)
        note_rule = ""
        if used_year != ejercicio:
            note_rule = f'\n\nAl final agrega exactamente: "Nota: Respuesta basada en normativa {used_year} por continuidad legal."'

        user_prompt = (
            f"Ejercicio fiscal solicitado: {ejercicio}\n"
            f"Ejercicio de evidencia recuperada: {used_year}\n"
            f"Régimen (si aplica): {regimen}\n"
            f"Pregunta: {question}\n\n"
            f"Responde específicamente a la pregunta usando SOLO el contexto recuperado. "
            f"Cita reglas/artículos en **negritas** y usa viñetas (-) para requisitos u obligaciones."
            f"{note_rule}"
        )

        # 5) Generar respuesta (consumimos streaming y devolvemos texto completo)
        response_text = ""
        for chunk in generate_answer_stream(system_prompt, user_prompt=user_prompt):
            response_text += chunk

        return response_text

    except Exception as e:
        return f"Error en el motor RAG: {str(e)}"
    finally:
        if conn:
            conn.close()
