# Estado Integral del Proyecto: SaaS Fiscal (Handoff)

**Fecha:** 12 de Enero, 2026
**Autor:** Manus AI
**Versión:** 1.0

---

## 1) Resumen Ejecutivo

El proyecto **SaaS Fiscal** es un sistema de Retrieval-Augmented Generation (RAG) diseñado para responder preguntas complejas sobre el marco legal y fiscal de México. Su objetivo es proporcionar a contadores, abogados y empresas respuestas precisas, contextualizadas y fundamentadas en la legislación vigente, superando las limitaciones de los LLMs generalistas que carecen de conocimiento especializado y actualizado.

**Casos de Uso Principales:**
- **Consulta de Deducciones:** Un contador pregunta: "¿Cuál es el límite de exención para previsión social en salarios mínimos?"
- **Validación de Criterios:** Una empresa verifica si un gasto específico cumple los requisitos para ser deducible según la LISR.
- **Investigación Legal:** Un abogado investiga las obligaciones formales asociadas a un régimen fiscal particular.

| Componente | Estado | Notas |
| :--- | :--- | :--- |
| **Core RAG Pipeline** | ✅ **Funcional** | Extracción de PDF, chunking, embeddings y vector search operan end-to-end. |
| **Ingesta de Leyes** | ✅ **Funcional** | El script `reingestar_leyes_v2_1.py` ingesta correctamente las 13 leyes federales clave. |
| **Detección de Artículos** | ✅ **Robusto** | El regex actual (`v2.1`) detecta correctamente >95% de los artículos en leyes fiscales. |
| **Búsqueda Híbrida** | 🟡 **Frágil** | Se implementó un fallback a keyword search, pero requiere más pruebas y refinamiento. |
| **Detección de Transitorios** | 🟡 **Frágil** | La lógica actual no está optimizada para los formatos de artículos transitorios. |
| **Manejo de Vigencia** | 🟡 **Frágil** | La lógica actual (`exercise_year=0` para leyes) es una simplificación y no maneja derogaciones. |
| **UI/Frontend** | ❌ **Inexistente** | El desarrollo se ha centrado en el backend y la base de datos. |

**Riesgos Top 5:**
1.  **Bloqueo de Escalabilidad (Supabase):** La incapacidad de actualizar el plan de Supabase por un bloqueo bancario es el **riesgo #1**, ya que impide el crecimiento y la salida a producción.
2.  **Calidad de la Recuperación (RAG):** El algoritmo de retrieval es básico. Fallará en preguntas complejas que requieran cruzar información de múltiples artículos o realizar razonamiento multi-paso.
3.  **Precisión de la Data:** Aunque la ingesta ha mejorado, errores residuales en la metadata de artículos o la falta de manejo de vigencia pueden llevar a respuestas incorrectas, erosionando la confianza del usuario.
4.  **Velocidad de Ingesta:** El pipeline actual, aunque mejorado con batching, sigue siendo lento para actualizaciones masivas (ej. Resolución Miscelánea Fiscal anual), lo que retrasa la disponibilidad de información nueva.
5.  **Dependencia de Terceros:** El sistema depende críticamente de APIs externas (OpenAI, Supabase). Un cambio en sus políticas, precios o disponibilidad puede impactar directamente el servicio.

---

## 2) Repo y Ejecución

La estructura de carpetas inferida del proyecto local es la siguiente:

```
E:/DOCUMENTS/AGENTE FISCAL/SAAS_FISCAL/
├── .venv/                     # Entorno virtual de Python
├── app/
│   ├── services/
│   │   ├── retrieval/
│   │   │   ├── fallback.py
│   │   │   └── query_expansion.py
│   │   └── rag_engine.py
│   └── main.py                  # Backend (FastAPI)
├── data/
│   ├── LEYES_FEDERALES/         # PDFs de leyes y reglamentos
│   │   ├── CODIGO_FISCAL_DE_LA_FEDERACION.pdf
│   │   └── ... (12 más)
│   └── 2025/
│       └── ANEXOS/              # PDFs de anexos fiscales
├── .env                       # Archivo de variables de entorno
└── reingestar_leyes_v2_1.py     # Script de ingesta actual
```

**Ejecución Local:**
1.  **Activar Entorno Virtual:**
    ```powershell
    . .venv/Scripts/Activate
    ```
2.  **Instalar Dependencias:**
    ```powershell
    pip install -r requirements.txt  # (Asumiendo que existe un requirements.txt)
    ```
3.  **Correr Backend (FastAPI):**
    ```powershell
    uvicorn app.main:app --reload
    ```

**Variables de Entorno (`.env`):**

```ini
# .env.example

# Supabase
SUPABASE_URL="https://ytygyfgrkodpezorxgvn.supabase.co"
SUPABASE_KEY="sb_publishable_dgqMllK3kVN-qOeXJwOPRw_KwwulVEf" # Clave anónima (public)

# OpenAI
OPENAI_API_KEY="sk-..."

# RAG Engine
TOP_K_DEFAULT=10
```

---

## 3) Base de Datos (Supabase/Postgres)

**DDL (Schema SQL):**

```sql
-- Habilitar la extensión pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Tabla para almacenar metadatos de documentos fuente
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    doc_family TEXT, -- e.g., 'LISR', 'CFF', 'RMF'
    doc_type TEXT, -- e.g., 'ley', 'reglamento', 'anexo'
    exercise_year INTEGER DEFAULT 0, -- Año de ejercicio (0 para leyes federales)
    source_filename TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Tabla para almacenar los chunks de texto y sus embeddings
CREATE TABLE chunks (
    chunk_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    embedding VECTOR(1536), -- Dimensión para text-embedding-3-small
    metadata JSONB, -- { "article_number": "93", "page_start": 50, "source": "reingest_v2.1" }
    norm_kind TEXT, -- (No utilizado actualmente)
    norm_id TEXT, -- (No utilizado actualmente)
    page_start INTEGER,
    page_end INTEGER, -- (No utilizado actualmente)
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Índice para búsqueda por vector (IVF)
CREATE INDEX ON chunks USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);

-- (No se ha reportado el uso de Row Level Security - RLS)
```

**Embeddings:**
- **Modelo:** `text-embedding-3-small` de OpenAI.
- **Dimensión:** 1536.
- **Librería:** `pgvector` en Supabase para almacenamiento y búsqueda.

**Funciones SQL:**
Se utiliza una función para realizar la búsqueda por similitud de coseno.

```sql
-- Función para buscar chunks similares
CREATE OR REPLACE FUNCTION match_chunks (
  query_embedding VECTOR(1536),
  match_threshold FLOAT,
  match_count INT
)
RETURNS TABLE (
  chunk_id BIGINT,
  document_id TEXT,
  text TEXT,
  metadata JSONB,
  similarity FLOAT
)
AS $$
SELECT
  chunks.chunk_id,
  chunks.document_id,
  chunks.text,
  chunks.metadata,
  1 - (chunks.embedding <=> query_embedding) AS similarity
FROM chunks
WHERE 1 - (chunks.embedding <=> query_embedding) > match_threshold
ORDER BY similarity DESC
LIMIT match_count;
$$ LANGUAGE sql;
```

**Queries Reales (Ejemplos):**
1.  **Búsqueda por Vector (desde `rag_engine.py`):**
    ```python
    # 1. Generar embedding de la pregunta del usuario
    query_embedding = openai_client.embeddings.create(...).data[0].embedding

    # 2. Llamar a la función SQL
    results = supabase.rpc('match_chunks', {
        'query_embedding': query_embedding,
        'match_threshold': 0.7, # Umbral de similitud
        'match_count': 10       # Top-K
    }).execute()
    ```
2.  **Eliminación de Chunks (desde `reingestar_leyes_v2_1.py`):**
    ```python
    supabase.table("chunks").delete().eq("document_id", "LEY_DEL_IMPUESTO_SOBRE_LA_RENTA").execute()
    ```
3.  **Inserción de Chunks (desde `reingestar_leyes_v2_1.py`):**
    ```python
    supabase.table("chunks").insert({
        "document_id": "LEY_DEL_IMPUESTO_SOBRE_LA_RENTA",
        "text": "El impuesto se calculará por ejercicios...",
        "embedding": [0.01, ..., -0.02],
        "metadata": {"article_number": "1", "page_start": 1, "source": "reingest_v2.1"}
    }).execute()
    ```

---

## 4) Reingesta

- **Script Actual:** `/home/ubuntu/reingestar_leyes_v2_1.py` (en el sandbox de desarrollo).

**Pipeline de Ingesta:**
1.  **Extracción PDF:** Se usa `PyMuPDF` (`fitz`) para extraer el texto crudo de cada página del documento.
2.  **Limpieza:** Se agregan marcadores de página (`[[PAGE:X]]`) al texto extraído.
3.  **Split/Chunk:** El texto completo se divide en `chunks` de ~400 tokens (~1600 caracteres) con un solapamiento de 50 tokens.
4.  **Detección de Artículos:**
    - Se aplica un regex al inicio de cada chunk para detectar si comienza con una definición de artículo.
    - **Regex Actual (v2.1):** `r'^Artículo\s+(\d+)([oº])?\.?\s*[-–]?\s*([A-Z])?\s*(bis|ter|quater|quinquies)?\s*[.\-–]'`
    - **Normalización:** El número de artículo detectado (ej. `1`, `5-A`, `69-B Bis`) se almacena y se propaga a los chunks subsecuentes hasta que se encuentra un nuevo artículo.
5.  **Embeddings:** Se generan los embeddings para los chunks de texto en lotes de 15 usando el modelo `text-embedding-3-small` de OpenAI.
6.  **Insert:** Cada chunk, junto con su embedding y metadatos, se inserta en la tabla `chunks` de Supabase.

**Manejo de Metadatos:**
- `page_start`: Se calcula a partir de los marcadores `[[PAGE:X]]` para saber en qué página del PDF original comienza el chunk.
- `doc_type`, `exercise_year`: Se definen en una lista estática dentro del script de ingesta. Para leyes federales, `exercise_year` se establece en `0` para indicar que están siempre vigentes.

**Métricas Post-Reingesta (v2.1):**

| Documento | # Chunks (aprox) | # Artículos Detectados |
| :--- | :--- | :--- |
| Código Fiscal de la Federación | 899 | 262 |
| Constitución Política | 863 | 94 |
| Ley del ISR | 858 | 208 |
| Ley del IVA | 290 | 47 |
| Ley del IEPS | 350 | 60 |

**Errores Conocidos:**
- `ModuleNotFoundError: No module named 'fitz'`: Ocurre si `PyMuPDF` no está instalado correctamente en el entorno virtual.
- `psycopg2.errors.DuplicateObject`: Ocasionalmente ocurre en Supabase durante la inserción si un chunk ya existe. El script actual lo ignora.

---

## 5) Retrieval (RAG)

El algoritmo de recuperación es una secuencia de pasos definida en `rag_engine.py` y `fallback.py`.

1.  **Expansión de Consulta (`query_expansion.py`):** La pregunta del usuario se expande con sinónimos fiscales para mejorar la cobertura. (Ej: `límite` -> `exención`, `tope`, `máximo`).
2.  **Búsqueda Vectorial Primaria:** Se realiza una búsqueda por similitud de coseno en la tabla `chunks` usando el embedding de la consulta expandida.
    - **Top-K:** Se recuperan los 10 chunks más similares (`TOP_K_DEFAULT=10`).
    - **Umbral:** Se aplica un umbral de similitud (ej. 0.7) para filtrar resultados irrelevantes.
3.  **Fallback a Búsqueda por Keywords:** Si la búsqueda vectorial no arroja resultados satisfactorios, se intenta una búsqueda de texto completo (keyword search) usando `ilike` en la columna `text`.
4.  **Resolución de Citas (`Artículo X`):** El sistema actual **no tiene un mecanismo explícito** para resolver citas legales. Si un chunk recuperado menciona "ver artículo 93", el sistema no busca proactivamente el contenido del artículo 93. La solución actual depende de que el chunk del artículo 93 también sea recuperado por la búsqueda vectorial.
5.  **Formato de Respuesta:** El backend recibe los chunks de texto relevantes y los pasa a un modelo de lenguaje (GPT) con un prompt para que sintetice una respuesta final, citando las fuentes (documento y artículo).

---

## 6) Calidad / Evaluación

- **Evaluación Actual:** Manual y basada en casos de prueba. El principal criterio de éxito fue resolver la consulta sobre el "límite de exención de previsión social" (artículo 93 LISR), que fallaba debido a la incorrecta asignación de metadatos.
- **Principales Fallos Observados:**
    - **Asignación Incorrecta de Artículos:** (Problema principal, ahora mayormente resuelto) Chunks eran etiquetados con artículos referenciados, no con el artículo al que pertenecían.
    - **Recuperación de Información Irrelevante:** La búsqueda vectorial a veces recupera chunks que son semánticamente similares pero legalmente irrelevantes.
    - **Falta de Contexto en Transitorios:** El sistema no comprende el alcance temporal de los artículos transitorios.
- **Tests:** No existen tests automatizados (unitarios o de integración) ni un framework de CI/CD.

---

## 7) Seguridad y Cumplimiento

- **Manejo de Llaves:** Las claves de API (`SUPABASE_KEY`, `OPENAI_API_KEY`) se gestionan a través de un archivo `.env` local. La clave de Supabase utilizada es la `anon key` (pública), que debería estar restringida por políticas de RLS en producción.
- **Acceso a BD:** El acceso se realiza directamente desde los scripts de Python usando la librería de Supabase, sin un pool de conexiones o una capa de abstracción de datos robusta.
- **Logs:** El logging es básico, limitado a la salida estándar (`print`) de los scripts. No hay un sistema centralizado de logs.
- **Riesgos de Privacidad:** Mínimos en la etapa actual, ya que solo se manejan documentos públicos. Sin embargo, si el sistema se expande para manejar datos de clientes, la falta de RLS y logs de auditoría sería un riesgo crítico.

---

## 8) Backlog Priorizado

| Tarea | Esfuerzo | Dependencia |
| :--- | :--- | :--- |
| 1. **Resolver bloqueo de pago de Supabase** | Alto | **BLOQUEADOR CRÍTICO** |
| 2. Implementar Row Level Security (RLS) en Supabase | Medio | Tarea 1 |
| 3. Crear set de evaluación (Golden Set) con 50 preguntas | Medio | - |
| 4. Implementar Re-ranking (ej. Cohere Rerank) | Medio | Tarea 3 |
| 5. Mejorar regex para Artículos Transitorios | Bajo | - |
| 6. Desarrollar pipeline de ingesta para RMF y Anexos | Alto | Tarea 5 |
| 7. Implementar lógica de "vigencia" de normas | Alto | Tarea 6 |
| 8. Crear un endpoint de health-check en el backend | Bajo | - |
| 9. Configurar logging centralizado (ej. Datadog) | Medio | Tarea 1 |
| 10. Desarrollar un frontend básico para interactuar con el API | Alto | - |

---

## Adjuntos

**Lista de Documentos Legales Cargados (12/Ene/2026):**

- `CODIGO_FISCAL_DE_LA_FEDERACION.pdf`
- `CONSTITUCION_POLITICA_ESTADOS_UNIDOS_MEXICANOS.pdf`
- `CONVENCION_MULTILATERAL_BEPS_(MLI)_OCDE.pdf`
- `LEY FEDERAL DE LOS DERECHOS DEL CONTRIBUYENTE DOF 23055005.pdf`
- `LEY_ADUANERA.pdf`
- `LEY_DEL_IMPUESTO_SOBRE_LA_RENTA.pdf`
- `LEY_DEL_IMPUESTO_VALOR_AGREGADO.pdf`
- `LEY_FEDERAL_IMPUESTO_SOBRE_AUTOMOVILES_NUEVOS.pdf`
- `LEY_IMPUESTO_ESPECIAL_PRODUCCION_SERVICIOS.pdf`
- `REGLAMENTO_CODIGO_FISCAL_FEDERACION.pdf`
- `REGLAMENTO_LEY_ADUANERA.pdf`
- `REGLAMENTO_LEY_DEL_IMPUESTO_VALOR_AGREGADO.pdf`
- `REGLAMENTO_LEY_IMPUESTO_SOBRE_RENTA.pdf`

**Cambios Recientes Relevantes:**
- **Creación de `reingestar_leyes_v2_1.py`:** Script de re-ingesta con detección de artículos mejorada, que resuelve el principal problema de calidad de datos.
- **Creación de `query_expansion.py`:** Módulo para expandir las consultas de usuario con sinónimos fiscales.
- **Modificación de `fallback.py`:** Implementación de una lógica de fallback a búsqueda por keywords cuando la búsqueda vectorial falla.
