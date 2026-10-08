"""FastAPI entry point. Owner: Coder 3. Run from backend/: uvicorn main:app --reload --port 8000"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Vision Assistant API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # BE-01 moves this to ALLOWED_ORIGINS in config.py
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok", "version": "1.0.0", "models": {}, "uptime_s": 0}
