# app/services/retrieval/doc_router.py
import re
from typing import List

# --- PASO 1: DEFINIR LAS LEYES ---
# Aquí simplemente listamos el nombre de la ley en la DB y sus siglas comunes.
# Si mañana agregas una ley nueva, solo añades una línea aquí.
LAW_MAPPING = {
    "CONSTITUCION_POLITICA_ESTADOS_UNIDOS_MEXICANOS": [r"cpeum", r"constituci[oó]n"],
    "LEY_DEL_IMPUESTO_SOBRE_LA_RENTA": [r"lisr", r"isr", r"renta"],
    "CODIGO_FISCAL_DE_LA_FEDERACION": [r"cff", r"c[oó]digo fiscal"],
    "LEY_DEL_IMPUESTO_VALOR_AGREGADO": [r"iva", r"valor agregado"],
    "LEY_IMPUESTO_ESPECIAL_PRODUCCION_SERVICIOS": [r"ieps", r"especial"],
    "LEY_ADUANERA": [r"aduanera", r"aduana"],
    "LEY_FEDERAL_IMPUESTO_SOBRE_AUTOMOVILES_NUEVOS": [r"isan", r"autom[oó]viles"],
    "CONVENCION_MULTILATERAL_BEPS_(MLI)_OCDE": [r"beps", r"ocde"],
    "LEY FEDERAL DE LOS DERECHOS DEL CONTRIBUYENTE DOF 23055005": [r"derechos del contribuyente"]
}

# --- PASO 2: DOCUMENTOS BASE ---
# Estos se consultan siempre si el usuario no menciona una ley específica.
BASE_LEGAL_DOCS = [
    "CONSTITUCION_POLITICA_ESTADOS_UNIDOS_MEXICANOS",
    "CODIGO_FISCAL_DE_LA_FEDERACION",
    "LEY_DEL_IMPUESTO_SOBRE_LA_RENTA"
]

# --- PASO 3: LA FUNCIÓN QUE DECIDE ---
def resolve_candidate_documents(question: str) -> List[str]:
    """
    Esta función lee la pregunta del usuario y decide qué leyes buscar.
    """
    q = (question or "").lower()
    resolved = []

    # Revisamos nuestra lista de leyes (LAW_MAPPING)
    for doc_id, patterns in LAW_MAPPING.items():
        for p in patterns:
            if re.search(rf"\b{p}\b", q):
                resolved.append(doc_id)
                # Si encontramos la ley, también sugerimos su reglamento automáticamente
                REG_MAP = {
                    "CODIGO_FISCAL_DE_LA_FEDERACION": "REGLAMENTO_CODIGO_FISCAL_FEDERACION",
                    "LEY_DEL_IMPUESTO_SOBRE_LA_RENTA": "REGLAMENTO_LEY_IMPUESTO_SOBRE_RENTA",
                    "LEY_DEL_IMPUESTO_VALOR_AGREGADO": "REGLAMENTO_LEY_DEL_IMPUESTO_VALOR_AGREGADO",
                    "LEY_ADUANERA": "REGLAMENTO_LEY_ADUANERA",
                }
                reg = REG_MAP.get(doc_id)
                if reg:
                    resolved.append(reg)

                break # Ya encontramos esta ley, pasamos a la siguiente

    # Si no detectamos ninguna ley, usamos las 3 básicas (Constitución, CFF, LISR)
    if not resolved:
        return BASE_LEGAL_DOCS
    
    # Quitamos duplicados por si acaso
    return list(dict.fromkeys(resolved))
