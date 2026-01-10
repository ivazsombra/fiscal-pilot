from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
from app.services.retrieval.doc_router import resolve_candidate_documents
from app.services.rag_engine import generate_response_with_rag

app = FastAPI(title="Agente Fiscal Pro 2025")

app.mount("/static", StaticFiles(directory="static"), name="static")

class QueryRequest(BaseModel):
    question: str
    regimen: Optional[str] = "General"
    ejercicio: Optional[int] = 2025
    trace: Optional[bool] = False # esta linea se coloco para el debug

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

@app.get("/api/health")
def health_check():
    return {"status": "Online", "mode": "Tier 2 RAG", "db": "Supabase"}

@app.post("/chat")
def chat_endpoint(request: QueryRequest):
    try:
        response_text, debug = generate_response_with_rag(
            question=request.question,
            regimen=request.regimen or "General",
            ejercicio=request.ejercicio or 2025,
            trace=bool(getattr(request, "trace", False)),
        )

        payload = {"answer": response_text, "response": response_text}
        if getattr(request, "trace", False):
            payload["debug"] = debug

        return JSONResponse(
            content=payload,
            media_type="application/json; charset=utf-8",
        )


        # Compatibilidad: frontend usa answer; mantenemos response por si algo lo consume
        return JSONResponse(
            content={"answer": response_text, "response": response_text},
            media_type="application/json; charset=utf-8",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
