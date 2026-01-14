#!/usr/bin/env python3
"""SAS Fiscal — Reingesta ÚNICA (Ruta 2)

Este script debe ser el ÚNICO punto de entrada para reingestas.

Modos:
- laws: Leyes/Reglamentos (article-first) ✅
- rmf : RMF/Anexos (referencias) ⚠️ (stub)

Convenciones (ya acordadas):
- Sufijos: 69-B-BIS (sin espacios)
- Transitorios: TRANS-PRIMERO

Uso rápido:
  python reingest.py laws --base-path data/LEYES_FEDERALES --all
  python reingest.py laws --doc CODIGO_FISCAL_DE_LA_FEDERACION

Requisitos env:
  SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import os
import re
import time
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client

# Parser Único (token canónico)
# Nota: este import asume que article_parser.py vive en la raíz del proyecto.
from article_parser import parse_article_header


# -----------------------------
# Config
# -----------------------------

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

MODEL_EMBED = os.getenv("MODEL_EMBED", "text-embedding-3-small")

# Chunking (por caracteres; estable y predecible para PDFs)
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "3500"))
CHUNK_OVERLAP_CHARS = int(os.getenv("CHUNK_OVERLAP_CHARS", "400"))

# Embeddings / inserción
BATCH_SIZE_EMBED = int(os.getenv("BATCH_SIZE_EMBED", "15"))
DELAY_EMBEDDING = float(os.getenv("DELAY_EMBEDDING", "0.10"))
DELAY_INSERT = float(os.getenv("DELAY_INSERT", "0.05"))


# -----------------------------
# Manifest (baseline)
# -----------------------------

@dataclass(frozen=True)
class DocumentSpec:
    filename: str
    document_id: str
    title: str
    doc_type: str = "ley"
    exercise_year: int = 0


LEYES_BASELINE: List[DocumentSpec] = [
    DocumentSpec(
        filename="CODIGO_FISCAL_DE_LA_FEDERACION.pdf",
        document_id="CODIGO_FISCAL_DE_LA_FEDERACION",
        title="Código Fiscal de la Federación",
    ),
    DocumentSpec(
        filename="CONSTITUCION_POLITICA_ESTADOS_UNIDOS_MEXICANOS.pdf",
        document_id="CONSTITUCION_POLITICA_ESTADOS_UNIDOS_MEXICANOS",
        title="Constitución Política de los Estados Unidos Mexicanos",
    ),
    DocumentSpec(
        filename="LEY_DEL_IMPUESTO_SOBRE_LA_RENTA.pdf",
        document_id="LEY_DEL_IMPUESTO_SOBRE_LA_RENTA",
        title="Ley del Impuesto Sobre la Renta",
    ),
    DocumentSpec(
        filename="LEY_DEL_IMPUESTO_VALOR_AGREGADO.pdf",
        document_id="LEY_DEL_IMPUESTO_VALOR_AGREGADO",
        title="Ley del Impuesto al Valor Agregado",
    ),
    DocumentSpec(
        filename="LEY_IMPUESTO_ESPECIAL_PRODUCCION_SERVICIOS.pdf",
        document_id="LEY_IMPUESTO_ESPECIAL_PRODUCCION_SERVICIOS",
        title="Ley del Impuesto Especial sobre Producción y Servicios",
    ),
    DocumentSpec(
        filename="LEY_ADUANERA.pdf",
        document_id="LEY_ADUANERA",
        title="Ley Aduanera",
    ),
    DocumentSpec(
        filename="LEY_FEDERAL_IMPUESTO_SOBRE_AUTOMOVILES_NUEVOS.pdf",
        document_id="LEY_FEDERAL_IMPUESTO_SOBRE_AUTOMOVILES_NUEVOS",
        title="Ley Federal del Impuesto sobre Automóviles Nuevos",
    ),
    DocumentSpec(
        filename="LEY FEDERAL DE LOS DERECHOS DEL CONTRIBUYENTE DOF 23055005.pdf",
        document_id="LEY FEDERAL DE LOS DERECHOS DEL CONTRIBUYENTE DOF 23055005",
        title="Ley Federal de los Derechos del Contribuyente",
    ),
    DocumentSpec(
        filename="CONVENCION_MULTILATERAL_BEPS_(MLI)_OCDE.pdf",
        document_id="CONVENCION_MULTILATERAL_BEPS_(MLI)_OCDE",
        title="Convención Multilateral BEPS (MLI) OCDE",
    ),
    DocumentSpec(
        filename="REGLAMENTO_CODIGO_FISCAL_FEDERACION.pdf",
        document_id="REGLAMENTO_CODIGO_FISCAL_FEDERACION",
        title="Reglamento del Código Fiscal de la Federación",
    ),
    DocumentSpec(
        filename="REGLAMENTO_LEY_IMPUESTO_SOBRE_RENTA.pdf",
        document_id="REGLAMENTO_LEY_IMPUESTO_SOBRE_RENTA",
        title="Reglamento de la Ley del Impuesto Sobre la Renta",
    ),
    DocumentSpec(
        filename="REGLAMENTO_LEY_DEL_IMPUESTO_VALOR_AGREGADO.pdf",
        document_id="REGLAMENTO_LEY_DEL_IMPUESTO_VALOR_AGREGADO",
        title="Reglamento de la Ley del IVA",
    ),
    DocumentSpec(
        filename="REGLAMENTO_LEY_ADUANERA.pdf",
        document_id="REGLAMENTO_LEY_ADUANERA",
        title="Reglamento de la Ley Aduanera",
    ),
]


# -----------------------------
# PDF extraction
# -----------------------------

_PAGE_MARK_RE = re.compile(r"\[\[PAGE:(\d+)\]\]")


def extract_text_with_page_marks(pdf_path: Path) -> str:
    """Extrae texto e inserta marcadores [[PAGE:n]] para rastreo."""
    doc = fitz.open(pdf_path)
    parts: List[str] = []
    for page_num, page in enumerate(doc, 1):
        parts.append(f"\n[[PAGE:{page_num}]]\n")
        parts.append(page.get_text() or "")
    doc.close()
    return "".join(parts)



# -----------------------------
# Extracción por páginas (evita O(n^2) y facilita page_start/page_end)
# -----------------------------

def extract_pages(pdf_path: Path) -> List[Tuple[int, str]]:
    """Devuelve lista de (page_num, page_text) usando PyMuPDF."""
    doc = fitz.open(pdf_path)
    pages: List[Tuple[int, str]] = []
    for page_num, page in enumerate(doc, 1):
        pages.append((page_num, page.get_text("text") or ""))
    doc.close()
    return pages


@dataclass(frozen=True)
class ArticleBlock:
    article_id: str
    text: str
    page_offsets: List[Tuple[int, int]]  # (char_offset_in_text, page_num)


def iter_article_blocks(pages: List[Tuple[int, str]]) -> List[ArticleBlock]:
    """Segmenta el documento en bloques por artículo (incluye PREAMBULO)."""
    blocks: List[ArticleBlock] = []

    current_id = "PREAMBULO"
    buf: List[str] = []
    page_offsets: List[Tuple[int, int]] = []
    cur_len = 0

    def flush():
        nonlocal buf, page_offsets, cur_len, blocks, current_id
        text = "\n".join(buf).strip()
        if text:
            if not page_offsets:
                page_offsets = [(0, 1)]
            blocks.append(ArticleBlock(article_id=current_id, text=text, page_offsets=page_offsets))
        buf = []
        page_offsets = []
        cur_len = 0

    for page_num, page_text in pages:
        lines = (page_text or "").splitlines()
        if not lines:
            continue

        page_started = False
        for line in lines:
            token = parse_article_header(line)
            if token:
                flush()
                current_id = token
                buf = [line]
                page_offsets = [(0, page_num)]
                cur_len = len(line) + 1
                page_started = True
                continue

            if not page_started:
                if buf:
                    page_offsets.append((cur_len, page_num))
                else:
                    page_offsets.append((0, page_num))
                page_started = True

            buf.append(line)
            cur_len += len(line) + 1

    flush()
    return blocks


def _infer_page_start(text_slice: str, fallback: int = 1) -> int:
    """Intenta inferir el page_start desde el último marcador [[PAGE:n]] dentro del slice."""
    last = None
    for m in _PAGE_MARK_RE.finditer(text_slice):
        last = m
    if last:
        try:
            return int(last.group(1))
        except Exception:
            return fallback
    return fallback


# -----------------------------
# Chunking article-first
# -----------------------------

@dataclass
class Chunk:
    text: str
    article_id: str
    page_start: int
    page_end: int | None = None
    chunk_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None



def chunk_article_first(pages: List[Tuple[int, str]]) -> List[Chunk]:
    """Chunking por artículo (sin mezclar) y sub-chunks por caracteres con overlap."""
    blocks = iter_article_blocks(pages)
    chunks: List[Chunk] = []

    for block in blocks:
        text = block.text
        if not text:
            continue

        offsets = [o for (o, _) in block.page_offsets]
        pages_nums = [p for (_, p) in block.page_offsets]

        def page_for(char_offset: int) -> int:
            i = bisect_right(offsets, max(char_offset, 0)) - 1
            if i < 0:
                return pages_nums[0]
            return pages_nums[i]

        start = 0
        per_article_idx = 0
        L = len(text)

        while start < L:
            end = min(start + CHUNK_CHARS, L)
            chunk_text = text[start:end].strip()
            if chunk_text:
                ps = page_for(start)
                pe = page_for(max(end - 1, 0))
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        article_id=block.article_id,
                        page_start=ps,
                        page_end=pe,
                        chunk_index=per_article_idx,
                        char_start=start,
                        char_end=end,
                    )
                )
                per_article_idx += 1

            if end >= L:
                break
            start = max(0, end - CHUNK_OVERLAP_CHARS)

    return chunks


# -----------------------------
# DB helpers
# -----------------------------


def _require_env() -> None:
    missing = [k for k, v in {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_KEY": SUPABASE_KEY,
        "OPENAI_API_KEY": OPENAI_API_KEY,
    }.items() if not v]
    if missing:
        raise SystemExit(f"❌ Faltan variables de entorno: {', '.join(missing)}")


def upsert_document(supabase, spec: DocumentSpec, *, source_path: str, doc_family: str = "LEYES_FEDERALES") -> None:
    """UPSERT controlado en documents.

    No es "estricto total": si el documento no existe, lo crea con mínimos;
    si existe, actualiza campos relevantes (sin tocar lo demás).
    """
    supabase.table("documents").upsert({
        "document_id": spec.document_id,
        "title": spec.title,
        "doc_family": doc_family,
        "doc_type": spec.doc_type,
        "exercise_year": spec.exercise_year,
        "source_filename": spec.filename,
        "source_path": source_path,
    }).execute()



def delete_chunks(supabase, document_id: str) -> int:
    res = supabase.table("chunks").delete().eq("document_id", document_id).execute()
    return len(res.data) if getattr(res, "data", None) else 0


def embed_batch(client: OpenAI, texts: List[str]) -> List[Optional[List[float]]]:
    try:
        resp = client.embeddings.create(model=MODEL_EMBED, input=[(t or "").replace("\n", " ") for t in texts])
        vecs: List[Optional[List[float]]] = [None] * len(texts)
        for d in resp.data:
            vecs[getattr(d, "index", 0)] = d.embedding
        return vecs
    except Exception as e:
        print(f"      ⚠️ Embeddings fallaron (lote): {e}")
        # Reintento uno por uno
        out: List[Optional[List[float]]] = []
        for t in texts:
            try:
                r = client.embeddings.create(model=MODEL_EMBED, input=[(t or "").replace("\n", " ")])
                out.append(r.data[0].embedding)
            except Exception:
                out.append(None)
            time.sleep(DELAY_EMBEDDING * 2)
        return out


# -----------------------------
# Reingesta: laws
# -----------------------------


def reingest_law(openai_client: OpenAI, supabase, spec: DocumentSpec, base_path: Path, *, dry_run: bool) -> bool:
    pdf_path = base_path / spec.filename
    if not pdf_path.exists():
        print(f"    ❌ No existe: {pdf_path}")
        return False

    print(f"    📄 PDF: {pdf_path}")

    if not dry_run:
        deleted = delete_chunks(supabase, spec.document_id)
        print(f"    🗑️  Chunks previos eliminados: {deleted}")
        upsert_document(supabase, spec, source_path=str(pdf_path))
    else:
        print("    🧪 DRY-RUN: no se borran ni insertan registros")

    print("    📄 Extrayendo páginas...")
    pages = extract_pages(pdf_path)

    print("    ✂️  Chunking article-first (por artículo)...")
    chunks = chunk_article_first(pages)
    print(f"    ✂️  Chunks: {len(chunks)}")

    article_ids = {c.article_id for c in chunks if c.article_id}
    print(f"    📊 Artículos únicos detectados: {len(article_ids)}")
    if article_ids:
        print(f"    📋 Ejemplos: {', '.join(sorted(list(article_ids))[:12])}...")

    if dry_run:
        return True

    print("    🧠 Embeddings...")
    embeddings: List[Optional[List[float]]] = []
    for i in range(0, len(chunks), BATCH_SIZE_EMBED):
        batch = chunks[i:i + BATCH_SIZE_EMBED]
        embs = embed_batch(openai_client, [c.text for c in batch])
        embeddings.extend(embs)
        time.sleep(DELAY_EMBEDDING)
        done = min(i + BATCH_SIZE_EMBED, len(chunks))
        if done % 100 < BATCH_SIZE_EMBED or done == len(chunks):
            print(f"      Progreso embeddings: {done}/{len(chunks)}")

    print("    💾 Insertando chunks...")
    ok = 0
    bad = 0
    for idx, (c, emb) in enumerate(zip(chunks, embeddings)):
        if emb is None:
            bad += 1
            continue

        payload = {
            "document_id": spec.document_id,
            "norm_kind": ("PREAMBULO" if c.article_id == "PREAMBULO" else "ARTICLE"),
            "norm_id": c.article_id,
            "text": c.text,
            "embedding": emb,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "metadata": {
                "article_id": c.article_id,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "chunk_index": c.chunk_index,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "source": "reingest_unico_ruta2",
            },
        }

        try:
            supabase.table("chunks").insert(payload).execute()
            ok += 1
        except Exception as e:
            bad += 1
            if bad <= 3:
                print(f"      ⚠️ Insert fallo chunk {idx}: {str(e)[:120]}")
        time.sleep(DELAY_INSERT)
        if (idx + 1) % 100 == 0:
            print(f"      Progreso inserts: {idx + 1}/{len(chunks)} (✅{ok} ❌{bad})")

    print(f"    ✅ Inserts: {ok}/{len(chunks)}")
    if bad:
        print(f"    ⚠️ Fallidos: {bad}")

    return ok > 0


# -----------------------------
# CLI
# -----------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SAS Fiscal — Reingesta ÚNICA (Ruta 2)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("laws", help="Reingesta Leyes/Reglamentos (article-first)")
    pl.add_argument("--base-path", default="data/LEYES_FEDERALES", help="Carpeta base de PDFs")
    pl.add_argument("--all", action="store_true", help="Procesa todas las leyes del baseline")
    pl.add_argument("--doc", action="append", default=[], help="Procesa solo estos document_id (puede repetirse)")
    pl.add_argument("--dry-run", action="store_true", help="No borra ni inserta; solo reporta detección")

    pr = sub.add_parser("rmf", help="Reingesta RMF/Anexos (referencias) — stub")
    pr.add_argument("--base-path", default="data/RMF", help="Carpeta base")

    return p


def main() -> None:
    args = build_parser().parse_args()

    _require_env()

    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    if args.cmd == "laws":
        base_path = Path(args.base_path)
        if not base_path.exists():
            raise SystemExit(f"❌ base-path no existe: {base_path}")

        if not args.all and not args.doc:
            raise SystemExit("❌ Debes indicar --all o al menos un --doc")

        specs = LEYES_BASELINE
        if args.doc:
            wanted = set(args.doc)
            specs = [s for s in specs if s.document_id in wanted]
            missing = wanted - {s.document_id for s in specs}
            if missing:
                print(f"⚠️ document_id no encontrados en baseline: {', '.join(sorted(missing))}")

        print("=" * 70)
        print("REINGESTA ÚNICA — LEYES (Ruta 2)")
        print(f"Base path: {base_path.resolve()}")
        print(f"Docs: {len(specs)} | dry-run={bool(args.dry_run)}")
        print("=" * 70)

        ok = 0
        bad = 0
        for i, spec in enumerate(specs, 1):
            print(f"\n[{i}/{len(specs)}] {spec.title} ({spec.document_id})")
            try:
                if reingest_law(openai_client, supabase, spec, base_path, dry_run=bool(args.dry_run)):
                    ok += 1
                else:
                    bad += 1
            except Exception as e:
                bad += 1
                print(f"    ❌ Error: {e}")

        print("\n" + "=" * 70)
        print(f"✅ Éxitos: {ok} | ❌ Fallos: {bad}")
        print("=" * 70)
        return

    if args.cmd == "rmf":
        raise SystemExit(
            "⚠️ Modo rmf aún no implementado en este script. "
            "(Siguiente paso: metadata.referenced_articles, sin article_id.)"
        )


if __name__ == "__main__":
    main()
