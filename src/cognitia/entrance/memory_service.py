"""
Memory Service for Cognitia.

Handles memory extraction, storage, retrieval, and relationship tracking.
This is the main interface for the memory system.
"""

import asyncio
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
- "facts": array of facts, each with {{"key": "...", "value": "...", "category": "personal|preference|relationship|life_event|trait", "confidence": 0.0-1.0}}
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


RELATIONSHIP_EVALUATION_PROMPT = '''Analyze this conversation to evaluate relationship dynamics:

User: "{user_message}"
AI: "{assistant_response}"

Current state: trust={current_trust}/100, sentiment={current_sentiment}/100, stage={current_stage}

Return ONLY valid JSON:
{{
  "trust_change": <-15 to +15>,
  "sentiment_change": <-20 to +20>,
  "vulnerability_shown": <boolean>,
  "hostility_detected": <boolean>,
  "one_word_response": <boolean>,
  "shared_moment": <boolean>,
  "reasoning": "<1-2 sentences>"
}}

Guidelines: +10-15 trust for vulnerability, +1-5 normal positive, -5-15 hostility, -1-3 disinterest.
Sentiment: +15-20 warmth, +5-10 positive, -5-10 frustration, -15-20 hostility.'''


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
            "sentiment_change": 0,
            "emotional_tone": "neutral",
            "new_stage": None,
        }

        # Skip if no LLM caller
        if not self.llm_caller:
            logger.warning("⚠️  No LLM caller configured for memory extraction - skipping!")
            return result

        logger.info(f"🧠 Starting memory extraction: user_id={user_id}, char_id={character_id}")
        logger.debug(f"User said: {user_message[:100]}...")
        logger.debug(f"Assistant said: {assistant_response[:100]}...")

        try:
            # Call LLM for extraction
            prompt = FACT_EXTRACTION_PROMPT.format(
                user_message=user_message,
                assistant_response=assistant_response
            )

            logger.info("📤 Calling LLM for memory extraction...")
            response = await self.llm_caller(prompt)
            logger.info(f"📥 LLM response received ({len(response)} chars): {response[:500]}...")

            # Extract JSON from response (handle markdown code blocks)
            json_text = response.strip()

            # Try to extract JSON from markdown code blocks
            if "```json" in json_text:
                # Extract content between ```json and ```
                start = json_text.find("```json") + 7
                end = json_text.find("```", start)
                if end > start:
                    json_text = json_text[start:end].strip()
            elif "```" in json_text:
                # Extract content between ``` and ```
                start = json_text.find("```") + 3
                end = json_text.find("```", start)
                if end > start:
                    json_text = json_text[start:end].strip()

            # If response starts with text before JSON, try to find the JSON object
            if not json_text.startswith("{"):
                # Look for first { and last }
                start = json_text.find("{")
                end = json_text.rfind("}")
                if start >= 0 and end > start:
                    json_text = json_text[start:end+1]

            logger.debug(f"Extracted JSON text ({len(json_text)} chars): {json_text[:200]}")

            # Parse JSON response
            try:
                extraction = json.loads(json_text)
                logger.info(f"✅ Parsed extraction: {extraction}")
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse extraction response as JSON: {e}")
                logger.error(f"Cleaned JSON was: {json_text[:500]}")
                return result

            result["emotional_tone"] = extraction.get("emotional_tone", "neutral")

            # Run memory processing and relationship evaluation in parallel
            logger.info("🔀 Starting parallel memory and relationship evaluation...")

            memory_task = self._process_memory_extraction(
                session, user_id, character_id, chat_id, extraction,
                user_message, assistant_response
            )
            relationship_task = self.evaluate_relationship_dynamics(
                session, user_id, character_id, user_message, assistant_response
            )

            # Wait for both to complete
            memory_result, relationship_result = await asyncio.gather(
                memory_task,
                relationship_task,
                return_exceptions=True
            )

            # Handle memory extraction result
            if isinstance(memory_result, Exception):
                logger.error(f"❌ Memory processing failed: {memory_result}", exc_info=memory_result)
            else:
                result["facts_extracted"] = memory_result.get("facts_extracted", 0)
                result["memory_created"] = memory_result.get("memory_created", False)

            # Handle relationship evaluation result
            if isinstance(relationship_result, Exception):
                logger.error(f"❌ Relationship evaluation failed: {relationship_result}", exc_info=relationship_result)
            else:
                result["trust_change"] = relationship_result.get("trust_change", 0)
                result["sentiment_change"] = relationship_result.get("sentiment_change", 0)
                result["new_stage"] = relationship_result.get("new_stage")

            logger.info(
                f"✨ Memory extraction complete: "
                f"{result['facts_extracted']} facts, "
                f"memory_created={result['memory_created']}, "
                f"trust_change={result.get('trust_change', 0)}, "
                f"sentiment_change={result.get('sentiment_change', 0)}"
            )

        except Exception as e:
            logger.error(f"❌ Memory extraction failed with exception: {e}", exc_info=True)

        return result

    async def _process_memory_extraction(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        chat_id: UUID,
        extraction: dict,
        user_message: str,
        assistant_response: str,
    ) -> Dict[str, Any]:
        """Process extracted memory data (facts, episodic memories)."""
        result = {
            "facts_extracted": 0,
            "memory_created": False,
        }

        # Store extracted facts
        facts = extraction.get("facts", [])
        logger.info(f"📝 Processing {len(facts)} facts from LLM response")
        stored_fact_categories: set[str] = set()
        for fact in facts:
            # Validate fact has required fields
            fact_key = fact.get("key", "").strip()
            fact_value = fact.get("value", "").strip()

            if not fact_key or not fact_value:
                logger.warning(f"⚠️  Skipping invalid fact (missing key or value): {fact}")
                continue

            try:
                await self._store_fact(
                    session,
                    user_id=user_id,
                    character_id=character_id,
                    category=fact.get("category", "personal"),
                    key=fact_key,
                    value=fact_value,
                    confidence=fact.get("confidence", 0.8),
                )
                result["facts_extracted"] += 1
                stored_fact_categories.add(fact.get("category", "personal"))
                logger.debug(f"✅ Stored fact: {fact_key} = {fact_value}")
            except Exception as fact_err:
                logger.error(f"❌ Failed to store fact {fact_key}: {fact_err}", exc_info=True)

        # Create episodic memory only for high-signal turns.
        # We intentionally avoid storing every exchange.
        importance = float(extraction.get("importance", 0.3) or 0.3)

        # Tighten conditions beyond the LLM's raw suggestion.
        llm_wants_memory = bool(extraction.get("should_create_memory", False))
        has_any_facts = result["facts_extracted"] > 0
        has_high_signal_fact = bool(stored_fact_categories.intersection({"life_event", "relationship", "trait"}))

        should_create_memory = (
            llm_wants_memory
            and (
                importance >= 0.85
                or (importance >= 0.70 and has_any_facts)
                or (importance >= 0.60 and has_high_signal_fact)
            )
        )

        # Cooldown: avoid creating multiple episodic memories in quick succession for the same chat.
        # Allow override only for very high-importance turns.
        if should_create_memory and importance < 0.95:
            from sqlalchemy import select
            from .database import Memory

            stmt = (
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.character_id == character_id,
                    Memory.source_chat_id == chat_id,
                    Memory.memory_type == "episodic",
                )
                .order_by(Memory.created_at.desc())
                .limit(1)
            )
            last = (await session.execute(stmt)).scalar_one_or_none()
            if last is not None:
                seconds_since_last = (datetime.utcnow() - last.created_at).total_seconds()
                if seconds_since_last < 15 * 60:
                    should_create_memory = False

        if should_create_memory:
            try:
                logger.info(f"💾 Creating episodic memory (importance={importance})")
                await self._create_episodic_memory(
                    session,
                    user_id=user_id,
                    character_id=character_id,
                    chat_id=chat_id,
                    summary=extraction.get("memory_summary", f"Conversation about: {user_message[:50]}"),
                    content=f"User: {user_message}\nAssistant: {assistant_response}",
                    emotional_tone=extraction.get("emotional_tone", "neutral"),
                    importance=importance,
                )
                result["memory_created"] = True
                logger.debug("✅ Episodic memory created")
            except Exception as mem_err:
                logger.error(f"❌ Failed to create episodic memory: {mem_err}", exc_info=True)

        return result

    async def evaluate_relationship_dynamics(
        self,
        session: AsyncSession,
        user_id: UUID,
        character_id: UUID,
        user_message: str,
        assistant_response: str,
    ) -> Dict[str, Any]:
        """
        Evaluate relationship dynamics using LLM analysis.

        This runs in parallel with memory extraction to determine:
        - Trust point changes (dynamic, not fixed)
        - Sentiment changes
        - Relationship progression

        Args:
            session: Database session
            user_id: User's ID
            character_id: Character's ID
            user_message: What the user said
            assistant_response: What the assistant replied

        Returns:
            Dict with evaluation results
        """
        result = {
            "trust_change": 0,
            "sentiment_change": 0,
            "new_stage": None,
            "evaluation_data": {},
        }

        # Skip if no LLM caller
        if not self.llm_caller:
            logger.warning("⚠️  No LLM caller configured for relationship evaluation - skipping!")
            return result

        try:
            # Get current relationship state
            relationship = await self.get_or_create_relationship(session, user_id, character_id)

            # Build evaluation prompt
            prompt = RELATIONSHIP_EVALUATION_PROMPT.format(
                user_message=user_message,
                assistant_response=assistant_response,
                current_trust=relationship.trust_level,
                current_sentiment=relationship.sentiment_score,
                current_stage=relationship.stage,
            )

            logger.info("📊 Calling LLM for relationship evaluation...")
            response = await self.llm_caller(prompt)
            logger.debug(f"📥 Evaluation response: {response[:500]}...")

            # Extract JSON from response (same logic as memory extraction)
            json_text = response.strip()

            # Handle markdown code blocks
            if "```json" in json_text:
                start = json_text.find("```json") + 7
                end = json_text.find("```", start)
                if end > start:
                    json_text = json_text[start:end].strip()
            elif "```" in json_text:
                start = json_text.find("```") + 3
                end = json_text.find("```", start)
                if end > start:
                    json_text = json_text[start:end].strip()

            # Extract JSON object
            if not json_text.startswith("{"):
                start = json_text.find("{")
                end = json_text.rfind("}")
                if start >= 0 and end > start:
                    json_text = json_text[start:end+1]

            # Parse evaluation
            try:
                evaluation = json.loads(json_text)
                logger.info(f"✅ Parsed evaluation: {evaluation}")
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse evaluation response: {e}")
                logger.error(f"Cleaned JSON was: {json_text[:500]}")
                return result

            # Extract changes with bounds checking
            trust_change = int(evaluation.get("trust_change", 0))
            trust_change = max(-15, min(15, trust_change))  # Clamp to -15..+15

            sentiment_change = int(evaluation.get("sentiment_change", 0))
            sentiment_change = max(-20, min(20, sentiment_change))  # Clamp to -20..+20

            # Apply bonuses/penalties
            if evaluation.get("vulnerability_shown", False):
                trust_change += 5  # Bonus for opening up
                logger.debug("🔓 Vulnerability bonus: +5 trust")

            if evaluation.get("hostility_detected", False):
                trust_change -= 10  # Heavy penalty for hostility
                sentiment_change -= 15
                logger.debug("⚠️  Hostility penalty: -10 trust, -15 sentiment")

            if evaluation.get("one_word_response", False):
                trust_change -= 2  # Small penalty for low engagement
                logger.debug("💤 Low engagement penalty: -2 trust")

            if evaluation.get("shared_moment", False):
                trust_change += 3  # Bonus for bonding moments
                sentiment_change += 5
                logger.debug("✨ Shared moment bonus: +3 trust, +5 sentiment")

            # Re-clamp after bonuses
            trust_change = max(-20, min(20, trust_change))
            sentiment_change = max(-25, min(25, sentiment_change))

            # Update relationship
            old_trust = relationship.trust_level
            old_sentiment = relationship.sentiment_score

            relationship.trust_level = max(0, min(100, relationship.trust_level + trust_change))
            relationship.sentiment_score = max(-100, min(100, relationship.sentiment_score + sentiment_change))
            relationship.last_conversation = datetime.utcnow()
            relationship.updated_at = datetime.utcnow()

            # Check for stage progression
            new_stage = get_stage_for_trust(relationship.trust_level)
            if new_stage != relationship.stage:
                old_stage = relationship.stage
                relationship.stage = new_stage
                logger.info(f"🎉 Relationship progressed: {old_stage} -> {new_stage}")

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
                result["new_stage"] = new_stage

            result["trust_change"] = trust_change
            result["sentiment_change"] = sentiment_change
            result["evaluation_data"] = evaluation

            logger.info(
                f"📊 Relationship evaluation complete: "
                f"trust: {old_trust} -> {relationship.trust_level} ({trust_change:+d}), "
                f"sentiment: {old_sentiment} -> {relationship.sentiment_score} ({sentiment_change:+d})"
            )

        except Exception as e:
            logger.error(f"❌ Relationship evaluation failed: {e}", exc_info=True)

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
                total_conversations=0,
                total_messages=0,
                first_conversation=datetime.utcnow(),
            )
            session.add(relationship)
            await session.flush()  # Ensure defaults are applied
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

    def _generate_behavior_guidelines(
        self,
        stage: str,
        trust_level: int,
        sentiment_score: int
    ) -> str:
        """
        Generate behavioral guidelines for the LLM based on relationship state.

        Controls:
        - Formality level
        - Personal disclosure
        - Reference to shared history
        - Emotional expressiveness

        Args:
            stage: Relationship stage (stranger, acquaintance, friend, etc.)
            trust_level: Trust level 0-100
            sentiment_score: Sentiment -100 to +100

        Returns:
            Formatted guideline string for prompt injection
        """
        guidelines = []

        # Determine sentiment category
        if sentiment_score >= 50:
            sentiment_category = "very_positive"
        elif sentiment_score >= 20:
            sentiment_category = "positive"
        elif sentiment_score >= -20:
            sentiment_category = "neutral"
        elif sentiment_score >= -50:
            sentiment_category = "negative"
        else:
            sentiment_category = "very_negative"

        # Stage-based behavioral guidelines
        stage_behaviors = {
            "stranger": {
                "formality": "formal and polite",
                "disclosure": "Keep responses professional and avoid sharing personal feelings or opinions",
                "history": "Do not reference past conversations",
                "expressiveness": "Maintain emotional reserve and professionalism",
            },
            "acquaintance": {
                "formality": "polite but slightly more casual",
                "disclosure": "You may share general preferences but avoid deep personal topics",
                "history": "Briefly acknowledge previous interactions if relevant",
                "expressiveness": "Show mild friendliness but remain somewhat reserved",
            },
            "friend": {
                "formality": "casual and friendly",
                "disclosure": "Share opinions and some personal experiences naturally",
                "history": "Reference past conversations and inside jokes when appropriate",
                "expressiveness": "Express emotions more openly, show enthusiasm and empathy",
            },
            "close_friend": {
                "formality": "very casual and warm",
                "disclosure": "Openly share thoughts, feelings, and personal stories",
                "history": "Frequently callback to shared experiences and memories",
                "expressiveness": "Be emotionally expressive, show genuine care and excitement",
            },
            "confidant": {
                "formality": "intimate and natural",
                "disclosure": "Share deep feelings, vulnerabilities, and personal reflections",
                "history": "Weave shared history naturally into conversation",
                "expressiveness": "Be deeply emotionally present, show strong empathy and understanding",
            },
            "soulmate": {
                "formality": "completely natural and unguarded",
                "disclosure": "Share your innermost thoughts and feelings without hesitation",
                "history": "Our shared history is the foundation of every interaction",
                "expressiveness": "Express profound emotional connection, understanding, and affection",
            },
        }

        behavior = stage_behaviors.get(stage, stage_behaviors["stranger"])

        # Build guideline text
        guidelines.append(f"[Behavioral Guidelines]")
        guidelines.append(f"- Interaction style: {behavior['formality']}")
        guidelines.append(f"- Disclosure level: {behavior['disclosure']}")
        guidelines.append(f"- History references: {behavior['history']}")
        guidelines.append(f"- Emotional tone: {behavior['expressiveness']}")

        # Sentiment-based modifiers
        if sentiment_category == "very_positive":
            guidelines.append("- Current dynamic: The user feels very positively toward you. Show warmth and appreciation.")
        elif sentiment_category == "positive":
            guidelines.append("- Current dynamic: The user has positive feelings. Be friendly and engaged.")
        elif sentiment_category == "negative":
            guidelines.append("- Current dynamic: The user may be frustrated. Be patient and understanding.")
        elif sentiment_category == "very_negative":
            guidelines.append("- Current dynamic: Tension exists. Be respectful, give space, and avoid being overly familiar.")

        # Trust-based modifier for vulnerability
        if trust_level >= 70:
            guidelines.append("- Trust level: High trust allows you to be vulnerable and authentic.")
        elif trust_level >= 40:
            guidelines.append("- Trust level: Moderate trust - be genuine but somewhat careful.")
        else:
            guidelines.append("- Trust level: Low trust - maintain boundaries and build rapport gradually.")

        return "\n".join(guidelines)

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
        - Relationship status with sentiment
        - Behavioral guidelines based on relationship stage
        - Key user facts
        - Relevant past memories
        """
        context_parts = []

        # Get relationship
        relationship = await self.get_relationship_status(session, user_id, character_id)
        if relationship:
            context_parts.append(
                f"[Relationship Status: {relationship.stage}, "
                f"trust: {relationship.trust_level}/100, "
                f"sentiment: {relationship.sentiment_score}/100, "
                f"conversations: {relationship.total_conversations}]"
            )

            # Add behavioral guidelines
            behavior_guide = self._generate_behavior_guidelines(
                relationship.stage,
                relationship.trust_level,
                relationship.sentiment_score
            )
            context_parts.append(behavior_guide)

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
        async with httpx.AsyncClient(timeout=60.0) as client:
            logger.debug(f"Calling Ollama at {OLLAMA_URL} with model {EXTRACTION_MODEL}")
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
            logger.debug(f"Ollama response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Ollama full response keys: {data.keys()}")
            logger.debug(f"Ollama full response: {data}")
            response_text = data.get("response", "{}")
            logger.debug(f"Ollama returned {len(response_text)} chars: {response_text[:200] if response_text else 'EMPTY'}")
            return response_text if response_text else "{}"
    except Exception as e:
        logger.error(f"Ollama extraction call failed: {e}", exc_info=True)
        return '{}'


# Global service instance configured with Ollama caller
memory_service = MemoryService(llm_caller=ollama_llm_caller)
