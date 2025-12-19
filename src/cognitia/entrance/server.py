"""
Cognitia Entrance - Main Server

This is the frontend-facing service that runs in Kubernetes:
- User authentication (JWT)
- Character/Chat CRUD (PostgreSQL)
- WebSocket proxy to GPU Core
- Static file serving for Web UI
"""

import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from uuid import UUID

import httpx
import websockets
from fastapi import (
    Body,
    FastAPI,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy import select, func, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_user_id,
    hash_password,
    verify_password,
    verify_token,
    TokenPayload,
)
from .database import (
    init_db,
    get_session_dep,
    User,
    Character,
    Chat,
    Message,
    Memory,
    UserFact,
    Relationship,
    DiaryEntry,
)
from .schemas_v1 import (
    UserCreate,
    UserLogin,
    UserResponse,
    TokenResponse,
    TokenRefresh,
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    CharacterListResponse,
    ChatCreate,
    ChatResponse,
    ChatListResponse,
    MessageCreate,
    MessageResponse,
    MessageListResponse,
    CursorPaginatedMessages,
    VoiceModelInfo,
    VoiceModelListResponse,
    RVCModelInfo,
    RVCModelListResponse,
    CoreStatusResponse,
    HealthResponse,
    ErrorResponse,
)
from .middleware import SubscriptionMiddleware
from .usage_tracker import usage_tracker
from . import subscription as subscription_module
from .api.v2 import auth_router, users_router, characters_router, chats_router
from .memory_service import MemoryService, memory_service
from .schemas.memory import (
    UserFactCreate,
    UserFactUpdate,
    UserFactResponse,
    UserFactListResponse,
    MemoryUpdate,
    MemoryResponse,
    MemoryListResponse,
    MemorySearchRequest,
    RelationshipResponse,
    RelationshipUpdate,
    MemoryContextResponse,
    DiaryEntryResponse,
    DiaryListResponse,
)


# Configuration
CORE_URL = os.getenv("COGNITIA_CORE_URL", "http://10.0.0.15:8080")
CORE_WS_URL = CORE_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    await init_db()
    logger.info("Cognitia Entrance started")
    yield
    logger.info("Cognitia Entrance shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Cognitia Entrance",
        description="Authentication proxy for Cognitia AI assistant",
        version="3.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Subscription middleware for rate limiting
    app.add_middleware(SubscriptionMiddleware)

    # Include subscription router
    app.include_router(subscription_module.router)

    # Include API v2 routers
    app.include_router(auth_router, prefix="/api/v2")
    app.include_router(users_router, prefix="/api/v2")
    app.include_router(characters_router, prefix="/api/v2")
    app.include_router(chats_router, prefix="/api/v2")

    logger.info("✓ Subscription system enabled")
    logger.info("✓ API v2 endpoints enabled")

    return app


app = create_app()


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["health"])
@app.get("/api/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint."""
    core_available = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{CORE_URL}/health")
            core_available = response.status_code == 200
    except Exception:
        pass
    
    return HealthResponse(core_available=core_available)


# =============================================================================
# Authentication Routes
# =============================================================================

@app.post("/api/auth/register", response_model=TokenResponse, tags=["auth"])
async def register(
    data: UserCreate,
    session: AsyncSession = Depends(get_session_dep),
):
    """Register a new user."""
    # Check if email exists
    result = await session.execute(
        select(User).where(User.email == data.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Create user
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
    )
    session.add(user)
    await session.flush()
    
    # Generate tokens
    access_token = create_access_token(user.id, user.email)
    refresh_token = create_refresh_token(user.id, user.email)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@app.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(
    data: UserLogin,
    session: AsyncSession = Depends(get_session_dep),
):
    """Login and get tokens."""
    result = await session.execute(
        select(User).where(User.email == data.email)
    )
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    access_token = create_access_token(user.id, user.email)
    refresh_token = create_refresh_token(user.id, user.email)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@app.post("/api/auth/refresh", response_model=TokenResponse, tags=["auth"])
async def refresh_token(
    data: TokenRefresh,
    session: AsyncSession = Depends(get_session_dep),
):
    """Refresh access token using refresh token."""
    payload = decode_token(data.refresh_token)
    
    if payload is None or payload.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    
    # Verify user still exists
    result = await session.execute(
        select(User).where(User.id == UUID(payload.sub))
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    access_token = create_access_token(user.id, user.email)
    refresh_token = create_refresh_token(user.id, user.email)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@app.get("/api/auth/me", response_model=UserResponse, tags=["auth"])
async def get_me(
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Get current user info."""
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return UserResponse.model_validate(user)


@app.post("/api/auth/logout", tags=["auth"])
async def logout(
    user_id: UUID = Depends(get_user_id),
):
    """Logout current user (invalidate token client-side)."""
    # JWT tokens are stateless - client should discard the token
    # In a production system, you might want to blacklist the token
    return {"message": "Successfully logged out"}


@app.post("/api/auth/me/avatar", response_model=UserResponse, tags=["auth"])
async def upload_user_avatar(
    avatar_file: UploadFile = File(...),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """
    Upload an avatar image for the current user.
    
    Accepts image files (JPG, PNG, GIF, WebP) up to 2MB.
    """
    # Get user
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Validate file type
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    file_ext = Path(avatar_file.filename).suffix.lower() if avatar_file.filename else ''
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}",
        )
    
    # Validate file size (2MB max)
    content = await avatar_file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 2MB.",
        )
    
    # Save avatar
    docker_path = Path("/app/web/avatars")
    local_path = Path(__file__).parent.parent.parent.parent / "web" / "avatars"
    avatars_dir = docker_path if docker_path.parent.exists() else local_path
    avatars_dir.mkdir(parents=True, exist_ok=True)
    
    avatar_filename = f"user_{user_id}{file_ext}"
    avatar_path = avatars_dir / avatar_filename
    
    with open(avatar_path, "wb") as f:
        f.write(content)
    
    # Update user
    user.avatar_url = f"/avatars/{avatar_filename}"
    await session.commit()
    await session.refresh(user)
    
    logger.info(f"Updated user {user_id} avatar: {avatar_filename}")
    return UserResponse.model_validate(user)


# =============================================================================
# Character Routes
# =============================================================================

@app.get("/api/characters", response_model=CharacterListResponse, tags=["characters"])
@app.get("/api/characters/", response_model=CharacterListResponse, tags=["characters"], include_in_schema=False)
async def list_characters(
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """List all characters for the current user."""
    result = await session.execute(
        select(Character)
        .where(Character.user_id == user_id)
        .order_by(Character.created_at.desc())
    )
    characters = result.scalars().all()
    
    return CharacterListResponse(
        characters=[CharacterResponse.model_validate(c) for c in characters]
    )


@app.post("/api/characters", response_model=CharacterResponse, tags=["characters"])
@app.post("/api/characters/", response_model=CharacterResponse, tags=["characters"], include_in_schema=False)
async def create_character(
    data: CharacterCreate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Create a new character."""
    character = Character(
        user_id=user_id,
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        persona_prompt=data.persona_prompt,
        voice_model=data.voice_model,
        prompt_template=data.prompt_template,
        avatar_url=data.avatar_url,
    )
    session.add(character)
    await session.flush()
    await session.refresh(character)
    
    return CharacterResponse.model_validate(character)


@app.get("/api/characters/{character_id}", response_model=CharacterResponse, tags=["characters"])
async def get_character(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Get a character by ID."""
    result = await session.execute(
        select(Character)
        .where(Character.id == character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    return CharacterResponse.model_validate(character)


@app.put("/api/characters/{character_id}", response_model=CharacterResponse, tags=["characters"])
async def update_character(
    character_id: UUID,
    data: CharacterUpdate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Update a character."""
    result = await session.execute(
        select(Character)
        .where(Character.id == character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    # Update fields
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(character, field, value)
    
    await session.flush()
    await session.refresh(character)
    
    return CharacterResponse.model_validate(character)


@app.delete("/api/characters/{character_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["characters"])
async def delete_character(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a character."""
    result = await session.execute(
        select(Character)
        .where(Character.id == character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    await session.delete(character)


@app.post("/api/characters/{character_id}/voice-model", response_model=CharacterResponse, tags=["characters"])
async def upload_voice_model(
    character_id: UUID,
    pth_file: UploadFile = File(...),
    index_file: Optional[UploadFile] = File(None),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """
    Upload an RVC voice model for a character.
    
    Accepts .pth file (required) and .index file (optional) and forwards them
    to the Core server for storage. Updates the character's rvc_model_path.
    
    Args:
        character_id: The character to update
        pth_file: The .pth model file (required)
        index_file: The .index file for better quality (optional)
    
    Returns:
        Updated character information
    """
    # Verify character ownership
    result = await session.execute(
        select(Character)
        .where(Character.id == character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    # Validate file extensions
    if not pth_file.filename.endswith('.pth'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pth_file must have .pth extension",
        )
    
    if index_file and not index_file.filename.endswith('.index'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="index_file must have .index extension",
        )
    
    # Use original filename (without extension) as model name for better readability
    original_name = pth_file.filename.rsplit('.', 1)[0]  # Remove .pth extension
    # Sanitize: remove special chars, keep alphanumeric, underscore, hyphen
    model_name = "".join(c for c in original_name if c.isalnum() or c in ('_', '-')).strip()
    if not model_name:
        model_name = f"char_{character_id}"  # Fallback if name is empty after sanitizing
    
    try:
        # Read file contents
        pth_content = await pth_file.read()
        index_content = await index_file.read() if index_file else None
        
        # Forward to Core server
        async with httpx.AsyncClient(timeout=300.0) as client:  # 5 min timeout for large files
            files = {
                "pth_file": (pth_file.filename, pth_content, "application/octet-stream"),
            }
            if index_file and index_content:
                files["index_file"] = (index_file.filename, index_content, "application/octet-stream")
            
            response = await client.post(
                f"{CORE_URL}/upload-rvc-model",
                files=files,
                data={"model_name": model_name},
            )
            
            if response.status_code != 200:
                logger.error(f"Core server RVC upload failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to upload voice model to Core server: {response.text}",
                )
            
            upload_result = response.json()
            logger.info(f"RVC model uploaded to Core: {upload_result}")
        
        # Update character with model path
        character.rvc_model_path = model_name  # Just the model name, not full path
        if index_file:
            character.rvc_index_path = index_file.filename
        
        await session.commit()
        await session.refresh(character)
        
        logger.info(f"Updated character {character_id} with RVC model: {model_name}")
        return CharacterResponse.model_validate(character)
        
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Upload timed out - file may be too large",
        )
    except httpx.RequestError as e:
        logger.exception(f"Failed to connect to Core server: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to connect to Core server: {str(e)}",
        )


@app.put("/api/characters/{character_id}/rvc-model", response_model=CharacterResponse, tags=["characters"])
async def assign_rvc_model(
    character_id: UUID,
    rvc_model_path: str = Body(..., embed=True),
    rvc_index_path: Optional[str] = Body(None, embed=True),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """
    Assign an existing RVC model to a character.
    
    Args:
        character_id: The character to update
        rvc_model_path: Path to the RVC model (from /api/models/rvc)
        rvc_index_path: Optional index path
    
    Returns:
        Updated character information
    """
    # Verify character ownership
    result = await session.execute(
        select(Character)
        .where(Character.id == character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    # Extract model name from path (e.g., "rvc_models/name/file.pth" -> "name")
    # RVC service expects just the model name, not the full path
    model_name = rvc_model_path.split('/')[1] if '/' in rvc_model_path else rvc_model_path
    
    # Verify model exists on Core server
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{CORE_URL}/rvc-models")
            if response.status_code == 200:
                core_models = response.json()
                model_exists = any(m.get('name') == model_name for m in core_models)
                if not model_exists:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"RVC model '{model_name}' not found on Core server",
                    )
    except httpx.RequestError as e:
        logger.warning(f"Could not verify RVC model on Core: {e}")
        # Continue anyway - model might exist
    
    # Update character with just the model name (not the full path)
    character.rvc_model_path = model_name
    character.rvc_index_path = rvc_index_path
    
    await session.commit()
    await session.refresh(character)
    
    logger.info(f"Assigned RVC model {model_name} to character {character_id}")
    return CharacterResponse.model_validate(character)


@app.post("/api/characters/{character_id}/avatar", response_model=CharacterResponse, tags=["characters"])
async def upload_character_avatar(
    character_id: UUID,
    avatar_file: UploadFile = File(...),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """
    Upload an avatar image for a character.
    
    Accepts image files (JPG, PNG, GIF, WebP) and stores them.
    
    Args:
        character_id: The character to update
        avatar_file: The avatar image file
    
    Returns:
        Updated character information
    """
    # Verify character ownership
    result = await session.execute(
        select(Character)
        .where(Character.id == character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    # Validate file type
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    file_ext = Path(avatar_file.filename).suffix.lower() if avatar_file.filename else ''
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}",
        )
    
    # Validate file size (2MB max)
    content = await avatar_file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 2MB.",
        )
    
    # Save avatar to static directory - use /app/web in Docker, else local path
    docker_path = Path("/app/web/avatars")
    local_path = Path(__file__).parent.parent.parent.parent / "web" / "avatars"
    avatars_dir = docker_path if docker_path.parent.exists() else local_path
    avatars_dir.mkdir(parents=True, exist_ok=True)
    
    # Create unique filename
    avatar_filename = f"char_{character_id}{file_ext}"
    avatar_path = avatars_dir / avatar_filename
    
    # Write file
    with open(avatar_path, "wb") as f:
        f.write(content)
    
    # Update character with avatar URL
    character.avatar_url = f"/avatars/{avatar_filename}"
    
    await session.commit()
    await session.refresh(character)
    
    logger.info(f"Updated character {character_id} with avatar: {avatar_filename}")
    return CharacterResponse.model_validate(character)


# =============================================================================
# Chat Routes
# =============================================================================

@app.get("/api/chats", response_model=ChatListResponse, tags=["chats"])
@app.get("/api/chats/", response_model=ChatListResponse, tags=["chats"], include_in_schema=False)
async def list_chats(
    character_id: Optional[UUID] = None,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """List all chats for the current user, optionally filtered by character."""
    query = (
        select(Chat)
        .join(Character)
        .options(selectinload(Chat.character))
        .where(Character.user_id == user_id)
        .order_by(Chat.updated_at.desc())
    )
    
    if character_id:
        query = query.where(Chat.character_id == character_id)
    
    result = await session.execute(query)
    chats = result.scalars().all()
    
    # Build response with character avatar
    chat_responses = []
    for chat in chats:
        chat_data = ChatResponse.model_validate(chat)
        # Add character avatar URL to the response
        if chat.character:
            chat_data.character_avatar_url = chat.character.avatar_url
        chat_responses.append(chat_data)
    
    return ChatListResponse(chats=chat_responses)


@app.post("/api/chats", response_model=ChatResponse, tags=["chats"])
@app.post("/api/chats/", response_model=ChatResponse, tags=["chats"], include_in_schema=False)
async def create_chat(
    data: ChatCreate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Create a new chat."""
    # Verify character belongs to user
    result = await session.execute(
        select(Character)
        .where(Character.id == data.character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    chat = Chat(
        character_id=data.character_id,
        title=data.title or f"Chat with {character.name}",
    )
    session.add(chat)
    await session.flush()
    await session.refresh(chat)
    
    return ChatResponse.model_validate(chat)


@app.get("/api/chats/{chat_id}", response_model=ChatResponse, tags=["chats"])
async def get_chat(
    chat_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Get a chat by ID."""
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    return ChatResponse.model_validate(chat)


@app.delete("/api/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["chats"])
async def delete_chat(
    chat_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a chat."""
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    await session.delete(chat)


# =============================================================================
# Message Routes
# =============================================================================

@app.get("/api/chats/{chat_id}/messages", response_model=MessageListResponse, tags=["messages"])
async def list_messages(
    chat_id: UUID,
    limit: int = 50,
    offset: int = 0,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """List messages in a chat."""
    # Verify chat belongs to user
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    # Get messages
    result = await session.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit + 1)  # Fetch one extra to check if there's more
    )
    messages = list(result.scalars().all())
    
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]
    
    # Return in chronological order
    messages.reverse()
    
    return MessageListResponse(
        messages=[MessageResponse.model_validate(m) for m in messages],
        has_more=has_more,
    )


@app.post("/api/chats/{chat_id}/messages", response_model=MessageResponse, tags=["messages"])
async def create_message(
    chat_id: UUID,
    data: MessageCreate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Create a message in a chat."""
    # Verify chat belongs to user
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )

    # Handle audio data - save base64 data URIs to files
    audio_url = data.audio_url
    if audio_url and audio_url.startswith('data:audio/'):
        try:
            # Parse data URI: data:audio/wav;base64,<data>
            header, base64_data = audio_url.split(',', 1)
            mime_match = header.split(';')[0].split(':')[1] if ':' in header else 'audio/wav'
            extension = mime_match.split('/')[-1]  # wav, mp3, etc.
            
            # Create audio directory
            docker_path = Path("/app/web/audio")
            local_path = Path(__file__).parent.parent.parent.parent / "web" / "audio"
            audio_dir = docker_path if docker_path.parent.exists() else local_path
            audio_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            import base64
            audio_filename = f"{chat_id}_{uuid4()}.{extension}"
            audio_path = audio_dir / audio_filename
            
            # Decode and save
            audio_bytes = base64.b64decode(base64_data)
            audio_path.write_bytes(audio_bytes)
            
            # Store URL reference instead of data
            audio_url = f"/audio/{audio_filename}"
            logger.debug(f"Saved audio to {audio_path}, URL: {audio_url}")
        except Exception as e:
            logger.error(f"Failed to save audio data: {e}")
            audio_url = None  # Don't fail the request, just skip audio

    message = Message(
        chat_id=chat_id,
        role=data.role,
        content=data.content,
        audio_url=audio_url,
    )
    session.add(message)
    await session.flush()
    await session.refresh(message)

    # Track usage (fire and forget - don't block response)
    asyncio.create_task(
        usage_tracker.record_message(
            user_id=user_id,
            chat_id=chat_id,
            character_id=chat.character_id,
            tokens=0  # TODO: Track actual tokens when LLM integration is added
        )
    )

    # Trigger memory extraction for assistant messages (fire and forget)
    if data.role == "assistant" and chat.character_id:
        asyncio.create_task(
            _extract_memories_for_exchange(
                user_id=user_id,
                character_id=chat.character_id,
                chat_id=chat_id,
            )
        )

    return MessageResponse.model_validate(message)


@app.delete("/api/chats/{chat_id}/messages/{message_id}", tags=["messages"])
async def delete_message(
    chat_id: UUID,
    message_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a single message from a chat."""
    # Verify chat belongs to user
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )

    # Verify message exists and belongs to this chat
    result = await session.execute(
        select(Message).where(
            Message.id == message_id,
            Message.chat_id == chat_id,
        )
    )
    message = result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    await session.delete(message)
    await session.commit()

    return {"success": True, "deleted_count": 1}


@app.delete("/api/chats/{chat_id}/messages/{message_id}/and-after", tags=["messages"])
async def delete_message_and_after(
    chat_id: UUID,
    message_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a message and all messages after it in a chat."""
    # Verify chat belongs to user
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()

    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )

    # Get the target message to find its timestamp
    result = await session.execute(
        select(Message).where(
            Message.id == message_id,
            Message.chat_id == chat_id,
        )
    )
    target_message = result.scalar_one_or_none()

    if not target_message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    # Delete all messages with created_at >= target message's created_at
    delete_stmt = delete(Message).where(
        and_(
            Message.chat_id == chat_id,
            Message.created_at >= target_message.created_at,
        )
    )
    result = await session.execute(delete_stmt)
    deleted_count = result.rowcount
    await session.commit()

    return {"success": True, "deleted_count": deleted_count}


@app.get("/api/v2/chats/{chat_id}/messages", response_model=CursorPaginatedMessages, tags=["messages"])
async def list_messages_v2(
    chat_id: UUID,
    limit: int = Query(default=50, ge=1, le=100, description="Number of messages to fetch"),
    cursor: Optional[str] = Query(default=None, description="Cursor for pagination (base64 encoded message ID)"),
    direction: str = Query(default="older", pattern="^(older|newer)$", description="Direction to paginate"),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """
    List messages in a chat with cursor-based pagination.
    
    Cursor-based pagination is more efficient for real-time chat applications
    and handles message insertions/deletions better than offset pagination.
    
    Args:
        chat_id: The chat ID
        limit: Number of messages to return (1-100)
        cursor: Base64-encoded message ID to start from
        direction: 'older' fetches messages before cursor, 'newer' fetches after
    
    Returns:
        Messages with next/prev cursors for continued pagination
    """
    # Verify chat belongs to user
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    # Decode cursor if provided
    cursor_message_id: Optional[UUID] = None
    cursor_timestamp: Optional[datetime] = None
    if cursor:
        try:
            decoded = base64.b64decode(cursor).decode('utf-8')
            cursor_message_id = UUID(decoded)
            # Get the timestamp of the cursor message
            cursor_result = await session.execute(
                select(Message.created_at).where(Message.id == cursor_message_id)
            )
            cursor_timestamp = cursor_result.scalar_one_or_none()
        except (ValueError, Exception):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid cursor format",
            )
    
    # Build query
    query = select(Message).where(Message.chat_id == chat_id)
    
    if cursor_timestamp:
        if direction == "older":
            # Get messages older than cursor
            query = query.where(Message.created_at < cursor_timestamp)
            query = query.order_by(Message.created_at.desc())
        else:
            # Get messages newer than cursor
            query = query.where(Message.created_at > cursor_timestamp)
            query = query.order_by(Message.created_at.asc())
    else:
        # No cursor - get latest messages
        query = query.order_by(Message.created_at.desc())
    
    # Fetch limit + 1 to check if there are more
    query = query.limit(limit + 1)
    result = await session.execute(query)
    messages = list(result.scalars().all())
    
    # Check if there are more messages
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]
    
    # For "newer" direction, we need to reverse to maintain chronological order
    if direction == "newer":
        messages.reverse()
    else:
        # For "older", reverse to get chronological order
        messages.reverse()
    
    # Get total count for reference
    count_result = await session.execute(
        select(Message.id).where(Message.chat_id == chat_id)
    )
    total_count = len(count_result.all())
    
    # Build cursors
    next_cursor = None
    prev_cursor = None
    
    if messages:
        # Next cursor points to the oldest message (for fetching more older messages)
        oldest_msg = messages[0]
        next_cursor = base64.b64encode(str(oldest_msg.id).encode()).decode() if has_more or cursor else None
        
        # Prev cursor points to the newest message (for fetching newer messages)
        newest_msg = messages[-1]
        # Only provide prev_cursor if we have a cursor (i.e., we're paginating)
        if cursor:
            prev_cursor = base64.b64encode(str(newest_msg.id).encode()).decode()
    
    return CursorPaginatedMessages(
        messages=[MessageResponse.model_validate(m) for m in messages],
        next_cursor=next_cursor if direction == "older" else prev_cursor,
        prev_cursor=prev_cursor if direction == "older" else next_cursor,
        has_more=has_more,
        total_count=total_count,
    )


# =============================================================================
# Model & Voice Endpoints
# =============================================================================

@app.get("/api/models/voices", response_model=VoiceModelListResponse, tags=["models"])
async def list_voice_models(
    user_id: UUID = Depends(get_user_id),
):
    """
    List available TTS voice models.
    
    These are the built-in Kokoro TTS voices available for characters.
    """
    # Built-in Kokoro voices
    voices = [
        VoiceModelInfo(id="af_bella", name="Bella", description="American female, warm and friendly", language="en", type="tts"),
        VoiceModelInfo(id="af_nicole", name="Nicole", description="American female, professional", language="en", type="tts"),
        VoiceModelInfo(id="af_sarah", name="Sarah", description="American female, casual", language="en", type="tts"),
        VoiceModelInfo(id="af_sky", name="Sky", description="American female, youthful", language="en", type="tts"),
        VoiceModelInfo(id="am_adam", name="Adam", description="American male, authoritative", language="en", type="tts"),
        VoiceModelInfo(id="am_michael", name="Michael", description="American male, friendly", language="en", type="tts"),
        VoiceModelInfo(id="bf_emma", name="Emma", description="British female, elegant", language="en", type="tts"),
        VoiceModelInfo(id="bf_isabella", name="Isabella", description="British female, refined", language="en", type="tts"),
        VoiceModelInfo(id="bm_george", name="George", description="British male, distinguished", language="en", type="tts"),
        VoiceModelInfo(id="bm_lewis", name="Lewis", description="British male, articulate", language="en", type="tts"),
    ]
    return VoiceModelListResponse(models=voices)


@app.get("/api/models/rvc", response_model=RVCModelListResponse, tags=["models"])
async def list_rvc_models(
    user_id: UUID = Depends(get_user_id),
):
    """
    List available RVC voice conversion models.
    
    These are custom voice models that can be applied on top of TTS output.
    Fetches from the Core GPU server where RVC models are stored.
    """
    models = []
    
    # Fetch RVC models from Core server (GPU machine has the models)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{CORE_URL}/rvc-models")
            if response.status_code == 200:
                core_models = response.json()
                for model in core_models:
                    # Build full path for the Core server
                    model_name = model.get("name", "")
                    pth_file = model.get("pth_file", "")
                    index_file = model.get("index_file")
                    
                    if model_name and pth_file:
                        models.append(RVCModelInfo(
                            name=model_name,
                            model_path=f"rvc_models/{model_name}/{pth_file}",
                            index_path=f"rvc_models/{model_name}/{index_file}" if index_file else None,
                            description=f"RVC model: {model_name}",
                        ))
    except Exception as e:
        logger.warning(f"Failed to fetch RVC models from Core: {e}")
    
    return RVCModelListResponse(models=models)


@app.get("/api/core/status", response_model=CoreStatusResponse, tags=["core"])
async def get_core_status(
    user_id: UUID = Depends(get_user_id),
):
    """
    Get the status of the Core GPU server.
    
    Returns availability, version, and loaded model information.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{CORE_URL}/health")
            if response.status_code == 200:
                data = response.json()
                return CoreStatusResponse(
                    available=True,
                    version=data.get("version"),
                    models_loaded=data.get("models"),
                    gpu_info=data.get("gpu"),
                )
    except Exception as e:
        logger.warning(f"Failed to get Core status: {e}")
    
    return CoreStatusResponse(available=False)


@app.post("/api/core/reload-model", tags=["core"])
async def reload_core_model(
    model_type: str = Query(..., pattern="^(asr|tts|llm|rvc)$", description="Type of model to reload"),
    user_id: UUID = Depends(get_user_id),
):
    """
    Request the Core server to reload a specific model.
    
    Useful after updating model files or changing configuration.
    
    Args:
        model_type: Type of model to reload (asr, tts, llm, rvc)
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{CORE_URL}/api/models/reload",
                json={"model_type": model_type}
            )
            if response.status_code == 200:
                return {"message": f"Model {model_type} reload requested", "status": "success"}
            else:
                return {"message": f"Core server returned {response.status_code}", "status": "error"}
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to connect to Core server: {str(e)}",
        )


# =============================================================================
# Memory Extraction Helpers
# =============================================================================


async def _extract_memories_for_exchange(
    user_id: UUID,
    character_id: UUID,
    chat_id: UUID,
):
    """
    Extract memories from the last user+assistant exchange in a chat.

    Called as a background task after an assistant message is saved.
    """
    from .database import get_session

    try:
        async with get_session() as session:
            # Get the last 2 messages (user + assistant)
            result = await session.execute(
                select(Message)
                .where(Message.chat_id == chat_id)
                .order_by(Message.created_at.desc())
                .limit(2)
            )
            messages = list(result.scalars().all())

            if len(messages) < 2:
                return

            # Messages are in reverse order (newest first)
            messages.reverse()

            # Find user and assistant messages
            user_msg = None
            assistant_msg = None
            for m in messages:
                if m.role == "user":
                    user_msg = m.content
                elif m.role == "assistant":
                    assistant_msg = m.content

            if not user_msg or not assistant_msg:
                return

            # Extract memories
            result = await memory_service.extract_and_store_memories(
                session=session,
                user_id=user_id,
                character_id=character_id,
                chat_id=chat_id,
                user_message=user_msg,
                assistant_response=assistant_msg,
            )

            await session.commit()

            if result.get("facts_extracted", 0) > 0 or result.get("memory_created"):
                logger.info(
                    f"Memory extraction: {result['facts_extracted']} facts, "
                    f"memory_created={result['memory_created']}, "
                    f"trust_change={result['trust_change']}"
                )

    except Exception as e:
        logger.error(f"Memory extraction failed: {e}")


async def _extract_and_notify_memory(
    websocket: WebSocket,
    user_id: UUID,
    character_id: UUID,
    chat_id: Optional[UUID],
    user_message: str,
    assistant_response: str,
):
    """
    Extract memories and notify client via WebSocket.

    Called after WebSocket conversation turns complete.
    """
    from .database import get_session

    try:
        async with get_session() as session:
            # Extract memories
            result = await memory_service.extract_and_store_memories(
                session=session,
                user_id=user_id,
                character_id=character_id,
                chat_id=chat_id,
                user_message=user_message,
                assistant_response=assistant_response,
            )

            await session.commit()

            # Notify client if anything significant happened
            if (result.get("facts_extracted", 0) > 0
                or result.get("memory_created")
                or result.get("trust_change", 0) != 0
                or result.get("sentiment_change", 0) != 0):

                logger.info(
                    f"WebSocket memory extraction: {result['facts_extracted']} facts, "
                    f"memory_created={result['memory_created']}, "
                    f"trust_change={result.get('trust_change', 0)}, "
                    f"sentiment_change={result.get('sentiment_change', 0)}"
                )

                # Send memory_update message to client
                try:
                    await websocket.send_json({
                        "type": "memory_update",
                        "facts_extracted": result.get("facts_extracted", 0),
                        "memory_created": result.get("memory_created", False),
                        "trust_change": result.get("trust_change", 0),
                        "sentiment_change": result.get("sentiment_change", 0),
                        "emotional_tone": result.get("emotional_tone", "neutral"),
                    })
                except Exception as send_err:
                    logger.warning(f"Could not send memory_update to client: {send_err}")

            # Send separate notification for stage progression
            if result.get("new_stage"):
                try:
                    await websocket.send_json({
                        "type": "relationship_milestone",
                        "new_stage": result["new_stage"],
                        "message": f"Your relationship has evolved to: {result['new_stage']}!",
                    })
                except Exception as send_err:
                    logger.warning(f"Could not send relationship_milestone to client: {send_err}")

            # Send alert for significant sentiment changes
            sentiment_change = result.get("sentiment_change", 0)
            if abs(sentiment_change) >= 15:
                try:
                    sentiment_direction = "improved significantly" if sentiment_change > 0 else "declined noticeably"
                    await websocket.send_json({
                        "type": "sentiment_alert",
                        "sentiment_change": sentiment_change,
                        "message": f"The emotional dynamic has {sentiment_direction}.",
                    })
                except Exception as send_err:
                    logger.warning(f"Could not send sentiment_alert to client: {send_err}")

    except Exception as e:
        logger.error(f"WebSocket memory extraction failed: {e}", exc_info=True)


# =============================================================================
# Memory System Endpoints
# =============================================================================


@app.get("/api/memory/{character_id}/facts", response_model=UserFactListResponse, tags=["memory"])
async def get_user_facts(
    character_id: UUID,
    category: Optional[str] = Query(None, description="Filter by category"),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Get all facts the AI knows about the user for a specific character."""
    facts = await memory_service.get_user_facts(
        session, user_id, character_id, category=category
    )
    return UserFactListResponse(
        facts=[UserFactResponse.model_validate(f) for f in facts],
        total=len(facts)
    )


@app.post("/api/memory/{character_id}/facts", response_model=UserFactResponse, tags=["memory"])
async def create_user_fact(
    character_id: UUID,
    fact: UserFactCreate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Manually add a fact about the user."""
    new_fact = await memory_service._store_fact(
        session,
        user_id=user_id,
        character_id=character_id,
        category=fact.category,
        key=fact.key,
        value=fact.value,
        confidence=fact.confidence,
    )
    await session.commit()
    await session.refresh(new_fact)
    return UserFactResponse.model_validate(new_fact)


@app.delete("/api/memory/{character_id}/facts/{fact_key}", status_code=status.HTTP_204_NO_CONTENT, tags=["memory"])
async def delete_user_fact(
    character_id: UUID,
    fact_key: str,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a specific fact (user-initiated forget)."""
    from sqlalchemy import delete as sql_delete, and_
    stmt = sql_delete(UserFact).where(
        and_(
            UserFact.user_id == user_id,
            UserFact.character_id == character_id,
            UserFact.key == fact_key,
        )
    )
    await session.execute(stmt)
    await session.commit()


@app.get("/api/memory/{character_id}/memories", response_model=MemoryListResponse, tags=["memory"])
async def get_memories(
    character_id: UUID,
    memory_type: Optional[str] = Query(None, description="Filter by type: episodic, semantic, event"),
    limit: int = Query(20, ge=1, le=100),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Get episodic memories for a character."""
    memories = await memory_service.get_relevant_memories(
        session, user_id, character_id,
        memory_type=memory_type,
        limit=limit
    )
    return MemoryListResponse(
        memories=[MemoryResponse.model_validate(m) for m in memories],
        total=len(memories)
    )


@app.delete("/api/memory/{character_id}/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["memory"])
async def delete_memory(
    character_id: UUID,
    memory_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a specific memory."""
    deleted = await memory_service.delete_memory(session, memory_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    await session.commit()


@app.get("/api/memory/{character_id}/relationship", response_model=RelationshipResponse, tags=["memory"])
async def get_relationship(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Get relationship status with a character."""
    import traceback
    try:
        relationship = await memory_service.get_relationship_status(session, user_id, character_id)
        if not relationship:
            # Create initial relationship
            relationship = await memory_service.get_or_create_relationship(session, user_id, character_id)
            await session.commit()
        logger.info(f"Relationship data: stage={relationship.stage}, inside_jokes={relationship.inside_jokes}, milestones={relationship.milestones}")
        return RelationshipResponse.model_validate(relationship)
    except Exception as e:
        logger.error(f"Error in get_relationship: {e}")
        logger.error(traceback.format_exc())
        raise


@app.get("/api/memory/{character_id}/context", response_model=MemoryContextResponse, tags=["memory"])
async def get_memory_context(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """
    Get full memory context that would be injected into LLM prompts.
    
    Useful for debugging and understanding what the AI "knows".
    """
    # Get all components
    relationship = await memory_service.get_relationship_status(session, user_id, character_id)
    facts = await memory_service.get_user_facts(session, user_id, character_id)
    memories = await memory_service.get_relevant_memories(session, user_id, character_id, limit=5)
    context_string = await memory_service.build_memory_context(session, user_id, character_id)
    
    return MemoryContextResponse(
        relationship=RelationshipResponse.model_validate(relationship) if relationship else None,
        facts=[UserFactResponse.model_validate(f) for f in facts],
        recent_memories=[MemoryResponse.model_validate(m) for m in memories],
        context_string=context_string
    )


@app.get("/api/memory/{character_id}/diary", response_model=DiaryListResponse, tags=["memory"])
async def get_diary_entries(
    character_id: UUID,
    entry_type: Optional[str] = Query("daily", description="Entry type: daily, weekly, monthly"),
    limit: int = Query(30, ge=1, le=100),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Get diary entries summarizing past conversations."""
    from sqlalchemy import and_
    stmt = select(DiaryEntry).where(
        and_(
            DiaryEntry.user_id == user_id,
            DiaryEntry.character_id == character_id,
        )
    )
    if entry_type:
        stmt = stmt.where(DiaryEntry.entry_type == entry_type)
    stmt = stmt.order_by(DiaryEntry.entry_date.desc()).limit(limit)
    
    result = await session.execute(stmt)
    entries = list(result.scalars().all())
    
    return DiaryListResponse(
        entries=[DiaryEntryResponse.model_validate(e) for e in entries],
        total=len(entries)
    )


# =============================================================================
# Memory CRUD Endpoints (Update/Delete by ID)
# =============================================================================


@app.put("/api/memory/{character_id}/facts/{fact_id}", response_model=UserFactResponse, tags=["memory"])
async def update_user_fact(
    character_id: UUID,
    fact_id: UUID,
    update: UserFactUpdate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Update a specific user fact."""
    from sqlalchemy import and_
    stmt = select(UserFact).where(
        and_(
            UserFact.id == fact_id,
            UserFact.user_id == user_id,
            UserFact.character_id == character_id,
        )
    )
    result = await session.execute(stmt)
    fact = result.scalar_one_or_none()
    
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")
    
    # Update only provided fields
    if update.category is not None:
        fact.category = update.category
    if update.key is not None:
        fact.key = update.key
    if update.value is not None:
        fact.value = update.value
    if update.confidence is not None:
        fact.confidence = update.confidence
    
    fact.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(fact)
    
    return UserFactResponse.model_validate(fact)


@app.delete("/api/memory/{character_id}/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["memory"])
async def delete_user_fact_by_id(
    character_id: UUID,
    fact_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a specific fact by ID."""
    from sqlalchemy import delete as sql_delete, and_
    stmt = sql_delete(UserFact).where(
        and_(
            UserFact.id == fact_id,
            UserFact.user_id == user_id,
            UserFact.character_id == character_id,
        )
    )
    result = await session.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Fact not found")
    await session.commit()


@app.put("/api/memory/{character_id}/memories/{memory_id}", response_model=MemoryResponse, tags=["memory"])
async def update_memory(
    character_id: UUID,
    memory_id: UUID,
    update: MemoryUpdate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Update a specific memory."""
    from sqlalchemy import and_
    stmt = select(Memory).where(
        and_(
            Memory.id == memory_id,
            Memory.user_id == user_id,
            Memory.character_id == character_id,
        )
    )
    result = await session.execute(stmt)
    memory = result.scalar_one_or_none()
    
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    # Update only provided fields
    if update.content is not None:
        memory.content = update.content
    if update.summary is not None:
        memory.summary = update.summary
    if update.emotional_tone is not None:
        memory.emotional_tone = update.emotional_tone
    if update.importance is not None:
        memory.importance = update.importance
    
    memory.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(memory)
    
    return MemoryResponse.model_validate(memory)


@app.put("/api/memory/{character_id}/relationship", response_model=RelationshipResponse, tags=["memory"])
async def update_relationship(
    character_id: UUID,
    update: RelationshipUpdate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Update relationship status with a character."""
    from sqlalchemy import and_
    stmt = select(Relationship).where(
        and_(
            Relationship.user_id == user_id,
            Relationship.character_id == character_id,
        )
    )
    result = await session.execute(stmt)
    relationship = result.scalar_one_or_none()
    
    if not relationship:
        raise HTTPException(status_code=404, detail="Relationship not found")
    
    # Update only provided fields
    if update.stage is not None:
        valid_stages = ["stranger", "acquaintance", "friend", "close_friend", "confidant", "soulmate"]
        if update.stage not in valid_stages:
            raise HTTPException(status_code=400, detail=f"Invalid stage. Must be one of: {valid_stages}")
        relationship.stage = update.stage
    if update.trust_level is not None:
        relationship.trust_level = update.trust_level
    
    relationship.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(relationship)
    
    return RelationshipResponse.model_validate(relationship)


@app.delete("/api/memory/{character_id}/relationship/inside-jokes/{joke_index}", status_code=status.HTTP_204_NO_CONTENT, tags=["memory"])
async def delete_inside_joke(
    character_id: UUID,
    joke_index: int,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a specific inside joke by index."""
    from sqlalchemy import and_
    stmt = select(Relationship).where(
        and_(
            Relationship.user_id == user_id,
            Relationship.character_id == character_id,
        )
    )
    result = await session.execute(stmt)
    relationship = result.scalar_one_or_none()
    
    if not relationship:
        raise HTTPException(status_code=404, detail="Relationship not found")
    
    inside_jokes = relationship.inside_jokes or []
    if isinstance(inside_jokes, str):
        import json
        inside_jokes = json.loads(inside_jokes) if inside_jokes else []
    
    if joke_index < 0 or joke_index >= len(inside_jokes):
        raise HTTPException(status_code=404, detail="Inside joke not found")
    
    inside_jokes.pop(joke_index)
    relationship.inside_jokes = inside_jokes
    relationship.updated_at = datetime.utcnow()
    await session.commit()


@app.delete("/api/memory/{character_id}/relationship/milestones/{milestone_index}", status_code=status.HTTP_204_NO_CONTENT, tags=["memory"])
async def delete_milestone(
    character_id: UUID,
    milestone_index: int,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a specific milestone by index."""
    from sqlalchemy import and_
    stmt = select(Relationship).where(
        and_(
            Relationship.user_id == user_id,
            Relationship.character_id == character_id,
        )
    )
    result = await session.execute(stmt)
    relationship = result.scalar_one_or_none()
    
    if not relationship:
        raise HTTPException(status_code=404, detail="Relationship not found")
    
    milestones = relationship.milestones or []
    if isinstance(milestones, str):
        import json
        milestones = json.loads(milestones) if milestones else []
    
    if milestone_index < 0 or milestone_index >= len(milestones):
        raise HTTPException(status_code=404, detail="Milestone not found")
    
    milestones.pop(milestone_index)
    relationship.milestones = milestones
    relationship.updated_at = datetime.utcnow()
    await session.commit()


# =============================================================================
# WebSocket Proxy to Core
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time communication.
    
    Flow:
    1. Client sends auth message with JWT
    2. After auth, messages are proxied to Core
    3. Core responses are proxied back to client
    
    Client messages:
    {"type": "auth", "token": "jwt..."}
    {"type": "text", "chatId": "...", "message": "..."}
    {"type": "audio", "chatId": "...", "data": "base64..."}
    {"type": "character_switch", "characterId": "..."}
    
    Server messages:
    {"type": "auth_success", "userId": "..."}
    {"type": "text_chunk", "content": "..."}
    {"type": "text_complete", "content": "..."}
    {"type": "audio", "content": "base64...", "sample_rate": 24000}
    {"type": "error", "message": "..."}
    """
    await websocket.accept()
    logger.info("WebSocket client connected")
    
    # Authenticate
    try:
        logger.info("Waiting for auth message...")
        auth_msg = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=30.0
        )
        logger.info(f"Received auth message: {auth_msg.get('type')}")
        
        if auth_msg.get("type") != "auth":
            await websocket.send_json({
                "type": "error",
                "message": "First message must be auth"
            })
            await websocket.close()
            return
        
        token = auth_msg.get("token", "")
        logger.info(f"Token received: {token[:20]}..." if token else "Token empty")
        user_id = verify_token(token)
        logger.info(f"Token verification result: user_id={user_id}")
        
        if not user_id:
            logger.warning("Token verification failed")
            await websocket.send_json({
                "type": "error",
                "message": "Invalid token"
            })
            await websocket.close()
            return
        
        logger.info(f"WebSocket authenticated: {user_id}")
        await websocket.send_json({
            "type": "auth_success",
            "userId": user_id
        })
        
    except asyncio.TimeoutError:
        logger.warning("WebSocket auth timeout")
        await websocket.send_json({
            "type": "error",
            "message": "Auth timeout"
        })
        await websocket.close()
        return
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during auth")
        return
    except Exception as e:
        logger.error(f"WebSocket auth error: {type(e).__name__}: {e}")
        await websocket.close()
        return
    
    # State
    current_character: Optional[Character] = None
    conversation_history: list[dict] = []
    
    # Try to connect to Core
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(f"{CORE_URL}/health")
                core_available = response.status_code == 200
            except Exception:
                core_available = False
        
        if core_available:
            await websocket.send_json({
                "type": "status",
                "message": "Connected to AI core",
                "mode": "full"
            })
            await _proxy_to_core(websocket, user_id)
        else:
            await websocket.send_json({
                "type": "status",
                "message": "AI core not available. Text-only mode.",
                "mode": "text-only"
            })
            await _text_only_mode(websocket, user_id)
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


async def _proxy_to_core(websocket: WebSocket, user_id: str):
    """Proxy WebSocket communication to Core."""
    from .database import get_session, Character, Chat, Message

    # Shared state for memory extraction
    conversation_state = {
        "last_user_msg": None,
        "last_assistant_msg": None,
        "current_chat_id": None,
        "current_char_id": None,
    }

    try:
        logger.info(f"🔌 Attempting to connect to Core WebSocket: {CORE_WS_URL}")
        # Increase max_size to 50MB for large audio responses
        async with websockets.connect(CORE_WS_URL, max_size=50 * 1024 * 1024) as core_ws:
            logger.info("✅ Successfully connected to Core WebSocket")

            async def forward_to_core():
                """Forward client messages to Core."""
                logger.info("⬆️  forward_to_core() started")
                try:
                    while True:
                        msg = await websocket.receive_json()
                        msg_type = msg.get("type", "")

                        if msg_type == "ping":
                            await websocket.send_json({"type": "pong"})
                            continue

                        # Handle character_switch locally - do NOT forward to Core
                        if msg_type == "character_switch":
                            char_id = msg.get("characterId")
                            if char_id:
                                async with get_session() as session:
                                    result = await session.execute(
                                        select(Character).where(Character.id == UUID(char_id))
                                    )
                                    char = result.scalar_one_or_none()
                                    if char:
                                        await websocket.send_json({
                                            "type": "info",
                                            "message": f"Switched to {char.name}"
                                        })
                            continue  # Don't forward to Core

                        # Only forward text/audio messages to Core
                        if msg_type not in ("text", "audio", "phone"):
                            logger.warning(f"Ignoring unknown message type: {msg_type}")
                            continue

                        # Capture user message for memory extraction
                        user_message_text = msg.get("message") or msg.get("data", "")
                        char_id = msg.get("characterId")
                        chat_id = msg.get("chatId")

                        # Store in shared state for memory extraction
                        if user_message_text and char_id:
                            conversation_state["last_user_msg"] = user_message_text
                            conversation_state["current_chat_id"] = chat_id
                            conversation_state["current_char_id"] = char_id
                            logger.info(f"Captured user message for memory: {user_message_text[:50]}...")

                        # Enrich message with context
                        msg["user_id"] = user_id

                        # Get character info
                        
                        if char_id:
                            async with get_session() as session:
                                result = await session.execute(
                                    select(Character).where(Character.id == UUID(char_id))
                                )
                                char = result.scalar_one_or_none()
                                if char:
                                    msg["system_prompt"] = char.system_prompt
                                    msg["persona_prompt"] = char.persona_prompt
                                    msg["model_id"] = str(char.id)
                                    msg["model_name"] = char.name
                                    msg["voice"] = char.voice_model
                                    msg["prompt_template"] = char.prompt_template
                                    msg["rvc_model_path"] = char.rvc_model_path
                                    msg["rvc_enabled"] = char.rvc_model_path is not None
                        
                        # Get conversation history
                        if chat_id:
                            async with get_session() as session:
                                result = await session.execute(
                                    select(Message)
                                    .where(Message.chat_id == UUID(chat_id))
                                    .order_by(Message.created_at.desc())
                                    .limit(20)
                                )
                                messages = list(result.scalars().all())
                                messages.reverse()
                                msg["conversation_history"] = [
                                    {"role": m.role, "content": m.content}
                                    for m in messages
                                ]
                        
                        # Get memory context for system prompt enrichment
                        memory_context = ""
                        if char_id:
                            try:
                                async with get_session() as session:
                                    memory_context = await memory_service.build_memory_context(
                                        session,
                                        user_id=UUID(user_id),
                                        character_id=UUID(char_id),
                                        current_message=msg.get("message") or msg.get("data", ""),
                                    )
                            except Exception as e:
                                logger.warning(f"Failed to get memory context: {e}")
                        
                        # Map to Core format
                        core_msg = {
                            "type": "process",
                            "user_id": msg.get("user_id", user_id),
                            "model_id": msg.get("model_id", "default"),
                            "message": msg.get("message") or msg.get("data", ""),
                            "communication_type": msg_type if msg_type in ("text", "audio", "phone") else "text",
                            "system_prompt": msg.get("system_prompt", "You are a helpful AI assistant."),
                            "persona_prompt": msg.get("persona_prompt"),
                            "conversation_history": msg.get("conversation_history", []),
                            "model_name": msg.get("model_name", "Assistant"),
                            "voice": msg.get("voice", "af_bella"),
                            "prompt_template": msg.get("prompt_template", "pygmalion"),
                            "rvc_model_path": msg.get("rvc_model_path"),
                            "rvc_enabled": msg.get("rvc_enabled", False),
                            "memory_context": memory_context,  # New: memory context for prompt enrichment
                        }
                        
                        logger.info(f"Forwarding to Core: type={core_msg['type']}, message={core_msg['message'][:50] if core_msg['message'] else 'empty'}")
                        await core_ws.send(json.dumps(core_msg))
                        
                except WebSocketDisconnect:
                    pass
            
            async def forward_to_client():
                """Forward Core messages to client."""
                logger.info("⬇️  forward_to_client() started")
                try:
                    async for message in core_ws:
                        data = json.loads(message)
                        msg_type = data.get('type')
                        logger.info(f"Received from Core: type={msg_type}")

                        # Track conversation for memory extraction
                        if msg_type == 'user_transcription':
                            # For audio messages, update with transcribed text
                            transcribed_text = data.get('content')
                            if transcribed_text:
                                conversation_state["last_user_msg"] = transcribed_text
                                logger.info(f"Updated user message from transcription: {transcribed_text[:50]}...")

                        elif msg_type == 'text_complete':
                            assistant_response = data.get('content', '')
                            if assistant_response:
                                conversation_state["last_assistant_msg"] = assistant_response
                                logger.info(f"Captured assistant response: {assistant_response[:50]}...")

                            # Trigger memory extraction when we have both messages
                            user_msg = conversation_state.get("last_user_msg")
                            asst_msg = conversation_state.get("last_assistant_msg")
                            char_id = conversation_state.get("current_char_id")

                            if user_msg and asst_msg and char_id:
                                try:
                                    # Safely convert IDs to UUIDs
                                    chat_id_uuid = None
                                    if conversation_state.get("current_chat_id"):
                                        try:
                                            chat_id_uuid = UUID(conversation_state["current_chat_id"])
                                        except (ValueError, TypeError) as e:
                                            logger.warning(f"Invalid chat_id UUID: {conversation_state.get('current_chat_id')}: {e}")

                                    try:
                                        char_id_uuid = UUID(char_id)
                                    except (ValueError, TypeError) as e:
                                        logger.error(f"Invalid character_id UUID: {char_id}: {e}")
                                        raise

                                    try:
                                        user_id_uuid = UUID(user_id)
                                    except (ValueError, TypeError) as e:
                                        logger.error(f"Invalid user_id UUID: {user_id}: {e}")
                                        raise

                                    logger.info(
                                        f"🧠 Triggering memory extraction: "
                                        f"user='{user_msg[:30] if user_msg else ''}...', "
                                        f"assistant='{asst_msg[:30] if asst_msg else ''}...'"
                                    )

                                    # Fire-and-forget memory extraction task
                                    asyncio.create_task(
                                        _extract_and_notify_memory(
                                            websocket=websocket,
                                            user_id=user_id_uuid,
                                            character_id=char_id_uuid,
                                            chat_id=chat_id_uuid,
                                            user_message=user_msg,
                                            assistant_response=asst_msg,
                                        )
                                    )

                                    # Reset for next turn
                                    conversation_state["last_user_msg"] = None
                                    conversation_state["last_assistant_msg"] = None

                                except Exception as mem_err:
                                    logger.error(f"Failed to trigger memory extraction: {mem_err}")

                        # Forward message to client
                        await websocket.send_json(data)
                except Exception as e:
                    logger.error(f"Forward to client error: {e}", exc_info=True)

            logger.info("🚀 Starting forward_to_core() and forward_to_client() tasks...")
            try:
                await asyncio.gather(
                    forward_to_core(),
                    forward_to_client(),
                )
                logger.info("✅ Both forward tasks completed")
            except Exception as gather_err:
                logger.error(f"❌ Error in asyncio.gather(): {gather_err}", exc_info=True)
                raise
            
    except websockets.exceptions.WebSocketException as e:
        logger.error(f"Core WebSocket connection error: {type(e).__name__}: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Failed to connect to AI core: {e}"
            })
            await websocket.send_json({
                "type": "status",
                "message": "Falling back to text-only mode",
                "mode": "text-only"
            })
            await _text_only_mode(websocket, user_id)
        except Exception as fallback_err:
            logger.error(f"Failed to fallback to text-only mode: {fallback_err}")
    except Exception as e:
        logger.error(f"Core proxy error: {type(e).__name__}: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Core proxy error: {str(e)[:200]}"
            })
            await websocket.send_json({
                "type": "status",
                "message": "Falling back to text-only mode",
                "mode": "text-only"
            })
            await _text_only_mode(websocket, user_id)
        except Exception as fallback_err:
            logger.error(f"Failed to fallback to text-only mode: {fallback_err}")


async def _text_only_mode(websocket: WebSocket, user_id: str):
    """Handle text-only mode when Core is unavailable (direct Ollama fallback)."""
    from .database import get_session, Character, Message
    
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://10.0.0.15:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "hf.co/TheBloke/Mythalion-13B-GGUF:Q4_K_M")
    
    current_system_prompt = "You are a helpful AI assistant."
    conversation_history: list[dict] = []
    
    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")
            
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            
            if msg_type == "character_switch":
                char_id = msg.get("characterId")
                if char_id:
                    async with get_session() as session:
                        result = await session.execute(
                            select(Character).where(Character.id == UUID(char_id))
                        )
                        char = result.scalar_one_or_none()
                        if char:
                            current_system_prompt = char.system_prompt
                            conversation_history = []
                            await websocket.send_json({
                                "type": "info",
                                "message": f"Switched to {char.name}"
                            })
            
            elif msg_type == "text":
                user_message = msg.get("message", "").strip()
                if not user_message:
                    continue
                
                conversation_history.append({"role": "user", "content": user_message})
                if len(conversation_history) > 20:
                    conversation_history = conversation_history[-20:]
                
                # Stream from Ollama
                full_response = ""
                try:
                    async for chunk in _stream_ollama(
                        conversation_history,
                        current_system_prompt,
                        OLLAMA_URL,
                        OLLAMA_MODEL,
                    ):
                        full_response += chunk
                        await websocket.send_json({
                            "type": "text_chunk",
                            "content": chunk
                        })
                    
                    await websocket.send_json({
                        "type": "text_complete",
                        "content": full_response
                    })
                    
                    conversation_history.append({
                        "role": "assistant",
                        "content": full_response
                    })
                    
                except Exception as e:
                    logger.error(f"LLM error: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"LLM error: {e}"
                    })
            
            elif msg_type == "audio":
                await websocket.send_json({
                    "type": "info",
                    "message": "Voice not available in text-only mode"
                })
            
    except WebSocketDisconnect:
        logger.info(f"Text-only mode disconnected: {user_id}")


async def _stream_ollama(
    messages: list[dict],
    system_prompt: str,
    ollama_url: str,
    ollama_model: str,
):
    """Stream response from Ollama."""
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    
    payload = {
        "model": ollama_model,
        "messages": full_messages,
        "stream": True,
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{ollama_url}/api/chat",
            json=payload,
        ) as response:
            async for line in response.aiter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue


# =============================================================================
# Static Files (Web UI)
# =============================================================================

# Favicon
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


# Mount static files (must be last)
def _mount_static():
    """Mount static files directory."""
    # Try Docker path first, then local
    for web_dir in [Path("/app/web"), Path(__file__).parent.parent.parent.parent / "web"]:
        if web_dir.exists():
            app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")
            logger.info(f"Serving static files from {web_dir}")
            return
    logger.warning("No static files directory found")


_mount_static()


# =============================================================================
# CLI Entry Point
# =============================================================================

def run(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
):
    """Run the entrance server."""
    import uvicorn
    
    host = os.getenv("ENTRANCE_HOST", host)
    port = int(os.getenv("ENTRANCE_PORT", port))
    
    logger.info(f"Starting Cognitia Entrance on {host}:{port}")
    uvicorn.run(
        "cognitia.entrance.server:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    run()
