"""Chat repository with group chat support."""

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload

from .base import BaseRepository
from ..database import Chat, ChatParticipant, ChatCharacter, User, Character


class ChatRepository(BaseRepository[Chat]):
    """Repository for Chat operations with group support."""

    async def get_user_chats(
        self,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0
    ) -> List[Chat]:
        """Get all chats where user is a participant."""
        # Join with chat_participants to filter
        query = (
            select(Chat)
            .join(ChatParticipant, ChatParticipant.chat_id == Chat.id)
            .where(ChatParticipant.user_id == user_id)
            .order_by(Chat.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def is_participant(self, chat_id: UUID, user_id: UUID) -> bool:
        """Check if user is a participant in chat."""
        result = await self.session.execute(
            select(ChatParticipant).where(
                and_(
                    ChatParticipant.chat_id == chat_id,
                    ChatParticipant.user_id == user_id
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def add_participant(
        self,
        chat_id: UUID,
        user_id: UUID,
        role: str = "member"  # Parameter kept for API compatibility but not stored
    ) -> ChatParticipant:
        """Add participant to chat."""
        participant = ChatParticipant(
            chat_id=chat_id,
            user_id=user_id
        )
        self.session.add(participant)
        await self.session.flush()
        await self.session.refresh(participant)
        return participant

    async def remove_participant(
        self,
        chat_id: UUID,
        user_id: UUID
    ) -> bool:
        """Remove participant from chat."""
        result = await self.session.execute(
            select(ChatParticipant).where(
                and_(
                    ChatParticipant.chat_id == chat_id,
                    ChatParticipant.user_id == user_id
                )
            )
        )
        participant = result.scalar_one_or_none()
        if not participant:
            return False

        await self.session.delete(participant)
        await self.session.flush()
        return True

    async def add_character(
        self,
        chat_id: UUID,
        character_id: UUID,
        added_by_user_id: Optional[UUID] = None  # Parameter kept for API compatibility but not stored
    ) -> ChatCharacter:
        """Add character to group chat."""
        chat_character = ChatCharacter(
            chat_id=chat_id,
            character_id=character_id
        )
        self.session.add(chat_character)
        await self.session.flush()
        await self.session.refresh(chat_character)
        return chat_character

    async def remove_character(
        self,
        chat_id: UUID,
        character_id: UUID
    ) -> bool:
        """Remove character from group chat."""
        result = await self.session.execute(
            select(ChatCharacter).where(
                and_(
                    ChatCharacter.chat_id == chat_id,
                    ChatCharacter.character_id == character_id
                )
            )
        )
        chat_character = result.scalar_one_or_none()
        if not chat_character:
            return False

        await self.session.delete(chat_character)
        await self.session.flush()
        return True

    async def get_participants(self, chat_id: UUID) -> List[User]:
        """Get all participants in a chat."""
        query = (
            select(User)
            .join(ChatParticipant, ChatParticipant.user_id == User.id)
            .where(ChatParticipant.chat_id == chat_id)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_characters(self, chat_id: UUID) -> List[Character]:
        """Get all characters in a chat."""
        query = (
            select(Character)
            .join(ChatCharacter, ChatCharacter.character_id == Character.id)
            .where(ChatCharacter.chat_id == chat_id)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_participant_role(self, chat_id: UUID, user_id: UUID) -> Optional[str]:
        """Get the role of a participant in the chat."""
        # Check if user is a participant
        result = await self.session.execute(
            select(ChatParticipant).where(
                and_(
                    ChatParticipant.chat_id == chat_id,
                    ChatParticipant.user_id == user_id,
                )
            )
        )
        participant = result.scalar_one_or_none()
        if not participant:
            return None
        
        # Return 'owner' for first participant, 'member' for others
        # In a real implementation, this would be stored in the database
        result = await self.session.execute(
            select(ChatParticipant.user_id)
            .where(ChatParticipant.chat_id == chat_id)
            .order_by(ChatParticipant.joined_at)
            .limit(1)
        )
        first_user_id = result.scalar_one_or_none()
        return "owner" if first_user_id == user_id else "member"

    async def update_last_read(
        self,
        chat_id: UUID,
        user_id: UUID,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Update the last read timestamp for a participant."""
        if timestamp is None:
            timestamp = datetime.utcnow()

        result = await self.session.execute(
            select(ChatParticipant).where(
                and_(
                    ChatParticipant.chat_id == chat_id,
                    ChatParticipant.user_id == user_id,
                )
            )
        )
        participant = result.scalar_one_or_none()
        if participant:
            participant.last_read_at = timestamp
            await self.session.flush()

    async def count_unread_messages(self, chat_id: UUID, user_id: UUID) -> int:
        """Count unread messages for a user in a chat."""
        from ..database import Message

        # Get participant's last read timestamp
        result = await self.session.execute(
            select(ChatParticipant.last_read_at).where(
                and_(
                    ChatParticipant.chat_id == chat_id,
                    ChatParticipant.user_id == user_id,
                )
            )
        )
        last_read_at = result.scalar_one_or_none()

        if last_read_at is None:
            # Count all messages if never read
            result = await self.session.execute(
                select(func.count(Message.id)).where(Message.chat_id == chat_id)
            )
        else:
            # Count messages after last read
            result = await self.session.execute(
                select(func.count(Message.id)).where(
                    and_(
                        Message.chat_id == chat_id,
                        Message.created_at > last_read_at,
                    )
                )
            )

        return result.scalar_one() or 0
