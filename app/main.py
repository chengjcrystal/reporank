"""FastAPI application entry point."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.state import state

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    loaded = state.reload()
    if not loaded:
        print("No index snapshot found. Run: python -m app.cli seed && "
              "python -m app.cli build-index")
    yield


app = FastAPI(title="GitHub Repo Search Engine", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.include_router(router)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "index_loaded": state.engine is not None}


# Serve the frontend if present.
if os.path.isdir(WEB_DIR):
    @app.get("/")
    def index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
