import os
import json
import time
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from itsdangerous import URLSafeSerializer, BadSignature
from passlib.context import CryptContext

import psycopg2
from pgvector.psycopg2 import register_vector
from openai import OpenAI

# -----------------------
# Config
# -----------------------
DATABASE_URL = os.environ.get("DATABASE_URL")  # Supabase connection string
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

SESSION_SECRET = os.environ.get("SESSION_SECRET", "change-me")
BOOTSTRAP_ADMIN_KEY = os.environ.get("BOOTSTRAP_ADMIN_KEY", "")  # para crear el primer usuario
DEFAULT_TOP_K = int(os.environ.get("TOP_K_DEFAULT", "8"))

MODEL_EMBED = os.environ.get("MODEL_EMBED", "text-embedding-3-small")  # 1536
MODEL_CHAT = os.environ.get("MODEL_CHAT", "gpt-4.1-mini")  # puedes cambiarlo

PLAN_ADVANCED_ENABLED = False  # por decisión del piloto

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
signer = URLSafeSerializer(SESSION_SECRET, salt="session-v1")

app = FastAPI()
templates = Jinja2Templates(directory="templates")
client = OpenAI(api_key=OPENAI_API_KEY)


# -----------------------
# DB helpers
# -----------------------
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("Falta DATABASE_URL")
    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)
    return conn


def ensure_user_table_exists():
    conn = get_conn()
    try:
        # Compatible con poolers: evita "set_session inside a transaction"
        conn.set_session(autocommit=True)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS public.app_users (
          username TEXT PRIMARY KEY,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'evaluator',
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)
        cur.close()
    finally:
        conn.close()



# -----------------------
# Auth (cookie session)
# -----------------------
def set_session(response, username: str):
    token = signer.dumps({"u": username})
    response.set_cookie("session", token, httponly=True, secure=True, samesite="lax")


def clear_session(response):
    response.delete_cookie("session")


def get_current_user(request: Request) -> Optional[str]:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        data = signer.loads(token)
        return data.get("u")
    except BadSignature:
        return None


def require_user(request: Request) -> str:
    u = get_current_user(request)
    if not u:
        raise HTTPException(status_code=401, detail="No autenticado")
    return u


# -----------------------
# Retrieval
# -----------------------
def embed_text(text: str) -> List[float]:
    resp = client.embeddings.create(model=MODEL_EMBED, input=[text])
    return resp.data[0].embedding


def retrieve_chunks(conn, qvec: List[float], ejercicio: int, top_k: int) -> List[Dict[str, Any]]:
    """
    Retrieval optimizado para pgvector + HNSW:
    1) trae candidatos por similitud SIN filtro (usa índice HNSW)
    2) luego filtra por ejercicio al hacer JOIN con documents
    """
    # cuantos candidatos traer antes de filtrar por ejercicio
    # (si te salen pocos resultados del año, sube a 500)
    CANDIDATES = max(200, top_k * 25)

    cur = conn.cursor()
    sql = """
    WITH top AS (
      SELECT
        c.chunk_id,
        c.document_id,
        c.page_start,
        c.page_end,
        c.text,
        c.metadata,
        (c.embedding <=> %s::vector) AS score
      FROM public.chunks c
      ORDER BY c.embedding <=> %s::vector
      LIMIT %s
    )
    SELECT
      t.chunk_id,
      t.document_id,
      d.source_filename,
      d.doc_family,
      d.doc_type,
      d.exercise_year,
      d.published_date,
      t.page_start,
      t.page_end,
      t.text,
      t.metadata,
      t.score
    FROM top t
    JOIN public.documents d ON d.document_id = t.document_id
    WHERE d.exercise_year = %s
    ORDER BY t.score
    LIMIT %s;
    """
    cur.execute(sql, (qvec, qvec, CANDIDATES, ejercicio, top_k))
    rows = cur.fetchall()
    cur.close()

    out = []
    for r in rows:
        out.append({
            "chunk_id": r[0],
            "document_id": r[1],
            "source_filename": r[2],
            "doc_family": r[3],
            "doc_type": r[4],
            "exercise_year": r[5],
            "published_date": (r[6].isoformat() if r[6] else None),
            "page_start": r[7],
            "page_end": r[8],
            "text": r[9],
            "metadata": r[10],
            "score": float(r[11]),
        })
    return out



# -----------------------
# Prompt maestro (resumen)
# -----------------------
SYSTEM_PROMPT = """
Eres un asistente experto en derecho fiscal federal mexicano. Respondes exclusivamente con base en el corpus recuperado (evidencia).
Reglas obligatorias:
- Ejercicio fiscal: respeta el ejercicio elegido y advierte si el tema impacta otros ejercicios.
- Citas: toda afirmación importante debe tener citas del corpus (Documento, tipo, fecha DOF si existe, referencia interna chunk_id).
- Entrega: Resumen, Ejercicio y vigencia, Fundamento y citas, Análisis, Escenarios sin recomendar, Riesgo razonado, e Incertidumbre (si aplica).
- Si el corpus no permite concluir con certeza: detente y pide datos concretos; no especules.
- No des recomendaciones; entrega escenarios.
"""


def build_context(evidence: List[Dict[str, Any]]) -> str:
    parts = []
    for i, ev in enumerate(evidence, 1):
        cite = f"""[CITA {i}]
Documento: {ev["source_filename"]} | Tipo: {ev["doc_type"]} | Familia: {ev["doc_family"]} | Ejercicio: {ev["exercise_year"]} | DOF: {ev["published_date"]}
Ref: chunk_id={ev["chunk_id"]} | páginas: {ev["page_start"]}-{ev["page_end"]}
Texto:
{ev["text"]}
"""
        parts.append(cite)
    return "\n".join(parts)


def answer_with_citations(question: str, ejercicio: int, evidence: List[Dict[str, Any]]) -> tuple[str, int]:
    context = build_context(evidence)
    user_prompt = f"""
Ejercicio fiscal: {ejercicio}
Pregunta del usuario:
{question}

EVIDENCIA (única fuente autorizada):
{context}
"""

    t4 = time.time()
    resp = client.chat.completions.create(
        model=MODEL_CHAT,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.strip()},
            {"role": "user", "content": user_prompt.strip()},
        ],
        temperature=0.2,
    )
    t5 = time.time()
    gen_ms = int((t5 - t4) * 1000)

    return resp.choices[0].message.content, gen_ms


# -----------------------
# Routes: UI
# -----------------------
@app.on_event("startup")
def startup():
    # En Supabase (pooler) evitamos DDL en startup.
    # La tabla app_users ya fue creada manualmente en Supabase.
    pass



@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    u = get_current_user(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse("/app", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT password_hash, is_active FROM public.app_users WHERE username=%s;", (username,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Usuario o contraseña incorrectos"})
    pw_hash, is_active = row
    if not is_active:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Usuario inactivo"})
    if not pwd_context.verify(password, pw_hash):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Usuario o contraseña incorrectos"})

    resp = RedirectResponse("/app", status_code=302)
    set_session(resp, username)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    clear_session(resp)
    return resp


@app.get("/app", response_class=HTMLResponse)
def app_page(request: Request, user: str = Depends(require_user)):
    # Plan avanzado desactivado
    return templates.TemplateResponse("app.html", {
        "request": request,
        "user": user,
        "advanced_enabled": PLAN_ADVANCED_ENABLED,
        "default_top_k": DEFAULT_TOP_K
    })


# -----------------------
# API: Bootstrap user
# -----------------------
@app.post("/bootstrap/create_user")
def bootstrap_create_user(
    key: str = Form(...),
    username: str = Form(...),
    password: str = Form(...)
):
    if not BOOTSTRAP_ADMIN_KEY or key != BOOTSTRAP_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

    pw_hash = pwd_context.hash(password)

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO public.app_users(username, password_hash, role, is_active)
            VALUES (%s, %s, 'evaluator', TRUE)
            ON CONFLICT (username) DO UPDATE
              SET password_hash=EXCLUDED.password_hash,
                  is_active=TRUE;
        """, (username, pw_hash))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return {"ok": True, "username": username}



# -----------------------
# API: Ask + Feedback
# -----------------------
@app.post("/ask")
async def ask(request: Request, ejercicio: int = Form(...), question: str = Form(...), top_k: int = Form(DEFAULT_TOP_K),
              user: str = Depends(require_user)):

    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY no configurada")

    if ejercicio < 2000 or ejercicio > 2100:
        raise HTTPException(status_code=400, detail="Ejercicio inválido")

    t0 = time.time()

    t_embed0 = time.time()
    qvec = embed_text(question)
    t_embed1 = time.time()
    embed_ms = int((t_embed1 - t_embed0) * 1000)


    conn = get_conn()
    t2 = time.time()

    evidence = retrieve_chunks(conn, qvec, ejercicio=ejercicio, top_k=top_k)
    t3 = time.time()
    retrieval_ms = int((t3 - t2) * 1000)
    answer, gen_ms = answer_with_citations(question, ejercicio, evidence)
    latency_ms = int((time.time() - t0) * 1000)

    # Guardar run
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO public.eval_runs(username, plan, ejercicio, question, top_k, retrieval, answer, latency_ms, model_chat, model_embed)
        VALUES (%s, 'basic', %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
        RETURNING run_id;
    """, (user, ejercicio, question, top_k, json.dumps(evidence, ensure_ascii=False), answer, latency_ms, MODEL_CHAT, MODEL_EMBED))
    run_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    print(f"[TIMING] embed_ms={embed_ms} retrieval_ms={retrieval_ms} gen_ms={gen_ms} total_ms={embed_ms+retrieval_ms+gen_ms}")
    return JSONResponse({
        "run_id": run_id,
        "answer": answer,
        "citations": [
            {
                "n": i + 1,
                "source_filename": ev["source_filename"],
                "doc_type": ev["doc_type"],
                "published_date": ev["published_date"],
                "chunk_id": ev["chunk_id"],
                "page_start": ev["page_start"],
                "page_end": ev["page_end"],
                "score": ev["score"],
            } for i, ev in enumerate(evidence)
        ],
        "evidence": evidence,
        "latency_ms": latency_ms,
    })


@app.post("/feedback")
async def feedback(request: Request, run_id: int = Form(...), thumbs_up: bool = Form(...), comment: str = Form(""),
                   user: str = Depends(require_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO public.eval_feedback(run_id, username, thumbs_up, comment)
        VALUES (%s, %s, %s, %s);
    """, (run_id, user, thumbs_up, comment))
    conn.commit()
    cur.close()
    conn.close()
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "advanced_enabled": PLAN_ADVANCED_ENABLED}
