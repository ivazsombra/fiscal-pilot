import os
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv

# 1. Cargar entorno
load_dotenv()

# 2. Configurar credenciales
DIRECT_URL = os.getenv("DIRECT_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DIRECT_URL or not OPENAI_API_KEY:
    print("❌ Error: Falta DIRECT_URL o OPENAI_API_KEY en el archivo .env")
    exit()

# Cliente OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

def get_embedding(text):
    """Genera el embedding usando el modelo configurado"""
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

def inspeccionar_texto(query):
    print(f"\n🔬 DIAGNÓSTICO (Vía SQL Directo) PARA: '{query}'")
    print("-" * 60)
    
    conn = None
    try:
        # 1. Generar Vector
        print("1. Generando embedding...")
        vector = get_embedding(query)
        
        # 2. Conectar a DB
        print("2. Conectando a PostgreSQL...")
        conn = psycopg2.connect(DIRECT_URL)
        cur = conn.cursor()
        
        # 3. Ejecutar consulta SQL cruda con CAST EXPLÍCITO
        print("3. Ejecutando búsqueda...")
        
        # --- AQUÍ ESTABA EL ERROR, AGREGAMOS ::vector ---
        sql = """
        SELECT content, metadata 
        FROM match_documents(
            %s::vector,  -- <--- EL CAMBIO CLAVE ESTÁ AQUÍ
            0.4, 
            1
        );
        """
        
        cur.execute(sql, (vector,))
        resultado = cur.fetchone()
        
        if resultado:
            content = resultado[0]
            metadata = resultado[1]
            archivo = metadata.get('source_filename', 'Desconocido') # Ajusté a source_filename según tu schema
            
            print(f"\n📄 Archivo Origen: {archivo}")
            print("\n--- INICIO DEL TEXTO REAL EN BASE DE DATOS ---")
            print(content[:300]) # Primeros 300 caracteres
            print("--- FIN DEL TEXTO REAL ---\n")
            
            # Verificación visual automática
            if " " not in content[:50]:
                print("🚨 RESULTADO: El texto está COMPRIMIDO (sin espacios).")
                print("👉 CAUSA: El script de PDF unió las líneas sin separador.")
            else:
                print("✅ RESULTADO: El texto TIENE espacios correctamente.")
                print("👉 CAUSA: El problema es visual en el frontend/agente.")
        else:
            print("❌ No se encontraron coincidencias. Intenta bajar el umbral (0.4) si es necesario.")
            
        cur.close()

    except Exception as e:
        print(f"\n❌ ERROR TÉCNICO: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    inspeccionar_texto("Novena modificación anexo 15")