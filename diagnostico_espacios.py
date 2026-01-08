import os
from supabase import create_client
from openai import OpenAI
from dotenv import load_dotenv

# 1. Cargar entorno
load_dotenv()

# 2. Configurar credenciales
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY or not OPENAI_API_KEY:
    print("❌ Error: Faltan variables en el archivo .env (SUPABASE_URL, SUPABASE_SERVICE_KEY o OPENAI_API_KEY)")
    exit()

# 3. Inicializar Clientes
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=OPENAI_API_KEY)

def get_embedding(text):
    """Genera embedding usando OpenAI nativo"""
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

def inspeccionar_texto(query):
    print(f"\n🔬 DIAGNÓSTICO (Modo Nativo) PARA: '{query}'")
    print("-" * 60)
    
    try:
        # Generar vector
        vector = get_embedding(query)
        
        # Consultar Supabase
        response = supabase.rpc(
            "match_documents",
            {
                "query_embedding": vector,
                "match_threshold": 0.4, 
                "match_count": 1
            }
        ).execute()
        
        if response.data:
            fragmento = response.data[0]
            contenido = fragmento.get('content', '')
            archivo = fragmento.get('metadata', {}).get('source', 'Desconocido')
            similitud = fragmento.get('similarity', 0)
            
            print(f"📄 Archivo Origen: {archivo}")
            print(f"📊 Similitud: {similitud:.4f}")
            print("\n--- INICIO DEL TEXTO REAL EN BASE DE DATOS ---")
            print(contenido[:300]) # Primeros 300 caracteres
            print("--- FIN DEL TEXTO REAL ---\n")
            
            # Verificación visual automática
            if " " not in contenido[:50]:
                print("🚨 RESULTADO: El texto está COMPRIMIDO (sin espacios).")
                print("👉 ACCIÓN: Debemos corregir el script 'procesar_fallidos.py' y re-subir.")
            else:
                print("✅ RESULTADO: El texto TIENE espacios correctamente.")
                print("👉 ACCIÓN: El problema es solo de 'display' en el frontend.")
        else:
            print("❌ No se encontraron coincidencias en la base de datos.")
            
    except Exception as e:
        print(f"❌ Error durante la ejecución: {e}")

if __name__ == "__main__":
    inspeccionar_texto("Novena modificación anexo 15")