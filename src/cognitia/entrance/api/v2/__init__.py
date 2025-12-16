"""API v2 endpoints."""

from .auth import router as auth_router
from .users import router as users_router
from .characters import router as characters_router
from .chats import router as chats_router

__all__ = [
    "auth_router",
    "users_router",
    "characters_router",
    "chats_router",
]
