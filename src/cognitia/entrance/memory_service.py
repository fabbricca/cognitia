"""
Memory Service for Cognitia.

Handles memory extraction, storage, retrieval, and relationship tracking.
This is the main interface for the memory system.
"""

import json
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Callable, Awaitable, Union
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import select, and_, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Memory, UserFact, Relationship, DiaryEntry, Message, Chat


# =============================================================================
# Memory Extraction Prompts
# =============================================================================

FACT_EXTRACTION_PROMPT = '''Extract any personal information the user revealed about themselves from this conversation exchange.

Return a JSON object with these optional fields (only include fields if information was found):
- "facts": array of facts, each with {"key": "...", "value": "...", "category": "personal|preference|relationship|life_event|trait", "confidence": 0.0-1.0}
- "emotional_tone": overall emotional tone ("happy", "sad", "excited", "anxious", "neutral", "frustrated", "loving", etc.)
- "importance": 0.0-1.0 rating of how important this exchange is to remember
- "should_create_memory": true/false - should we create an episodic memory for this?
- "memory_summary": if should_create_memory is true, a 1-2 sentence summary of the memorable event

User said: "{user_message}"
Assistant replied: "{assistant_response}"

Return only valid JSON. Return {{"facts": [], "emotional_tone": "neutral", "importance": 0.3, "should_create_memory": false}} if nothing notable.'''

DIARY_SUMMARY_PROMPT = '''Summarize today's conversation between the user and the AI character in 2-3 sentences.
Focus on: key topics discussed, emotional highlights, important information learned, and memorable moments.

Write from the AI character's perspective, as if reflecting on the day.

Conversation:
{conversation}

Write a warm, personal diary entry (2-3 sentences):'''


# =============================================================================
# Relationship Stage Logic
# =============================================================================

RELATIONSHIP_STAGES = [
    ("stranger", 0, 10),
    ("acquaintance", 11, 30),
    ("friend", 31, 50),
    ("close_friend", 51, 70),
    ("confidant", 71, 90),
    ("soulmate", 91, 100),
]


def get_stage_for_trust(trust_level: int) -> str:
    """Get relationship stage name for a given trust level."""
    for stage, min_trust, max_trust in RELATIONSHIP_STAGES:
        if min_trust <= trust_level <= max_trust:
            return stage
    return "soulmate" if trust_level > 100 else "stranger"


# Trust point rewards for various interactions
TRUST_REWARDS = {
    "daily_conversation": 1,
    "shared_secret": 5,
    "emotional_support": 3,
    "remembered_fact": 2,
    "inside_joke": 4,
    "helped_with_problem": 3,
    "opened_up": 4,
    "first_conversation": 5,
    "streak_7_days": 5,
    "streak_30_days": 10,
}


# =============================================================================
# Memory Service Class
# =============================================================================

class MemoryService:
    """Service for managing the memory system."""

    def __init__(self, llm_caller: Optional[Callable[[str], Awaitable[str]]] = None):
        """
        Initialize memory service.
        
        Args:
            llm_caller: Async function to call LLM for extraction.
                       Signature: async (prompt: str) -> str
        """
        self.llm_caller = llm_caller

    # -------------------------------------------------------------------------
    # Memory Extraction
    # -------------------------------------------------------------------------

    async def extract_and_store_memories(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        chat_id: UUID,
        user_message: str,
        assistant_response: str,
    ) -> Dict[str, Any]:
        """
        Extract memories from a conversation exchange and store them.
        
        This should be called after each exchange. It:
        1. Extracts facts about the user
        2. Determines if an episodic memory should be created
        3. Updates relationship metrics
        
        Args:
            session: Database session
            user_id: User's ID
            character_id: Character's ID
            chat_id: Current chat ID
            user_message: What the user said
            assistant_response: What the assistant replied
            
        Returns:
            Dict with extraction results
        """
        result = {
            "facts_extracted": 0,
            "memory_created": False,
            "trust_change": 0,
            "emotional_tone": "neutral",
        }

        # Skip if no LLM caller
        if not self.llm_caller:
            logger.debug("No LLM caller configured, skipping memory extraction")
            return result

        try:
            # Call LLM for extraction
            prompt = FACT_EXTRACTION_PROMPT.format(
                user_message=user_message,
                assistant_response=assistant_response
            )
            response = await self.llm_caller(prompt)
            
            # Parse JSON response
            try:
                extraction = json.loads(response)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse extraction response: {response}")
                return result

            result["emotional_tone"] = extraction.get("emotional_tone", "neutral")
            importance = extraction.get("importance", 0.3)

            # Store extracted facts
            facts = extraction.get("facts", [])
            for fact in facts:
                await self._store_fact(
                    session,
                    user_id=user_id,
                    character_id=character_id,
                    category=fact.get("category", "personal"),
                    key=fact.get("key", ""),
                    value=fact.get("value", ""),
                    confidence=fact.get("confidence", 0.8),
                )
                result["facts_extracted"] += 1

            # Create episodic memory if important
            if extraction.get("should_create_memory", False) and importance > 0.5:
                await self._create_episodic_memory(
                    session,
                    user_id=user_id,
                    character_id=character_id,
                    chat_id=chat_id,
                    summary=extraction.get("memory_summary", f"Conversation about: {user_message[:50]}"),
                    content=f"User: {user_message}\nAssistant: {assistant_response}",
                    emotional_tone=result["emotional_tone"],
                    importance=importance,
                )
                result["memory_created"] = True

            # Update relationship
            trust_change = await self._update_relationship_on_exchange(
                session,
                user_id=user_id,
                character_id=character_id,
                emotional_tone=result["emotional_tone"],
                facts_shared=len(facts),
            )
            result["trust_change"] = trust_change

        except Exception as e:
            logger.error(f"Memory extraction error: {e}")

        return result

    async def _store_fact(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        category: str,
        key: str,
        value: str,
        confidence: float = 0.8,
        source_memory_id: Optional[UUID] = None,
    ) -> Optional[UserFact]:
        """Store or update a user fact."""
        if not key or not value:
            return None

        # Check if fact already exists
        stmt = select(UserFact).where(
            and_(
                UserFact.user_id == user_id,
                UserFact.character_id == character_id,
                UserFact.key == key,
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update if new confidence is higher or same value
            if confidence >= existing.confidence or existing.value == value:
                existing.value = value
                existing.confidence = confidence
                existing.updated_at = datetime.utcnow()
                logger.debug(f"Updated fact: {key} = {value}")
        else:
            # Create new fact
            fact = UserFact(
                id=uuid4(),
                user_id=user_id,
                character_id=character_id,
                category=category,
                key=key,
                value=value,
                confidence=confidence,
                source_memory_id=source_memory_id,
            )
            session.add(fact)
            logger.debug(f"Created fact: {key} = {value}")
            return fact

        return existing

    async def _create_episodic_memory(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        chat_id: UUID,
        summary: str,
        content: str,
        emotional_tone: str,
        importance: float,
    ) -> Memory:
        """Create an episodic memory entry."""
        memory = Memory(
            id=uuid4(),
            user_id=user_id,
            character_id=character_id,
            memory_type="episodic",
            content=content,
            summary=summary,
            emotional_tone=emotional_tone,
            importance=importance,
            source_chat_id=chat_id,
        )
        session.add(memory)
        logger.info(f"Created episodic memory: {summary[:50]}...")
        return memory

    # -------------------------------------------------------------------------
    # Relationship Management
    # -------------------------------------------------------------------------

    async def get_or_create_relationship(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
    ) -> Relationship:
        """Get or create relationship record between user and character."""
        stmt = select(Relationship).where(
            and_(
                Relationship.user_id == user_id,
                Relationship.character_id == character_id,
            )
        )
        result = await session.execute(stmt)
        relationship = result.scalar_one_or_none()

        if not relationship:
            relationship = Relationship(
                id=uuid4(),
                user_id=user_id,
                character_id=character_id,
                stage="stranger",
                trust_level=0,
                first_conversation=datetime.utcnow(),
            )
            session.add(relationship)
            logger.info(f"Created new relationship for user {user_id} with character {character_id}")

        return relationship

    async def _update_relationship_on_exchange(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        emotional_tone: str,
        facts_shared: int = 0,
    ) -> int:
        """Update relationship metrics after an exchange."""
        relationship = await self.get_or_create_relationship(session, user_id, character_id)
        
        trust_change = 0

        # Base reward for conversation
        trust_change += TRUST_REWARDS["daily_conversation"]

        # Bonus for sharing personal info
        if facts_shared > 0:
            trust_change += min(facts_shared * TRUST_REWARDS["remembered_fact"], 10)

        # Emotional bonuses
        if emotional_tone in ["loving", "grateful", "happy"]:
            trust_change += 2
        elif emotional_tone in ["vulnerable", "sad", "anxious"]:
            trust_change += TRUST_REWARDS["opened_up"]  # Opening up builds trust

        # Update relationship
        relationship.trust_level = min(100, relationship.trust_level + trust_change)
        relationship.total_messages += 2  # User + assistant
        relationship.last_conversation = datetime.utcnow()

        # Check for stage progression
        new_stage = get_stage_for_trust(relationship.trust_level)
        if new_stage != relationship.stage:
            old_stage = relationship.stage
            relationship.stage = new_stage
            logger.info(f"Relationship progressed: {old_stage} -> {new_stage}")
            
            # Add milestone
            milestones = relationship.milestones or []
            if isinstance(milestones, str):
                milestones = json.loads(milestones) if milestones else []
            milestones.append({
                "name": f"became_{new_stage}",
                "date": datetime.utcnow().isoformat(),
                "description": f"Relationship evolved to {new_stage}",
            })
            relationship.milestones = milestones

        relationship.updated_at = datetime.utcnow()
        return trust_change

    async def add_inside_joke(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        joke: str,
        context: str,
    ) -> None:
        """Record an inside joke between user and character."""
        relationship = await self.get_or_create_relationship(session, user_id, character_id)
        
        inside_jokes = relationship.inside_jokes or []
        if isinstance(inside_jokes, str):
            inside_jokes = json.loads(inside_jokes) if inside_jokes else []
        
        inside_jokes.append({
            "joke": joke,
            "context": context,
            "created_at": datetime.utcnow().isoformat(),
        })
        relationship.inside_jokes = inside_jokes
        relationship.trust_level = min(100, relationship.trust_level + TRUST_REWARDS["inside_joke"])
        
        logger.info(f"Added inside joke: {joke[:30]}...")

    # -------------------------------------------------------------------------
    # Memory Retrieval
    # -------------------------------------------------------------------------

    async def get_user_facts(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        category: Optional[str] = None,
    ) -> List[UserFact]:
        """Get all facts known about a user for a character."""
        stmt = select(UserFact).where(
            and_(
                UserFact.user_id == user_id,
                UserFact.character_id == character_id,
            )
        )
        if category:
            stmt = stmt.where(UserFact.category == category)
        
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_relevant_memories(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        query: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 5,
    ) -> List[Memory]:
        """
        Get relevant memories for context injection.
        
        For now, returns most recent important memories.
        TODO: Add vector search for semantic relevance.
        """
        stmt = select(Memory).where(
            and_(
                Memory.user_id == user_id,
                Memory.character_id == character_id,
            )
        )
        if memory_type:
            stmt = stmt.where(Memory.memory_type == memory_type)
        
        # Order by importance and recency
        stmt = stmt.order_by(Memory.importance.desc(), Memory.created_at.desc())
        stmt = stmt.limit(limit)
        
        result = await session.execute(stmt)
        memories = list(result.scalars().all())
        
        # Update access tracking
        for memory in memories:
            memory.access_count += 1
            memory.last_accessed = datetime.utcnow()
        
        return memories

    async def get_relationship_status(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
    ) -> Optional[Relationship]:
        """Get current relationship status."""
        stmt = select(Relationship).where(
            and_(
                Relationship.user_id == user_id,
                Relationship.character_id == character_id,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # Context Building for LLM
    # -------------------------------------------------------------------------

    async def build_memory_context(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        current_message: Optional[str] = None,
        max_facts: int = 10,
        max_memories: int = 3,
    ) -> str:
        """
        Build memory context string for LLM prompt injection.
        
        Returns a formatted string with:
        - Relationship status
        - Key user facts
        - Relevant past memories
        """
        context_parts = []

        # Get relationship
        relationship = await self.get_relationship_status(session, user_id, character_id)
        if relationship:
            context_parts.append(
                f"[Relationship: {relationship.stage}, trust: {relationship.trust_level}/100, "
                f"conversations: {relationship.total_conversations}]"
            )

        # Get user facts
        facts = await self.get_user_facts(session, user_id, character_id)
        if facts:
            facts_str = ", ".join(f"{f.key}: {f.value}" for f in facts[:max_facts])
            context_parts.append(f"[Known about user: {facts_str}]")

        # Get relevant memories
        memories = await self.get_relevant_memories(
            session, user_id, character_id,
            query=current_message,
            limit=max_memories
        )
        if memories:
            memories_str = "; ".join(m.summary for m in memories if m.summary)
            if memories_str:
                context_parts.append(f"[Past memories: {memories_str}]")

        return "\n".join(context_parts)

    # -------------------------------------------------------------------------
    # Diary System
    # -------------------------------------------------------------------------

    async def create_daily_diary(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        target_date: Optional[date] = None,
    ) -> Optional[DiaryEntry]:
        """
        Create daily diary entry summarizing conversations.
        
        Should be called at end of day or during quiet periods.
        """
        if target_date is None:
            target_date = date.today()

        # Check if diary already exists
        stmt = select(DiaryEntry).where(
            and_(
                DiaryEntry.user_id == user_id,
                DiaryEntry.character_id == character_id,
                DiaryEntry.entry_date == target_date,
                DiaryEntry.entry_type == "daily",
            )
        )
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            logger.debug(f"Diary already exists for {target_date}")
            return None

        # Get messages from that day
        # TODO: This needs to join through Chat to get the right messages
        # For now, return None - will implement after testing basic flow
        logger.info(f"Would create diary for {target_date} - implementation pending")
        return None

    # -------------------------------------------------------------------------
    # Memory Cleanup
    # -------------------------------------------------------------------------

    async def decay_memory_importance(
        self,
        session: AsyncSession,
        decay_factor: float = 0.95,
    ) -> int:
        """
        Apply importance decay to old memories.
        
        Should be run periodically (e.g., daily) to ensure old
        unaccessed memories fade in importance.
        """
        # Decay memories not accessed in the last 7 days
        cutoff = datetime.utcnow() - timedelta(days=7)
        
        stmt = (
            update(Memory)
            .where(Memory.last_accessed < cutoff)
            .values(importance=Memory.importance * decay_factor)
        )
        result = await session.execute(stmt)
        
        logger.info(f"Decayed importance for {result.rowcount} memories")
        return result.rowcount

    async def delete_memory(
        self,
        session: AsyncSession,
        memory_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Delete a specific memory (user-initiated forget)."""
        stmt = delete(Memory).where(
            and_(
                Memory.id == memory_id,
                Memory.user_id == user_id,
            )
        )
        result = await session.execute(stmt)
        return result.rowcount > 0


# Missing import
from datetime import timedelta


# =============================================================================
# Ollama LLM Caller for Memory Extraction
# =============================================================================

async def ollama_llm_caller(prompt: str) -> str:
    """
    Call Ollama for memory extraction.
    
    Uses a smaller/faster model for extraction to reduce latency.
    """
    import httpx
    import os
    
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://10.0.0.15:11434")
    # Use a smaller model for extraction if available, else fall back to main model
    EXTRACTION_MODEL = os.getenv("MEMORY_EXTRACTION_MODEL", os.getenv("OLLAMA_MODEL", "llama3.2:3b"))
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": EXTRACTION_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temp for consistent extraction
                        "num_predict": 500,  # Short responses needed
                    }
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "{}")
    except Exception as e:
        logger.error(f"Ollama extraction call failed: {e}")
        return '{}'


# Global service instance configured with Ollama caller
memory_service = MemoryService(llm_caller=ollama_llm_caller)
