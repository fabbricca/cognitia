"""Cognitia API (K8s web tier).

Frontend-facing API that serves REST endpoints and the web UI.

Realtime:
- Chat streaming: sentence-level SSE (POST /api/chat/stream)
- Calls: LiveKit (WebRTC)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .cache import init_cache, close_cache
from .database import init_db
from .memory_client import memory_client
from .routes_auth import router as auth_router
from .routes_characters import router as characters_router
from .routes_chats import router as chats_router
from .routes_call import router as call_router
from .routes_memory import router as memory_router
from .routes_stream import router as stream_router
from .routes_models import router as models_router
from .routes_subscription import router as subscription_router
from .schemas import HealthResponse
from .streams import publisher


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    await init_db()
    await init_cache()
    await publisher.connect()
    logger.info("Cognitia API started")
    yield
    await publisher.close()
    await close_cache()
    logger.info("Cognitia API shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    app = FastAPI(
        title="Cognitia API",
        description="Voice assistant API with authentication and GPU backend proxy",
        version="3.0.0",
        lifespan=lifespan,
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    # Routers define their own prefixes (e.g. /auth, /characters, /chats, /memory),
    # so we mount them once under /api.
    app.include_router(auth_router, prefix="/api")
    app.include_router(characters_router, prefix="/api")
    app.include_router(chats_router, prefix="/api")
    app.include_router(call_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.include_router(models_router, prefix="/api")
    app.include_router(subscription_router, prefix="/api")
    app.include_router(stream_router, prefix="/api")
    
    # Favicon
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)
    
    # Health check
    @app.get("/health", tags=["health"])
    @app.get("/api/health", response_model=HealthResponse, tags=["health"])
    async def health_check():
        """Health check endpoint."""
        # Check memory service availability
        memory_status = "unavailable"
        try:
            is_available = await memory_client.check_health()
            if is_available:
                memory_status = "healthy"
        except Exception as e:
            logger.debug(f"Memory service health check failed: {e}")
            memory_status = "unavailable"

        return HealthResponse(memory_service=memory_status)

    return app

# Create app instance
app = create_app()

# Mount static files (must be last)
web_dir = Path("/app/web")
if not web_dir.exists():
    web_dir = Path(__file__).parent.parent.parent.parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")


def run():
    """Run the server."""
    import uvicorn
    uvicorn.run(
        "cognitia.api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=os.getenv("API_RELOAD", "false").lower() == "true",
    )


if __name__ == "__main__":
    run()
