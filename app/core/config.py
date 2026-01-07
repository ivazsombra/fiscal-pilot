import os
from dotenv import load_dotenv

# Carga variables locales si existen
load_dotenv()

# Variables confirmadas
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DIRECT_URL = os.getenv("DIRECT_URL")  # Usamos el nombre exacto que tienes

# Configuración fija (si deseas cambiar estos modelos, indícamelo)
MODEL_EMBED = "text-embedding-3-small"
MODEL_CHAT = "gpt-4o"