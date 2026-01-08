import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.supabase_client import supabase
import fitz  # PyMuPDF
from openai import OpenAI
import re
import json

# Configuración OPTIMIZADA
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"
client = OpenAI(api_key=OPENAI_API_KEY)

def extract_text_with_structure(pdf_path: str) -> str:
    """Extrae texto manteniendo estructura legal"""
    doc = fitz.open(pdf_path)
    full_text = ""
    
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")
        
        # Mejorar estructura para documentos legales
        text = re.sub(r'\n\s*\n', '\n\n', text)  # Normalizar saltos
        text = re.sub(r'(\d+)\.\s+([A-Z])', r'\1. \2', text)  # Artículos
        full_text += text + "\n\n"
    
    return full_text

def smart_chunking_legal_text(text: str, target_chars: int = 600, overlap: int = 150) -> list:
    """
    Chunking inteligente para textos legales:
    - Respeta límites naturales (artículos, secciones)
    - Tamaño óptimo para embeddings
    - Overlap para mantener contexto
    """
    # Primero, dividir por secciones naturales
    sections = []
    
    # Dividir por capítulos, artículos, secciones
    pattern = r'(CAP[ÍI]TULO\s+\d+|Art[íi]culo\s+\d+|Secci[óo]n\s+\d+\.\d+|[IVXLCDM]+\.\s+[A-Z])'
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    
    if len(matches) > 5:  # Si tiene estructura clara
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            section_text = text[start:end].strip()
            if section_text:
                sections.append(section_text)
    else:
        # Fallback: dividir por párrafos largos
        paragraphs = text.split('\n\n')
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
                
            if len(current_chunk) + len(para) + 1 > target_chars and current_chunk:
                sections.append(current_chunk)
                current_chunk = para
            else:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
        
        if current_chunk:
            sections.append(current_chunk)
    
    # Ahora crear chunks con overlap
    chunks = []
    for i, section in enumerate(sections):
        words = section.split()
        
        # Si la sección es muy grande, subdividirla
        if len(words) > 800:
            num_subchunks = (len(words) // 500) + 1
            for j in range(num_subchunks):
                start = j * 500
                end = min(start + 500 + 100, len(words))  # Overlap interno
                subchunk_text = ' '.join(words[start:end])
                
                chunks.append({
                    'text': subchunk_text,
                    'section_index': i,
                    'subchunk': j,
                    'source_section': section[:100] if section else ''
                })
        else:
            chunks.append({
                'text': section,
                'section_index': i,
                'subchunk': 0,
                'source_section': ''
            })
    
    return chunks

def reprocess_rmf2026():
    """Reprocesa RMF2026 con chunking optimizado"""
    
    document_id = "RMF2026-DOF 28122025"
    pdf_filename = "RMF2026-DOF 28122025.pdf"
    
    # Buscar archivo
    base_path = "E:/Documents/AGENTE FISCAL/saas_fiscal/data"
    pdf_path = None
    
    for root, dirs, files in os.walk(base_path):
        if pdf_filename in files:
            pdf_path = os.path.join(root, pdf_filename)
            break
    
    if not pdf_path:
        print(f"❌ No se encontró: {pdf_filename}")
        return
    
    print(f"✅ Archivo encontrado: {pdf_path}")
    print(f"📄 Reprocesando {document_id}...")
    
    # 1. Extraer texto
    print("📖 Extrayendo texto...")
    raw_text = extract_text_with_structure(pdf_path)
    print(f"   Texto extraído: {len(raw_text):,} caracteres")
    print(f"   Aprox. {len(raw_text.split()):,} palabras")
    
    # 2. Chunking inteligente
    print("✂️  Creando chunks optimizados...")
    chunks = smart_chunking_legal_text(raw_text, target_chars=600, overlap=150)
    print(f"   Creados {len(chunks)} chunks (antes: 20)")
    
    # 3. Eliminar chunks existentes
    print("🗑️  Eliminando chunks antiguos...")
    try:
        supabase.table("chunks").delete().eq("document_id", document_id).execute()
        print(f"   Eliminados 20 chunks antiguos")
    except Exception as e:
        print(f"   Error eliminando: {e}")
    
    # 4. Insertar nuevos chunks en BATCHES PEQUEÑOS
    print("📤 Insertando nuevos chunks...")
    BATCH_SIZE = 3  # Pequeño para evitar timeout
    total_inserted = 0
    
    for batch_start in range(0, len(chunks), BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, len(chunks))
        batch = chunks[batch_start:batch_end]
        
        batch_data = []
        for i, chunk in enumerate(batch):
            try:
                # Obtener embedding
                embedding = client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    input=chunk['text']
                ).data[0].embedding
                
                # Preparar metadata enriquecida
                metadata = {
                    "chunk_index": batch_start + i,
                    "source": pdf_filename,
                    "path": pdf_path,
                    "chunk_size": len(chunk['text']),
                    "total_chunks": len(chunks),
                    "section_index": chunk.get('section_index'),
                    "subchunk": chunk.get('subchunk', 0),
                    "avg_chars": len(chunk['text']),
                    "word_count": len(chunk['text'].split())
                }
                
                batch_data.append({
                    "document_id": document_id,
                    "text": chunk['text'],
                    "embedding": embedding,
                    "metadata": metadata
                })
                
            except Exception as e:
                print(f"   Error preparando chunk {batch_start + i}: {e}")
                continue
        
        # Insertar batch
        if batch_data:
            try:
                supabase.table("chunks").insert(batch_data).execute()
                total_inserted += len(batch_data)
                print(f"   Batch {batch_start//BATCH_SIZE + 1}: {len(batch_data)} chunks insertados")
                
                # Pequeña pausa entre batches
                import time
                time.sleep(0.5)
                
            except Exception as e:
                print(f"   ❌ Error insertando batch: {e}")
                # Intentar insertar uno por uno
                for item in batch_data:
                    try:
                        supabase.table("chunks").insert([item]).execute()
                        total_inserted += 1
                    except:
                        print(f"   ❌ Error con chunk individual, saltando...")
    
    print(f"\n🎉 REPROCESAMIENTO COMPLETADO:")
    print(f"   Documento: {document_id}")
    print(f"   Chunks antiguos: 20")
    print(f"   Chunks nuevos: {total_inserted}")
    print(f"   Mejora: {total_inserted/20:.1f}x más contexto")
    print(f"   Tamaño promedio: ~600 caracteres por chunk")
    
    # Verificar en DB
    response = supabase.table("chunks").select("chunk_id", count="exact").eq("document_id", document_id).execute()
    print(f"   Verificación DB: {response.count} chunks encontrados")

if __name__ == "__main__":
    reprocess_rmf2026()