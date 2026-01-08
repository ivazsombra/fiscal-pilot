import os
from dotenv import load_dotenv

# Carga el archivo .env si existe (útil para local)
load_dotenv()

# Prioriza la variable de entorno del sistema (Render) sobre la local
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Buscamos DATABASE_URL (nombre estándar en Render) o DIRECT_URL
DIRECT_URL = os.getenv("DATABASE_URL") or os.getenv("DIRECT_URL")

MODEL_EMBED = "text-embedding-3-small"
MODEL_CHAT = "gpt-4o"