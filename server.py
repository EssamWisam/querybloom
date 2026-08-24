from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from querybloom.api import api_router


app = FastAPI(
    title="QueryBloom & ABSTAT API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(api_router, prefix="/querybloom")

# Mount frontend build if available (production mode)
webapp_build_dir = Path(__file__).resolve().parent / "webapp" / "build"
if webapp_build_dir.exists():
    app_dir = webapp_build_dir / "_app"
    if app_dir.exists():
        app.mount("/querybloom/_app", StaticFiles(directory=str(app_dir)), name="querybloom_app")
        app.mount("/_app", StaticFiles(directory=str(app_dir)), name="_app")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # 1. Try direct path
        file_path = webapp_build_dir / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))

        # 2. Try stripped querybloom prefix if present
        clean_path = full_path
        if clean_path.startswith("querybloom/"):
            clean_path = clean_path[len("querybloom/"):]
        elif clean_path == "querybloom":
            clean_path = ""

        if clean_path:
            file_path = webapp_build_dir / clean_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))

        return FileResponse(str(webapp_build_dir / "index.html"))


def run():
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("querybloom.server:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    run()
