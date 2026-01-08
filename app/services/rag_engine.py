import json
import psycopg2
from typing import List, Dict, Any, Generator, Optional
from openai import OpenAI
from app.core.config import DIRECT_URL

# Importamos la configuración desde la ruta correcta de la nueva estructura
from app.core.config import OPENAI_API_KEY, DIRECT_URL, MODEL_EMBED, MODEL_CHAT

# Inicializamos el cliente de OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================================
# 1. PROMPT DE DIAGNÓSTICO (Simplificado)
# ==========================================
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

# ==========================================
# 2. FUNCIONES DE BASE DE DATOS E IA
# ==========================================

def get_db_connection():
    # Si DIRECT_URL está vacío, intentamos leerlo directamente del sistema
    conn_str = DIRECT_URL or os.getenv("DATABASE_URL")
    
    if not conn_str:
        raise ValueError("No se encontró la cadena de conexión a la base de datos.")
        
    return psycopg2.connect(conn_str)

def embed_text(text: str) -> List[float]:
    """Convierte texto a vector usando OpenAI"""
    clean_text = text.replace("\n", " ")
    resp = client.embeddings.create(input=[clean_text], model=MODEL_EMBED)
    return resp.data[0].embedding

def retrieve_context(conn, query_vec: List[float], ejercicio: int, top_k: int = 8) -> List[Dict[str, Any]]:
    """Busca documentos relevantes en Postgres/pgvector"""
    cur = conn.cursor()
    
    # Consulta SQL optimizada para tu esquema
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
    
    cur.execute(sql, (query_vec, ejercicio, query_vec, top_k))
    rows = cur.fetchall()
    cur.close()

    evidence = []
    for r in rows:
        # Manejo seguro de fecha (puede ser None)
        pub_date = r[4].isoformat() if r[4] else "S/F"
        
        evidence.append({
            "chunk_id": r[0],
            "source_filename": r[1],
            "chunk_text": r[2],
            "doc_type": r[3],
            "published_date": pub_date,
            "page_start": r[5],
            "page_end": r[6],
            "score": float(r[7])
        })
    return evidence

def build_system_message(evidence: List[Dict[str, Any]], ejercicio: int, question: str) -> str:
    """Construye el prompt final con capacidad extendida para Tier 2."""
    context_parts = []
    
    # Límite seguro de caracteres para GPT-4o
    char_limit = 400000 
    current_chars = 0

    for i, ev in enumerate(evidence, 1):
       # CAMBIO: Agregamos separadores claros (---) y saltos de línea dobles
        txt = f"\n--- DOCUMENTO {i} ---\nFuente: {ev['source_filename']}\nTexto:\n{ev['chunk_text']}\n"
        
        if current_chars + len(txt) < char_limit:
            context_parts.append(txt)
            current_chars += len(txt)
        else:
            context_parts.append("... [Límite de seguridad alcanzado] ...")
            break
    
    full_context_str = "\n".join(context_parts)
    
    if not full_context_str:
        full_context_str = "No se encontró información específica en la base de conocimientos para este ejercicio."

    final_prompt = SYSTEM_PROMPT_TEMPLATE.replace(
        "{{CONTEXTO_RECUPERADO}}", full_context_str
    ).replace(
        "{{PREGUNTA_USUARIO}}", f"Ejercicio Fiscal: {ejercicio}\nPregunta: {question}"
    )
    
    return final_prompt

def generate_answer_stream(system_prompt: str, user_prompt: str = "Proceda con el análisis.") -> Generator[str, None, None]:
    """Generador que consume la API de OpenAI en modo streaming"""
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

# ==========================================
# 3. FUNCIÓN PRINCIPAL (ORQUESTADOR)
# ==========================================
# Esta es la función que llama main.py 
def generate_response_with_rag(question: str, regimen: str = "General", ejercicio: int = 2025) -> str:
    """
    Flujo completo: Conectar DB -> Vectorizar -> Buscar Contexto -> Generar Respuesta
    """
    conn = None
    try:
        # 1. Conectar a Supabase
        conn = get_db_connection()
        
        # 2. Vectorizar la pregunta
        query_vec = embed_text(question)
        
        # 3. Recuperar contexto (RAG)
        evidence = retrieve_context(conn, query_vec, ejercicio, top_k=8)
        
        # 4. Construir Prompt
        full_prompt = build_system_message(evidence, ejercicio, question)
        
        # 5. Generar respuesta (Consumimos el stream aquí para devolver texto completo a la API)
        response_text = ""
        stream_gen = generate_answer_stream(full_prompt)
        for chunk in stream_gen:
            response_text += chunk
            
        return response_text

    except Exception as e:
        return f"Error en el motor RAG: {str(e)}"
    finally:
        if conn:
            conn.close()