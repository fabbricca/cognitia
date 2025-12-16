"""Message repository for chat messages."""

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import select, and_

from .base import BaseRepository
from ..database import Message


class MessageRepository(BaseRepository[Message]):
    """Repository for Message operations."""

    async def get_chat_messages(
        self,
        chat_id: UUID,
        limit: int = 50,
        before: Optional[datetime] = None,
        after: Optional[datetime] = None
    ) -> List[Message]:
        """Get messages for a chat with optional time filtering."""
        query = select(Message).where(Message.chat_id == chat_id)

        if before:
            query = query.where(Message.created_at < before)
        if after:
            query = query.where(Message.created_at > after)

        query = query.order_by(Message.created_at.desc()).limit(limit)
        result = await self.session.execute(query)
        messages = list(result.scalars().all())

        # Return in chronological order
        return list(reversed(messages))

    async def get_user_messages(
        self,
        user_id: UUID,
        limit: int = 100
    ) -> List[Message]:
        """Get all messages sent by a user."""
        query = (
            select(Message)
            .where(Message.sender_id == user_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_character_messages(
        self,
        character_id: UUID,
        limit: int = 100
    ) -> List[Message]:
        """Get all messages from a character."""
        query = (
            select(Message)
            .where(Message.character_id == character_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_chat_messages(self, chat_id: UUID) -> int:
        """Count total messages in a chat."""
        from sqlalchemy import func
        result = await self.session.execute(
            select(func.count(Message.id)).where(Message.chat_id == chat_id)
        )
        return result.scalar_one()

    async def delete_chat_messages(self, chat_id: UUID) -> int:
        """Delete all messages in a chat. Returns count deleted."""
        from sqlalchemy import delete
        result = await self.session.execute(
            delete(Message).where(Message.chat_id == chat_id)
        )
        return result.rowcount
