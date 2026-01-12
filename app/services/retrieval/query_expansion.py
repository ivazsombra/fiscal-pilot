# app/services/retrieval/query_expansion.py
"""
Query Expansion para términos fiscales mexicanos.
Expande la consulta del usuario con sinónimos y términos relacionados
para mejorar la recuperación de información.
"""

import re
from typing import List, Tuple

# Diccionario de expansión de términos fiscales
# Formato: término_usuario -> [términos_relacionados_para_buscar]
FISCAL_SYNONYMS = {
    # Límites y exenciones
    "límite": ["exención", "tope", "máximo", "monto máximo", "cantidad máxima"],
    "limite": ["exención", "tope", "máximo", "monto máximo", "cantidad máxima"],
    "tope": ["límite", "exención", "máximo"],
    "exención": ["límite", "exento", "no gravado", "no sujeto al pago"],
    "exento": ["exención", "no gravado", "límite"],
    
    # Salarios y UMA
    "salario mínimo": ["UMA", "unidad de medida", "veces el salario", "siete veces"],
    "uma": ["salario mínimo", "unidad de medida y actualización"],
    "veces": ["salario mínimo", "UMA", "siete veces", "equivalente"],
    
    # Deducciones
    "deducción": ["deducible", "deducir", "gasto deducible"],
    "deducir": ["deducción", "deducible"],
    "deducible": ["deducción", "requisitos de deducción"],
    
    # Previsión social
    "previsión social": ["prestaciones", "beneficios trabajadores", "seguridad social"],
    "prestaciones": ["previsión social", "beneficios"],
    
    # Requisitos
    "requisitos": ["condiciones", "requisito", "cumplir", "obligaciones"],
    "requisito": ["requisitos", "condiciones"],
    
    # Artículos específicos
    "fracción xi": ["fracción 11", "once"],
    "fracción 11": ["fracción XI", "once"],
    
    # Personas morales/físicas
    "persona moral": ["empresa", "sociedad", "contribuyente persona moral"],
    "persona física": ["individuo", "contribuyente persona física"],
    
    # Ingresos
    "ingreso acumulable": ["ingreso gravable", "base gravable"],
    "ingreso exento": ["exención", "no acumulable"],
}

# Patrones de preguntas que requieren expansión específica
EXPANSION_PATTERNS = [
    # Patrón: pregunta sobre límites de deducción/exención
    (
        r"(límite|limite|tope|máximo).*(deducción|deducir|exención|exento|previsión)",
        ["siete veces el salario mínimo", "salario mínimo general", "UMA", 
         "cantidad equivalente", "monto de la exención", "ingreso no sujeto"]
    ),
    # Patrón: pregunta sobre cuánto/cuántos
    (
        r"(cuánto|cuanto|cuántos|cuantos).*(deducir|exento|exención|límite)",
        ["veces el salario", "salario mínimo", "UMA", "monto máximo", "cantidad"]
    ),
    # Patrón: pregunta sobre porcentajes
    (
        r"(porcentaje|%|por ciento).*(deducción|deducible|límite)",
        ["proporción", "fracción", "parte", "monto"]
    ),
]


def expand_query(question: str) -> Tuple[str, List[str]]:
    """
    Expande la consulta del usuario con términos relacionados.
    
    Args:
        question: Pregunta original del usuario
        
    Returns:
        Tuple con:
        - expanded_query: Consulta expandida para embedding
        - keywords: Lista de palabras clave adicionales para búsqueda híbrida
    """
    q_lower = question.lower()
    additional_terms = []
    keywords = []
    
    # 1. Buscar sinónimos directos
    for term, synonyms in FISCAL_SYNONYMS.items():
        if term in q_lower:
            additional_terms.extend(synonyms[:3])  # Máximo 3 sinónimos por término
            keywords.extend(synonyms[:2])
    
    # 2. Aplicar patrones de expansión específicos
    for pattern, expansions in EXPANSION_PATTERNS:
        if re.search(pattern, q_lower, re.IGNORECASE):
            additional_terms.extend(expansions)
            keywords.extend(expansions[:3])
    
    # 3. Construir consulta expandida
    # Removemos duplicados manteniendo orden
    seen = set()
    unique_terms = []
    for term in additional_terms:
        if term.lower() not in seen:
            seen.add(term.lower())
            unique_terms.append(term)
    
    # La consulta expandida es la original + términos adicionales
    if unique_terms:
        expanded_query = f"{question} ({', '.join(unique_terms[:5])})"
    else:
        expanded_query = question
    
    # Keywords únicos para búsqueda híbrida
    unique_keywords = list(set(keywords))[:5]
    
    return expanded_query, unique_keywords


def get_keyword_filter(keywords: List[str]) -> str:
    """
    Genera un filtro SQL para búsqueda por palabras clave.
    
    Args:
        keywords: Lista de palabras clave
        
    Returns:
        Fragmento SQL para filtrar por keywords (usando ILIKE)
    """
    if not keywords:
        return ""
    
    conditions = []
    for kw in keywords:
        # Escapamos comillas simples
        safe_kw = kw.replace("'", "''")
        conditions.append(f"text ILIKE '%{safe_kw}%'")
    
    return " OR ".join(conditions)


# Función de prueba
if __name__ == "__main__":
    test_questions = [
        "¿Cuál es el límite de deducción de previsión social?",
        "¿Cuántos salarios mínimos es el tope de exención?",
        "¿Qué requisitos hay para deducir gastos?",
        "¿Qué dice el artículo 27 fracción XI?",
    ]
    
    for q in test_questions:
        expanded, keywords = expand_query(q)
        print(f"\nOriginal: {q}")
        print(f"Expandida: {expanded}")
        print(f"Keywords: {keywords}")
