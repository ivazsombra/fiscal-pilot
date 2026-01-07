import os
from supabase import create_client, Client
from dotenv import load_dotenv

# Cargar las variables del archivo .env (asegúrate de que el .env esté en la raíz del proyecto)
load_dotenv()

# Obtener URL y KEY de las variables de entorno
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ Error: Faltan las credenciales SUPABASE_URL o SUPABASE_KEY en el archivo .env")

# Crear y exportar la instancia del cliente
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("✅ Conexión a Supabase inicializada correctamente.")