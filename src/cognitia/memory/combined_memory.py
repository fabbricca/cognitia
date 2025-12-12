"""
Combined Memory System for Cognitia.

Unifies conversation memory and entity memory into a single, 
fast context builder for LLM prompts.

Design principles:
- Zero-latency context building (all reads from memory)
- Background processing for extraction and summarization
- Clean interface for the LLM processor
"""

import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from loguru import logger

from .conversation_memory import ConversationMemory
from .entity_memory import EntityMemory


class CombinedMemory:
    """
    Unified memory interface for Cognitia.
    
    Combines:
    - ConversationMemory: Recent conversation history (fast, in-memory)
    - EntityMemory: User information extracted by LLM (background async)
    
    All public methods are designed to be instant (< 1ms).
    Heavy operations happen in background threads.
    """
    
    def __init__(
        self,
        conversation_memory: ConversationMemory,
        entity_memory: Optional[EntityMemory] = None,
        max_context_messages: int = 20,
    ):
        """
        Initialize combined memory.
        
        Args:
            conversation_memory: Existing conversation memory instance
            entity_memory: Optional entity memory instance
            max_context_messages: Maximum messages to include in context
        """
        self.conversation = conversation_memory
        self.entities = entity_memory
        self.max_context_messages = max_context_messages
        
        logger.info("CombinedMemory initialized")
    
    def on_conversation_start(self) -> None:
        """Signal that a conversation has started - pause background processing."""
        if self.entities:
            self.entities.set_busy()
    
    def on_conversation_end(self) -> None:
        """Signal that conversation ended - resume background processing."""
        if self.entities:
            self.entities.set_idle()
    
    def add_exchange(
        self,
        user_input: str,
        assistant_response: str,
        user_id: Optional[str] = None,  # v2.1+: User ID for multi-user isolation
    ) -> None:
        """
        Record a conversation exchange.

        - Stores in conversation memory (instant)
        - Queues for entity extraction (non-blocking)

        Args:
            user_input: What the user said
            assistant_response: What the assistant replied
            user_id: User ID for this exchange (v2.1+, for multi-user isolation)
        """
        # Store in conversation memory (instant, O(1))
        self.conversation.add_turn(user_input, assistant_response, user_id=user_id)

        # Queue for background entity extraction (non-blocking)
        if self.entities:
            self.entities.queue_extraction(user_input, assistant_response)
    
    def build_context_messages(
        self, 
        max_turns: Optional[int] = None,
        include_entities: bool = True,
    ) -> List[Dict[str, str]]:
        """
        Build context messages for LLM prompt injection.
        
        This is the main method used by LLM processor. It's designed
        to be instant (< 1ms) - all data comes from memory cache.
        
        Args:
            max_turns: Maximum conversation turns to include
            include_entities: Whether to include entity context
            
        Returns:
            List of message dicts with 'role' and 'content'
        """
        messages = []
        
        # 1. Add entity context as system knowledge (instant read)
        if include_entities and self.entities:
            entity_context = self.entities.get_context_string()
            if entity_context:
                messages.append({
                    "role": "system",
                    "content": f"What you know about the user: {entity_context}"
                })
        
        # 2. Add conversation history (instant read from deque)
        conv_messages = self.conversation.get_context_as_messages(max_turns)
        
        # Limit total messages if needed
        if len(conv_messages) > self.max_context_messages:
            conv_messages = conv_messages[-self.max_context_messages:]
        
        messages.extend(conv_messages)
        
        return messages
    
    def get_user_name(self) -> Optional[str]:
        """Get user's name if known. Instant access."""
        if self.entities:
            return self.entities.get_user_name()
        return None
    
    def get_conversation_summary(self, max_chars: int = 500) -> str:
        """Get a brief summary of recent conversation. Instant access."""
        return self.conversation.get_context_summary(max_chars)
    
    def get_stats(self) -> Dict[str, int]:
        """Get memory statistics."""
        stats = self.conversation.get_stats()
        
        if self.entities:
            stats["entities_count"] = len(self.entities)
            stats["user_name_known"] = 1 if self.entities.get_user_name() else 0
        
        return stats
    
    def clear_all(self) -> None:
        """Clear all memory (conversation + entities)."""
        self.conversation.clear_memory()
        if self.entities:
            self.entities.clear()
        logger.info("CombinedMemory: All memory cleared")
    
    def shutdown(self) -> None:
        """Gracefully shutdown background workers."""
        if self.entities:
            self.entities.shutdown()
        logger.debug("CombinedMemory shutdown complete")


def create_combined_memory(
    max_turns: int = 50,
    persist_dir: Optional[Path] = None,
    llm_caller: Optional[Callable[[str], str]] = None,
    enable_entities: bool = True,
    user_id: Optional[str] = None,  # v2.1+: User ID for multi-user isolation
) -> CombinedMemory:
    """
    Factory function to create a fully configured CombinedMemory.

    Args:
        max_turns: Maximum conversation turns to keep
        persist_dir: Directory for persistence (None = no persistence)
        llm_caller: Function to call LLM for entity extraction
        enable_entities: Whether to enable entity extraction
        user_id: User ID for multi-user isolation (v2.1+, optional for backward compat)

    Returns:
        Configured CombinedMemory instance
    """
    # Create conversation memory
    conv_persist = persist_dir / "conversation_memory.json" if persist_dir else None
    conversation = ConversationMemory(
        max_turns=max_turns,
        persist_path=conv_persist,
        persist_interval=30.0,
        user_id=user_id,  # v2.1+: Pass user_id
    )

    # Create entity memory if enabled
    entity_memory = None
    if enable_entities:
        entity_persist = persist_dir / "entity_memory.json" if persist_dir else None
        entity_memory = EntityMemory(
            persist_path=entity_persist,
            llm_caller=llm_caller,
            user_id=user_id,  # v2.1+: Pass user_id
        )

    return CombinedMemory(
        conversation_memory=conversation,
        entity_memory=entity_memory,
    )
