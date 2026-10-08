"""FastAPI entry point. Owner: Coder 3. Run from backend/: uvicorn main:app --reload --port 8000"""
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from speech import server_audio

app = FastAPI(title="Vision Assistant API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # BE-01 moves this to ALLOWED_ORIGINS in config.py
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str
    lang: str = "en-IN"


def _speech_http_error(error: server_audio.SpeechServiceError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": str(error)},
    )


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok", "version": "1.0.0", "models": {}, "uptime_s": 0}


@app.post("/api/v1/tts", response_class=Response, tags=["speech"])
def text_to_speech(request: TTSRequest) -> Response:
    try:
        audio, content_type = server_audio.text_to_speech(request.text, request.lang)
    except server_audio.SpeechServiceError as error:
        raise _speech_http_error(error) from error
    return Response(content=audio, media_type=content_type)


@app.post("/api/v1/stt", tags=["speech"])
def speech_to_text(
    audio: UploadFile = File(...),
    lang: str = Form("en-IN"),
) -> dict[str, str | float]:
    try:
        result = server_audio.speech_to_text(
            audio.file.read(),
            content_type=audio.content_type or "",
            lang=lang,
        )
    except server_audio.SpeechServiceError as error:
        raise _speech_http_error(error) from error
    return {"text": result["transcript"], "confidence": result["confidence"]}
