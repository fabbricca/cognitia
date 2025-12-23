"""Character router: CRUD operations for AI characters."""

import os
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_user_id
from .cache import cache
from .database import Character, get_session
from .schemas import (
    CharacterCreate,
    CharacterListResponse,
    CharacterResponse,
    CharacterUpdate,
)

router = APIRouter(prefix="/characters", tags=["characters"])

# Directory for uploaded RVC models
RVC_UPLOAD_DIR = Path(os.getenv("RVC_UPLOAD_DIR", "./data/rvc"))
RVC_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

AVATAR_UPLOAD_DIR = Path(os.getenv("AVATAR_UPLOAD_DIR", "./web/avatars"))
AVATAR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/", response_model=CharacterListResponse)
async def list_characters(
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """List all characters for the current user."""
    result = await session.execute(
        select(Character).where(Character.user_id == user_id).order_by(Character.created_at)
    )
    characters = result.scalars().all()
    
    return CharacterListResponse(
        characters=[CharacterResponse.model_validate(c) for c in characters]
    )


@router.post("/", response_model=CharacterResponse, status_code=status.HTTP_201_CREATED)
async def create_character(
    data: CharacterCreate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Create a new character."""
    character = Character(
        user_id=user_id,
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        voice_model=data.voice_model,
        avatar_url=data.avatar_url,
    )
    session.add(character)
    await session.commit()
    await session.refresh(character)
    
    return CharacterResponse.model_validate(character)


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Get a specific character with caching for system prompt."""
    # Try to get from cache first
    cached = await cache.get_character(str(character_id))
    if cached:
        # Verify ownership
        if cached.get("user_id") == str(user_id):
            return CharacterResponse(**cached)
    
    # Fetch from database
    result = await session.execute(
        select(Character).where(
            Character.id == character_id,
            Character.user_id == user_id,
        )
    )
    character = result.scalar_one_or_none()
    
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    response = CharacterResponse.model_validate(character)
    
    # Cache the character data
    await cache.set_character(str(character_id), response.model_dump(mode="json"))
    
    return response


@router.put("/{character_id}", response_model=CharacterResponse)
async def update_character(
    character_id: UUID,
    data: CharacterUpdate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Update a character."""
    result = await session.execute(
        select(Character).where(
            Character.id == character_id,
            Character.user_id == user_id,
        )
    )
    character = result.scalar_one_or_none()
    
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(character, field, value)
    
    await session.commit()
    await session.refresh(character)
    
    response = CharacterResponse.model_validate(character)
    
    # Update cache with new data
    await cache.set_character(str(character_id), response.model_dump(mode="json"))
    
    return response


@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_character(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Delete a character and its RVC models."""
    result = await session.execute(
        select(Character).where(
            Character.id == character_id,
            Character.user_id == user_id,
        )
    )
    character = result.scalar_one_or_none()
    
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    # Delete RVC model files if they exist
    if character.rvc_model_path:
        model_path = Path(character.rvc_model_path)
        if model_path.exists():
            model_path.unlink()
    
    if character.rvc_index_path:
        index_path = Path(character.rvc_index_path)
        if index_path.exists():
            index_path.unlink()
    
    await session.delete(character)
    await session.commit()
    
    # Invalidate cache
    await cache.invalidate_character(str(character_id))


@router.post("/{character_id}/voice", response_model=CharacterResponse)
async def upload_voice_model(
    character_id: UUID,
    model_file: UploadFile = File(..., description="RVC .pth model file"),
    index_file: UploadFile = File(None, description="RVC .index file (optional)"),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Upload RVC voice model files for a character."""
    result = await session.execute(
        select(Character).where(
            Character.id == character_id,
            Character.user_id == user_id,
        )
    )
    character = result.scalar_one_or_none()
    
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    # Validate model file
    if not model_file.filename.endswith(".pth"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Model file must be a .pth file",
        )
    
    # Create user-specific directory
    user_dir = RVC_UPLOAD_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    
    # Delete old files if they exist
    if character.rvc_model_path:
        old_model = Path(character.rvc_model_path)
        if old_model.exists():
            old_model.unlink()
    
    if character.rvc_index_path:
        old_index = Path(character.rvc_index_path)
        if old_index.exists():
            old_index.unlink()
    
    # Save model file
    model_path = user_dir / f"{character_id}.pth"
    with open(model_path, "wb") as f:
        shutil.copyfileobj(model_file.file, f)
    
    character.rvc_model_path = str(model_path)
    
    # Save index file if provided
    if index_file and index_file.filename:
        if not index_file.filename.endswith(".index"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Index file must be a .index file",
            )
        
        index_path = user_dir / f"{character_id}.index"
        with open(index_path, "wb") as f:
            shutil.copyfileobj(index_file.file, f)
        
        character.rvc_index_path = str(index_path)
    
    await session.commit()
    await session.refresh(character)
    
    return CharacterResponse.model_validate(character)


@router.post("/{character_id}/voice-model", response_model=CharacterResponse)
async def upload_voice_model_compat(
    character_id: UUID,
    pth_file: UploadFile = File(..., description="RVC .pth model file"),
    index_file: UploadFile = File(None, description="RVC .index file (optional)"),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Compatibility endpoint for the web UI (/voice-model + pth_file/index_file field names)."""
    return await upload_voice_model(
        character_id=character_id,
        model_file=pth_file,
        index_file=index_file,
        user_id=user_id,
        session=session,
    )


@router.put("/{character_id}/rvc-model", response_model=CharacterResponse)
async def assign_rvc_model(
    character_id: UUID,
    payload: dict,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Assign an existing RVC model path to a character."""
    result = await session.execute(
        select(Character).where(
            Character.id == character_id,
            Character.user_id == user_id,
        )
    )
    character = result.scalar_one_or_none()
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    character.rvc_model_path = payload.get("rvc_model_path")
    character.rvc_index_path = payload.get("rvc_index_path")
    await session.commit()
    await session.refresh(character)
    await cache.set_character(str(character_id), CharacterResponse.model_validate(character).model_dump(mode="json"))
    return CharacterResponse.model_validate(character)


@router.post("/{character_id}/avatar", response_model=CharacterResponse)
async def upload_character_avatar(
    character_id: UUID,
    avatar_file: UploadFile = File(..., description="Avatar image"),
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Upload a character avatar image (web UI compatibility)."""
    result = await session.execute(
        select(Character).where(
            Character.id == character_id,
            Character.user_id == user_id,
        )
    )
    character = result.scalar_one_or_none()
    if character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    ext = Path(avatar_file.filename or "avatar").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported image type")

    filename = f"{character_id}{ext}"
    target = AVATAR_UPLOAD_DIR / filename

    with open(target, "wb") as f:
        shutil.copyfileobj(avatar_file.file, f)

    character.avatar_url = f"/avatars/{filename}"
    await session.commit()
    await session.refresh(character)
    await cache.set_character(str(character_id), CharacterResponse.model_validate(character).model_dump(mode="json"))
    return CharacterResponse.model_validate(character)
