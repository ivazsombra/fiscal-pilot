import os
import sys

# Agregamos el directorio actual al path para importar 'app'
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from app.core.supabase_client import supabase
except ImportError as e:
    print("❌ Error: No se pudo cargar el cliente de Supabase.")
    sys.exit(1)

# --- CONFIGURACIÓN ---
RUTA_DATA = "data" 

def obtener_ids_en_db():
    """Descarga los IDs usando el nombre correcto de la columna: document_id"""
    print("🔌 Consultando Supabase...")
    try:
        # CORRECCIÓN AQUÍ: Usamos 'document_id' en lugar de 'id'
        response = supabase.table("documents").select("document_id").range(0, 9999).execute()
        
        # Guardamos en un set para búsqueda rápida
        ids = {item['document_id'] for item in response.data}
        return ids
    except Exception as e:
        print(f"❌ Error conectando a Supabase: {e}")
        return set()

def auditar():
    print(f"--- 🔍 AUDITORÍA DE SINCRONIZACIÓN ---")
    
    # 1. Obtener inventario de Base de Datos
    ids_db = obtener_ids_en_db()
    
    if not ids_db:
        print("⚠️ La base de datos parece vacía (o tiene 0 documentos).")
    else:
        print(f"✅ Documentos registrados en DB: {len(ids_db)}")

    # 2. Escanear archivos locales
    print(f"📂 Escaneando carpeta '{RUTA_DATA}'...")
    archivos_pendientes = []
    total_encontrados = 0

    if not os.path.exists(RUTA_DATA):
        print(f"❌ Error: No existe la carpeta '{RUTA_DATA}'.")
        return

    for root, dirs, files in os.walk(RUTA_DATA):
        for file in files:
            if file.lower().endswith(".pdf"):
                total_encontrados += 1
                
                # Lógica de ID: Nombre del archivo sin extensión
                # Ejemplo: "RMF2026.pdf" -> "RMF2026"
                doc_id = os.path.splitext(file)[0]
                
                # Verificamos si este ID ya existe en la lista de Supabase
                if doc_id not in ids_db:
                    # Si no está, lo agregamos a la lista de pendientes con su ruta completa
                    # (Guardamos la ruta completa para que el procesador sepa dónde buscarlo)
                    ruta_completa = os.path.join(root, file)
                    archivos_pendientes.append(ruta_completa)

    print(f"📄 Total PDFs en disco: {total_encontrados}")

    # 3. Generar reporte
    print("\n" + "=" * 40)
    print("📊 RESULTADOS")
    print("=" * 40)

    if not archivos_pendientes:
        print("🎉 ¡TODO SINCRONIZADO! No falta ningún archivo en la DB.")
        if os.path.exists("lista_para_reprocesar.txt"):
            os.remove("lista_para_reprocesar.txt")
    else:
        print(f"⚠️ SE DETECTARON {len(archivos_pendientes)} ARCHIVOS FALTANTES.")
        
        nombre_salida = "lista_para_reprocesar.txt"
        with open(nombre_salida, "w", encoding="utf-8") as f:
            for ruta in archivos_pendientes:
                # Guardamos la ruta completa para facilitar la carga después
                f.write(f"{ruta}\n")
        
        print(f"\n💾 Se generó el archivo: '{nombre_salida}'")

if __name__ == "__main__":
    auditar()