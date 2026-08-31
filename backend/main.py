import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings, logger
from backend.database import init_db
from backend.services.background_sync import background_sync
from backend.api.routes_emails import router as emails_router
from backend.api.routes_ai import router as ai_router
from backend.api.routes_settings import router as settings_router

# Static files directory
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown routines."""
    logger.info("Initializing Email Assistant backend...")
    init_db()
    
    # Start async background sync loop
    background_sync.start()
    
    yield
    
    # Shutdown
    logger.info("Shutting down Email Assistant backend...")
    background_sync.stop()

app = FastAPI(
    title="Email Assistant API",
    description="Local-first AI-powered email triage, calendar extraction, ghostwriter, and RAG-lite assistant.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for cross-origin local requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler for safe JSON error bodies
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled server error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please check logs for details."}
    )

# Include API routers
app.include_router(emails_router)
app.include_router(ai_router)
app.include_router(settings_router)

# Mount frontend static files
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/", include_in_schema=False)
def serve_index():
    """Serves the single-page application frontend."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Email Assistant backend active. Place index.html in frontend/ to view UI."}
