from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

# Importamos tu motor de RAG corregido
# Asegúrate de que tu archivo esté en app/services/rag_engine.py
from app.services.rag_engine import generate_response_with_rag # O como se llame tu función principal

app = FastAPI(title="Agente Fiscal Pro 2025")

class QueryRequest(BaseModel):
    question: str
    regimen: Optional[str] = "General"
    ejercicio: Optional[int] = 2025

@app.get("/")
def health_check():
    return {"status": "Online", "mode": "Tier 2 RAG", "db": "Supabase"}

@app.post("/chat")
def chat_endpoint(request: QueryRequest):
    try:
        # Aquí llamamos a tu lógica que usa psycopg2 y OpenAI
        # Nota: Asumo que tu función recibe (pregunta, regimen, ejercicio)
        response = generate_response_with_rag(request.question) 
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)