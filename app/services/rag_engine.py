import os
import psycopg2
import re
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
4. Para listar requisitos, SIEMPRE usa viñetas con "-" (no numeración romana) y cita la referencia en negritas, por ejemplo: **Art. 27, fracc. I LISR**.


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
# Article lookup (determinístico por metadata)
# =========================

ARTICLE_REF_RE = re.compile(r"\b(?:art(?:í|i)culo|art)\.?\s*(\d+)\b", re.IGNORECASE)

def try_get_article_chunks(
    conn,
    document_id: str,
    article_number: int,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Recupera chunks de un artículo usando metadata->>'article_number'.
    Ordena por chunk_id para mantener continuidad.
    """
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


# =========================
# Retrieval (incluye base year=0 y NULL)
# =========================

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
    question: str,
    top_k: int = 8
) -> Tuple[List[Dict[str, Any]], int]:
    q = (question or "").lower()
        # -------------------------
    # Fast path: Artículo N (LISR) por metadata
    # -------------------------
    m = ARTICLE_REF_RE.search(question or "")
    if m:
        art_num = int(m.group(1))

        # Si suena fiscal, prioriza LISR
        is_fiscal = any(k in q for k in [
            "lisr", "isr", "renta", "deducc", "deducib", "cfdi", "comprobante",
            "sat", "gasto", "requisito", "deducciones"
        ])

        if is_fiscal:
            ev_direct = try_get_article_chunks(
                conn,
                document_id="LEY_DEL_IMPUESTO_SOBRE_LA_RENTA",
                article_number=art_num,
                limit=max(12, top_k)
            )
            if ev_direct:
                return ev_direct, 0


    wants_rmf = ("rmf" in q) or ("miscel" in q) or ("miscelánea" in q)
    mentions_anexo = ("anexo" in q)
    mentions_dof = ("dof" in q) or ("diario oficial" in q)

    # Heurística: si suena a requisitos generales de ISR/deducciones => primero ley (LISR)
    general_deductions = any(k in q for k in [
        "requisitos", "deduccion", "deducciones", "deducción", "deducible", "autorizada",
        "estrictamente indispensable", "cfdi", "comprobante", "forma de pago", "isr", "lisr", "impuesto sobre la renta"
    ])

    prefer_doc_type = "rmf" if wants_rmf else None

    prefer_doc_type_first = None
    prefer_doc_type_second = None

    if general_deductions:
        prefer_doc_type_first = "ley"
        prefer_doc_type_second = "rmf"
    else:
        prefer_doc_type_first = "rmf" if wants_rmf else None
        prefer_doc_type_second = None

    # Excluir anexos en primera pasada si NO los pidió (evita sesgo a 16-A)
    exclude_doc_type_first_pass = None
    if not mentions_anexo and not mentions_dof:
        exclude_doc_type_first_pass = "anexo"

    # Candidatos de año: prioridad + continuidad
    candidates: List[int] = []
    if ejercicio in (2025, 2026):
        candidates = [ejercicio, 2024, 2023, 2022]
    else:
        candidates = [ejercicio] + [y for y in range(ejercicio - 1, 2021, -1)]

    for y in candidates:
        # PASO 1A: preferencia fuerte (ley)
        if prefer_doc_type_first:
            ev = retrieve_context(
                conn, query_vec, y, top_k=top_k,
                prefer_doc_type=prefer_doc_type_first,
                exclude_doc_type=exclude_doc_type_first_pass
            )
            if ev:
                return ev, y

        # PASO 1B: complemento (rmf)
        if prefer_doc_type_second:
            ev = retrieve_context(
                conn, query_vec, y, top_k=top_k,
                prefer_doc_type=prefer_doc_type_second,
                exclude_doc_type=exclude_doc_type_first_pass
            )
            if ev:
                return ev, y

        # PASO 1C: compatibilidad (prefer_doc_type original)
        ev = retrieve_context(
            conn, query_vec, y, top_k=top_k,
            prefer_doc_type=prefer_doc_type,
            exclude_doc_type=exclude_doc_type_first_pass
        )
        if ev:
            return ev, y

        # PASO 2: RMF sin excluir (por si quedó mal etiquetada)
        if prefer_doc_type:
            ev = retrieve_context(
                conn, query_vec, y, top_k=top_k,
                prefer_doc_type=prefer_doc_type,
                exclude_doc_type=None
            )
            if ev:
                return ev, y

        # PASO 3: abrir abanico
        ev = retrieve_context(conn, query_vec, y, top_k=top_k, prefer_doc_type=None, exclude_doc_type=None)
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

        query_vec = embed_text(question)

        evidence, used_year = retrieve_context_with_fallback(
            conn, query_vec, ejercicio, question=question, top_k=8
        )

        system_prompt = build_system_message(evidence)

        note_rule = ""
        if used_year not in (ejercicio, 0):
            note_rule = f'\n\nAl final agrega exactamente: "Nota: Respuesta basada en normativa {used_year} por continuidad legal."'

        user_prompt = (
            f"Ejercicio fiscal solicitado: {ejercicio}\n"
            f"Ejercicio de evidencia recuperada: {used_year}\n"
            f"Régimen (si aplica): {regimen}\n"
            f"Pregunta: {question}\n\n"
            f"Responde específicamente a la pregunta usando SOLO el contexto recuperado. "
            f"Obligatorio: usa viñetas con '-' para cada requisito y cita la referencia exacta en negritas (ej. **Art. 27, fracc. I LISR**)."
            f"{note_rule}"
        )

        response_text = ""
        for chunk in generate_answer_stream(system_prompt, user_prompt=user_prompt):
            response_text += chunk

        return response_text

    except Exception as e:
        return f"Error en el motor RAG: {str(e)}"
    finally:
        if conn:
            conn.close()
