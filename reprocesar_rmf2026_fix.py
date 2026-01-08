import sys
import os
import re
import json
import time

# Añadir ruta del proyecto
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Intentar importaciones flexibles
try:
    from app.core.supabase_client import supabase
    print("✅ Importación desde app.core.supabase_client")
except ImportError:
    try:
        # Intentar importación directa si supabase está instalado
        from supabase import create_client
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
        
        if not supabase_url or not supabase_key:
            raise ValueError("Faltan variables de entorno SUPABASE_URL o SUPABASE_KEY")
        
        supabase = create_client(supabase_url, supabase_key)
        print("✅ Supabase cliente creado directamente")
    except Exception as e:
        print(f"❌ Error importando supabase: {e}")
        print("\n💡 SOLUCIONES:")
        print("1. Activa tu entorno virtual: venv\\Scripts\\activate")
        print("2. Instala supabase: pip install supabase")
        print("3. O copia la importación de tus otros scripts funcionales")
        sys.exit(1)

try:
    import fitz  # PyMuPDF
    print("✅ PyMuPDF importado")
except ImportError:
    print("❌ PyMuPDF no instalado. Instala con: pip install PyMuPDF")
    sys.exit(1)

try:
    from openai import OpenAI
    print("✅ OpenAI importado")
except ImportError:
    print("❌ OpenAI no instalado. Instala con: pip install openai")
    sys.exit(1)

# Configuración
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("❌ OPENAI_API_KEY no configurada en variables de entorno")
    sys.exit(1)

EMBEDDING_MODEL = "text-embedding-3-small"
client = OpenAI(api_key=OPENAI_API_KEY)

# [TODO: Copia aquí el resto del código desde extract_text_with_structure() en adelante]
# [El resto del código que ya te pasé]