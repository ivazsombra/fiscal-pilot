import os
import psycopg2 

# ==========================================
# ⚙️ CONFIGURACIÓN
# ==========================================

# Apuntamos a la carpeta 'data' que vi en tu estructura
RUTA_PDFS = "data" 

# ⚠️ IMPORTANTE: Pon aquí tus credenciales reales de Supabase
DB_PARAMS = {
    "host": "aws-0-us-west-1.pooler.supabase.com", # Tu host real
    "database": "postgres",
    "user": "postgres.tusuario", # Tu usuario real
    "password": "TU_PASSWORD_AQUI", # <--- ¡PON TU CONTRASEÑA!
    "port": "5432" # Generalmente 5432 o 6543
}

# ==========================================
# 🚀 SCRIPT DE AUDITORÍA
# ==========================================

def auditar_archivos():
    print(f"--- 🔍 AUDITANDO CARPETA: {os.path.abspath(RUTA_PDFS)} ---")
    
    if not os.path.exists(RUTA_PDFS):
        print(f"❌ Error: No encuentro la carpeta 'data'. Asegúrate de estar en 'saas_fiscal'.")
        return

    conn = None
    try:
        # 1. Obtener lo que YA existe en la Base de Datos
        print("🔌 Conectando a Supabase...")
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()
        
        print("📥 Descargando inventario de la base de datos...")
        cursor.execute("SELECT id FROM documents")
        # Creamos un conjunto (Set) para comparar rápido
        ids_en_db = {str(row[0]) for row in cursor.fetchall()} 
        
        print(f"✅ La Base de Datos tiene: {len(ids_en_db)} documentos.")

        # 2. Escanear tu disco (La estructura que me mostraste)
        print(f"📂 Escaneando archivos locales en '{RUTA_PDFS}'...")
        archivos_encontrados = 0
        faltantes = []

        # Recorremos recursivamente (2022, 2025, Anexos, etc.)
        for root, dirs, files in os.walk(RUTA_PDFS):
            for file in files:
                if file.lower().endswith(".pdf"):
                    archivos_encontrados += 1
                    
                    # Asumimos que el ID es el nombre sin extensión
                    id_archivo = os.path.splitext(file)[0]
                    
                    # EL MOMENTO DE LA VERDAD: ¿Está o no está?
                    if id_archivo not in ids_en_db:
                        faltantes.append(file)

        print(f"📄 Total PDFs en disco: {archivos_encontrados}")

        # 3. Generar el reporte final
        print("\n" + "=" * 40)
        
        if not faltantes:
            print("🎉 ¡TODO SINCRONIZADO! No falta nada.")
        else:
            print(f"⚠️ SE ENCONTRARON {len(faltantes)} ARCHIVOS FALTANTES.")
            print("   Generando lista de reparación...")
            
            with open("lista_para_reprocesar.txt", "w", encoding="utf-8") as f:
                for item in faltantes:
                    f.write(f"{item}\n")
            
            print(f"💾 Archivo creado: 'lista_para_reprocesar.txt'")
            print("   (Este archivo contiene exactamente lo que se perdió)")

    except Exception as e:
        print(f"❌ Error: {e}")
        print("   (Verifica tus credenciales en DB_PARAMS)")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    auditar_archivos()