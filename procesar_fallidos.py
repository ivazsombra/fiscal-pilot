import fitz  # PyMuPDF
import time
import os
import sys
from openai import OpenAI
from dotenv import load_dotenv

# Agregamos el path para importar tu módulo de app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from app.core.supabase_client import supabase
except ImportError:
    print("❌ Error: No se pudo importar el cliente de Supabase.")
    sys.exit(1)

# Cargar variables de entorno
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- CONFIGURACIÓN ---
BATCH_SIZE = 5  # Mantenemos 5 para seguridad
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
MODELO_EMBEDDING = "text-embedding-3-small"
ARCHIVO_LISTA = "lista_para_reprocesar.txt"

def leer_lista_pendientes():
    if not os.path.exists(ARCHIVO_LISTA):
        print(f"❌ No encuentro el archivo '{ARCHIVO_LISTA}'.")
        return []
    with open(ARCHIVO_LISTA, "r", encoding="utf-8") as f:
        rutas = [line.strip() for line in f if line.strip()]
    return rutas

def procesar_pdf(ruta_pdf):
    """Extrae texto y lo limpia de caracteres inválidos."""
    try:
        doc = fitz.open(ruta_pdf)
        texto = ""
        for pagina in doc:
            t = pagina.get_text("text")
            # --- CORRECCIÓN CRÍTICA ---
            # Eliminamos los 'Null Bytes' (\x00) que rompen el JSON en Postgres
            t_limpio = t.replace("\x00", "") 
            texto += t_limpio + "\n"
        return texto
    except Exception as e:
        print(f"   ⚠️ Error leyendo PDF: {e}")
        return None

def crear_chunks(texto):
    chunks = []
    inicio = 0
    # Limpieza extra: reemplazar caracteres de control raros
    texto = texto.replace("\x00", "") 
    
    while inicio < len(texto):
        fin = inicio + CHUNK_SIZE
        # Reemplazamos saltos de línea para mejorar el embedding
        chunk = texto[inicio:fin].replace("\n", " ")
        chunks.append(chunk)
        inicio += (CHUNK_SIZE - CHUNK_OVERLAP)
    return chunks

def generar_embeddings(textos):
    try:
        response = client.embeddings.create(input=textos, model=MODELO_EMBEDDING)
        return [data.embedding for data in response.data]
    except Exception:
        time.sleep(2)
        try:
            response = client.embeddings.create(input=textos, model=MODELO_EMBEDDING)
            return [data.embedding for data in response.data]
        except Exception as e:
            print(f"   ❌ Error OpenAI: {e}")
            return None

def insertar_con_reintento(data_chunks, intento=1):
    """Intenta insertar en Supabase con reintentos inteligentes."""
    max_intentos = 5
    try:
        supabase.table("chunks").insert(data_chunks).execute()
        return True
    except Exception as e:
        mensaje = str(e)
        # Reintentamos si es Timeout (57014) o error de conexión
        # A veces el error 'JSON could not be generated' es transitorio, reintentamos también
        es_recuperable = "57014" in mensaje or "timeout" in mensaje.lower() or "json" in mensaje.lower()
        
        if es_recuperable and intento < max_intentos:
            tiempo_espera = intento * 5 
            print(f"     ⏳ Error detectado. Reintentando ({intento}/{max_intentos}) en {tiempo_espera}s...")
            time.sleep(tiempo_espera)
            return insertar_con_reintento(data_chunks, intento + 1)
        else:
            print(f"     ❌ Falló el lote tras {intento} intentos. Error: {mensaje}")
            return False

def ejecutar_reparacion():
    rutas_pendientes = leer_lista_pendientes()
    if not rutas_pendientes:
        print("✅ No hay archivos pendientes.")
        return

    print(f"🚀 INICIANDO REPARACIÓN SANITIZADA ({len(rutas_pendientes)} archivos)")
    
    for ruta_completa in rutas_pendientes:
        nombre_archivo = os.path.basename(ruta_completa)
        doc_id = os.path.splitext(nombre_archivo)[0]
        
        print(f"\n⚡ Procesando: {nombre_archivo}")
        
        if not os.path.exists(ruta_completa):
             posible_ruta = os.path.join("data", ruta_completa) 
             if os.path.exists(posible_ruta):
                 ruta_completa = posible_ruta
             elif not os.path.exists(ruta_completa):
                 print(f"   ⚠️ Archivo no encontrado: {ruta_completa}")
                 continue

        # 1. Fragmentar (con limpieza incluida)
        texto_completo = procesar_pdf(ruta_completa)
        if not texto_completo: continue
        
        fragmentos = crear_chunks(texto_completo)
        print(f"   - {len(fragmentos)} fragmentos limpios listos.")

        # 2. Upsert Documento Padre
        try:
            data_doc = {
                "document_id": doc_id,
                "source_filename": nombre_archivo,
                "source_path": ruta_completa,
                "title": doc_id
            }
            supabase.table("documents").upsert(data_doc).execute()
        except Exception as e:
            print(f"   ❌ Error creando documento padre: {e}")
            continue 

        # 3. Limpieza: Borrar versión anterior corrupta o incompleta
        supabase.table("chunks").delete().eq("document_id", doc_id).execute()

        # 4. Subida
        total_lotes = (len(fragmentos) // BATCH_SIZE) + 1
        print(f"   - Subiendo en {total_lotes} lotes...")

        errores_en_archivo = False
        for i in range(0, len(fragmentos), BATCH_SIZE):
            lote_txt = fragmentos[i : i + BATCH_SIZE]
            vectores = generar_embeddings(lote_txt)
            
            if vectores:
                lista_inserts = []
                for idx, (txt, vec) in enumerate(zip(lote_txt, vectores)):
                    lista_inserts.append({
                        "document_id": doc_id,
                        "text": txt,
                        "embedding": vec,
                        "metadata": {
                            "chunk_index": i + idx,
                            "source": nombre_archivo
                        }
                    })
                
                exito = insertar_con_reintento(lista_inserts)
                if exito:
                    sys.stdout.write(f"\r     ✅ Progreso: {i//BATCH_SIZE + 1}/{total_lotes} lotes")
                    sys.stdout.flush()
                else:
                    errores_en_archivo = True
                    print(f"\n     ❌ Lote {i} perdido definitivamente.")
            
            time.sleep(0.2) 

        print("")
        if not errores_en_archivo:
            print(f"   ✨ {nombre_archivo} FINALIZADO CORRECTAMENTE.")
        else:
            print(f"   ⚠️ {nombre_archivo} terminó con errores parciales.")

    print("\n🏁 PROCESO COMPLETADO.")

if __name__ == "__main__":
    ejecutar_reparacion()