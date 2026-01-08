from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

# Mantenemos tu importación del motor RAG
from app.services.rag_engine import generate_response_with_rag

app = FastAPI(title="Agente Fiscal Pro 2025")

# 1. Conectamos la carpeta "static" que acabas de crear
app.mount("/static", StaticFiles(directory="static"), name="static")

class QueryRequest(BaseModel):
    question: str
    regimen: Optional[str] = "General"
    ejercicio: Optional[int] = 2025

# 2. Ruta principal: Entrega el archivo index.html
@app.get("/")
async def read_root():
    return FileResponse('static/index.html')

# 3. Ruta de estado (movida para no estorbar)
@app.get("/api/health")
def health_check():
    return {"status": "Online", "mode": "Tier 2 RAG", "db": "Supabase"}

@app.post("/chat")
def chat_endpoint(request: QueryRequest):
    try:
        # Tu lógica original intacta
        response = generate_response_with_rag(request.question) 
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)