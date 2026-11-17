import shutil
import subprocess
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Local AI Video Generator", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/system")
def system():
    path = shutil.which("ffmpeg")
    version = None
    if path:
        result = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=5, check=False)
        version = result.stdout.splitlines()[0] if result.stdout else None
    return {"ffmpeg_available": path is not None, "ffmpeg_version": version}

from .projects import router
app.include_router(router)
from .rendering import router as render_router
app.include_router(render_router)
