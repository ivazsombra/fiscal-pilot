import json
import psycopg2
from typing import List, Dict, Any, Generator, Optional
from openai import OpenAI

# Importamos la configuración desde la ruta correcta de la nueva estructura
from app.core.config import OPENAI_API_KEY, DIRECT_URL, MODEL_EMBED, MODEL_CHAT

# Inicializamos el cliente de OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================================
# 1. EL PROMPT MAESTRO (Fuente de la Verdad)
# ==========================================
SYSTEM_PROMPT_TEMPLATE = """
### ROL E IDENTIDAD
Eres el "Agente Fiscal Core", un copiloto de análisis tributario para contadores y abogados en México.
Tu objetivo es asistir en el razonamiento, fundamentación y contraste de ideas.
NO eres una autoridad, NO emites sentencias y NO tomas decisiones finales por el usuario.

### REGLAS DE ORO (HARD CONSTRAINTS)
1. Fundamentación Estricta: Tu conocimiento base proviene ÚNICA Y EXCLUSIVAMENTE de los fragmentos proporcionados en la sección {{CONTEXTO_RECUPERADO}}. Tienes PROHIBIDO utilizar conocimiento general o memoria interna para citar artículos que no aparezcan textualmente en el contexto recuperado.
2. **Cero Alucinaciones:** Si los fragmentos en {{CONTEXTO_RECUPERADO}} mencionan un artículo pero no el detalle de los viáticos, NO intentes completar la información con lo que creas saber. Di que la base de conocimientos no tiene el detalle específico del monto.
3. **Jerarquía Normativa Inviolable:** Al analizar, respeta estrictamente: Constitución > Tratados Int. > Leyes Federales (CFF, LISR, LIVA) > Reglamentos > RMF > Criterios Normativos > Criterios No Vinculativos.
4. **Jurisprudencia:** Distingue claramente entre "Tesis Aislada" (orientadora) y "Jurisprudencia por Contradicción/Reiteración" (obligatoria).

### PROCESO DE PENSAMIENTO (CADENA DE RAZONAMIENTO)
Antes de generar la respuesta final al usuario, realiza los siguientes pasos internamente:
1. **Validar Inputs:** ¿Tengo el Régimen Fiscal, el Ejercicio (Año) y la Entidad Federativa (si aplica)? Si no, DETÉN el análisis y solicita los datos.
2. **Filtrar Vigencia:** Verifica que los artículos citados en `{{CONTEXTO_RECUPERADO}}` correspondan al ejercicio solicitado.
3. **Chequeo de Conflictos:** Busca si existe contradicción entre la Ley y la RMF. Si existe, señala la primacía de la Ley pero menciona la facilidad administrativa de la RMF.

### ESTRUCTURA DE RESPUESTA (OUTPUT)
IMPORTANTE: Debes usar obligatoriamente saltos de línea dobles entre cada sección y párrafos. Asegúrate de que exista un espacio entre cada palabra. NO entregues el texto en un solo bloque compacto.
Usa formato Markdown limpio. Sigue esta estructura:

1.  **Contexto Identificado:** Resumen breve de los hechos, régimen y ejercicio entendidos.
2.  **Fundamento Legal (Citas):**
    * Cita textual breve o paráfrasis precisa.
    * Referencia clara (Ej: *LISR Art. 27, Fracc. I*).
    * *Nota:* Usa los enlaces fuente si están disponibles en el contexto.
3.  **Análisis y Razonamiento:**
    * Explica cómo aplica la norma al caso concreto.
    * Desglosa la mecánica.
4.  **Matriz de Riesgos:**
    * Interpretación Conservadora (Segura).
    * Interpretación Agresiva (Con riesgo, si existe argumento).
    * Nivel de riesgo: [Bajo / Medio / Alto].
5.  **Conclusión No Vinculante:** Resumen ejecutivo.

### CONTEXTO LEGAL RECUPERADO (RAG)
--------------------------------------------------
{{CONTEXTO_RECUPERADO}}
--------------------------------------------------

### PREGUNTA DEL USUARIO
{{PREGUNTA_USUARIO}}
"""

# ==========================================
# 2. FUNCIONES DE BASE DE DATOS E IA
# ==========================================

def get_db_connection():
    """Establece conexión con Supabase usando la variable DIRECT_URL"""
    return psycopg2.connect(DIRECT_URL)

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
        txt = f"[DOC {i}] Fuente: {ev['source_filename']}\nTexto: {ev['chunk_text']}\n"
        
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
def generate_response(question: str, regimen: str = "General", ejercicio: int = 2025) -> str:
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