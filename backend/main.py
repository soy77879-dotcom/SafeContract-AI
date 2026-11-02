
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="SafeContract AI",
    description="청년 임차인을 위한 AI 전월세 계약 사전 검토 시스템",
    version="0.1.0"
)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "SafeContract AI"
    }


# 담당자 A의 프론트엔드가 준비되면 연결
if FRONTEND_DIR.is_dir():

    @app.get("/")
    def home():
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount(
        "/static",
        StaticFiles(directory=FRONTEND_DIR),
        name="static"
    )
