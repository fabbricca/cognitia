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
from sqlalchemy import select, func
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
    
    # Create model name from character ID (ensures uniqueness)
    model_name = f"char_{character_id}"
    
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

    message = Message(
        chat_id=chat_id,
        role=data.role,
        content=data.content,
        audio_url=data.audio_url,
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

    return MessageResponse.model_validate(message)


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
    """
    models = []
    
    # Check RVC models directory
    rvc_paths = [
        Path("/app/rvc_models"),  # Docker
        Path(__file__).parent.parent.parent.parent / "rvc_models",  # Local
    ]
    
    for rvc_dir in rvc_paths:
        if rvc_dir.exists():
            for model_dir in rvc_dir.iterdir():
                if model_dir.is_dir():
                    pth_files = list(model_dir.glob("*.pth"))
                    index_files = list(model_dir.glob("*.index"))
                    
                    if pth_files:
                        models.append(RVCModelInfo(
                            name=model_dir.name,
                            model_path=str(pth_files[0]),
                            index_path=str(index_files[0]) if index_files else None,
                            description=f"RVC model: {model_dir.name}",
                        ))
            break  # Only use first existing path
    
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
    
    try:
        # Increase max_size to 50MB for large audio responses
        async with websockets.connect(CORE_WS_URL, max_size=50 * 1024 * 1024) as core_ws:
            async def forward_to_core():
                """Forward client messages to Core."""
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
                        
                        # Enrich message with context
                        msg["user_id"] = user_id
                        
                        # Get character info
                        char_id = msg.get("characterId")
                        chat_id = msg.get("chatId")
                        
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
                        }
                        
                        logger.info(f"Forwarding to Core: type={core_msg['type']}, message={core_msg['message'][:50] if core_msg['message'] else 'empty'}")
                        await core_ws.send(json.dumps(core_msg))
                        
                except WebSocketDisconnect:
                    pass
            
            async def forward_to_client():
                """Forward Core messages to client."""
                try:
                    async for message in core_ws:
                        data = json.loads(message)
                        logger.info(f"Received from Core: type={data.get('type')}")
                        await websocket.send_json(data)
                except Exception as e:
                    logger.error(f"Forward to client error: {e}")
            
            await asyncio.gather(
                forward_to_core(),
                forward_to_client(),
            )
            
    except Exception as e:
        logger.error(f"Core proxy error: {e}")
        await websocket.send_json({
            "type": "status",
            "message": f"Lost connection to AI core: {e}",
            "mode": "text-only"
        })
        await _text_only_mode(websocket, user_id)


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
