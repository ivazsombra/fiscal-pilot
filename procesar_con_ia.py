import fitz  # PyMuPDF
import time
import os
from openai import OpenAI
from dotenv import load_dotenv
from app.core.supabase_client import supabase

# Cargar variables de entorno
load_dotenv()

# Configurar cliente OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# CONFIGURACIÓN
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
BATCH_SIZE = 10 
MODELO_EMBEDDING = "text-embedding-3-small" 

def procesar_pdf(ruta_pdf):
    """Extrae texto y lo divide en fragmentos con traslape."""
    try:
        doc = fitz.open(ruta_pdf)
        texto = ""
        for pagina in doc:
            texto += pagina.get_text("text") + "\n"
        
        chunks = []
        inicio = 0
        while inicio < len(texto):
            fin = inicio + CHUNK_SIZE
            chunk = texto[inicio:fin].replace("\n", " ")
            chunks.append(chunk)
            inicio += (CHUNK_SIZE - CHUNK_OVERLAP)
        return chunks
    except Exception as e:
        print(f"   ⚠️ Error leyendo PDF {ruta_pdf}: {e}")
        return []

def generar_embeddings_lote(textos):
    """Genera vectores usando OpenAI para una lista de textos."""
    try:
        response = client.embeddings.create(
            input=textos,
            model=MODELO_EMBEDDING
        )
        return [data.embedding for data in response.data]
    except Exception as e:
        print(f"⚠️ Error OpenAI: {e}")
        time.sleep(5) 
        try:
            response = client.embeddings.create(
                input=textos,
                model=MODELO_EMBEDDING
            )
            return [data.embedding for data in response.data]
        except:
            return None

def ejecutar_carga_maestra():
    print(f"🚀 INICIANDO CARGA MAESTRA (RECURSIVA) CON OPENAI ({MODELO_EMBEDDING})...")
    
    carpeta_raiz = "data"
    if not os.path.exists(carpeta_raiz):
        print(f"❌ Error: No encuentro la carpeta '{carpeta_raiz}'")
        return

    # --- CAMBIO IMPORTANTE: Búsqueda Recursiva ---
    archivos_para_procesar = []
    # os.walk recorre el árbol de carpetas (entra a 2022, 2025, etc.)
    for root, dirs, files in os.walk(carpeta_raiz):
        for file in files:
            if file.lower().endswith('.pdf'):
                # Guardamos la ruta completa para poder abrirlo
                ruta_completa = os.path.join(root, file)
                archivos_para_procesar.append(ruta_completa)

    print(f"📂 Archivos detectados en subcarpetas: {len(archivos_para_procesar)}")
    
    for ruta_completa in archivos_para_procesar:
        # Extraemos solo el nombre del archivo para usarlo como ID
        nombre_archivo = os.path.basename(ruta_completa)
        doc_id = nombre_archivo.replace(".pdf", "")
        
        print(f"\n⚡ Procesando: {doc_id}")
        
        try:
            # A. Fragmentar
            fragmentos_texto = procesar_pdf(ruta_completa)
            
            if not fragmentos_texto:
                print("   ⚠️ Archivo vacío o ilegible. Saltando...")
                continue

            print(f"   - Texto fragmentado en {len(fragmentos_texto)} partes.")
            
            # B. Limpiar versión anterior
            # (Borramos los chunks viejos de este documento para no duplicar)
            supabase.table("chunks").delete().eq("document_id", doc_id).execute()
            
            # C. Procesar por lotes
            for i in range(0, len(fragmentos_texto), BATCH_SIZE):
                lote_textos = fragmentos_texto[i : i + BATCH_SIZE]
                
                # 1. Generar Embeddings (OpenAI)
                vectores = generar_embeddings_lote(lote_textos)
                
                if vectores:
                    datos_subida = []
                    for idx, (txt, vec) in enumerate(zip(lote_textos, vectores)):
                        datos_subida.append({
                            "document_id": doc_id,
                            "text": txt,
                            "embedding": vec,
                            "metadata": {
                                "source": nombre_archivo, 
                                "chunk_index": i + idx,
                                "path": ruta_completa # Guardamos dónde estaba por si acaso
                            }
                        })
                    
                    supabase.table("chunks").insert(datos_subida).execute()
                    print(f"     ✅ Lote {i//BATCH_SIZE + 1} subido.")
                else:
                    print(f"     ❌ Falló OpenAI en el lote {i}")
                
                time.sleep(0.5) 

            print(f"   ✨ Documento {doc_id} terminado.")

        except Exception as e:
            print(f"   ❌ Error en {nombre_archivo}: {e}")

if __name__ == "__main__":
    ejecutar_carga_maestra()