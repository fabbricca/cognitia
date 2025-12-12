"""
Conversation Memory System for Cognitia.

A high-performance, low-latency memory system that stores and retrieves
conversation history for context injection into LLM prompts.
"""

import json
import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel


class ConversationTurn(BaseModel):
    """Represents a single conversation turn."""

    user_input: str
    assistant_response: str
    timestamp: float
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None  # v2.1+: User who created this turn

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for storage."""
        return {
            "user_input": self.user_input,
            "assistant_response": self.assistant_response,
            "timestamp": self.timestamp,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "ConversationTurn":
        """Create from dictionary."""
        return cls(
            user_input=data["user_input"],
            assistant_response=data["assistant_response"],
            timestamp=float(data["timestamp"]),
            conversation_id=data.get("conversation_id"),
            user_id=data.get("user_id"),
        )


class ConversationMemory:
    """
    High-performance conversation memory with minimal latency impact.

    Features:
    - In-memory storage with configurable size limits
    - Async persistence to disk
    - Thread-safe operations
    - Efficient context retrieval
    - Optional async LLM summarization for older turns
    """

    # Prompt for LLM summarization (when configured)
    SUMMARY_PROMPT = '''Summarize the key information from this conversation in 2-3 sentences.
Focus on: user preferences, important facts, decisions made, and context needed for future reference.

Conversation:
{conversation}

Summary (be concise):'''

    def __init__(
        self,
        max_turns: int = 50,
        persist_path: Optional[Path] = None,
        persist_interval: float = 30.0,  # Save every 30 seconds
        llm_summarizer: Optional[Callable[[str], str]] = None,
        user_id: Optional[str] = None,  # v2.1+: User ID for multi-user isolation
    ):
        """
        Initialize conversation memory.

        Args:
            max_turns: Maximum number of conversation turns to keep in memory
            persist_path: Path to save/load conversation history
            persist_interval: How often to persist to disk (seconds)
            llm_summarizer: Optional function to call LLM for summarization
            user_id: User ID for multi-user isolation (v2.1+, optional for backward compat)
        """
        self.max_turns = max_turns
        self.persist_path = persist_path
        self.persist_interval = persist_interval
        self.llm_summarizer = llm_summarizer
        self.user_id = user_id  # v2.1+: Filter conversations by this user
        
        # Cached summary of older conversations (updated in background)
        self._cached_summary: Optional[str] = None
        self._summary_lock = threading.Lock()
        self._summary_up_to_index: int = 0  # How many turns are summarized

        # Use deque for O(1) append and efficient memory usage
        self._turns: deque[ConversationTurn] = deque(maxlen=max_turns)

        # Persistence state
        self._last_persist_time = time.time()
        self._persist_lock = threading.Lock()
        self._is_dirty = False

        # Load existing conversations if available
        if persist_path and persist_path.exists():
            self._load_from_disk()

        logger.info(f"ConversationMemory initialized with max {max_turns} turns")

    def add_turn(
        self,
        user_input: str,
        assistant_response: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,  # v2.1+: Override instance user_id if provided
    ) -> None:
        """
        Add a new conversation turn.

        Args:
            user_input: User's input text
            assistant_response: Assistant's response text
            conversation_id: Optional conversation identifier
            user_id: User ID for this turn (v2.1+, overrides instance user_id if provided)
        """
        # Use provided user_id if given, otherwise fall back to instance user_id
        turn_user_id = user_id if user_id is not None else self.user_id

        turn = ConversationTurn(
            user_input=user_input.strip(),
            assistant_response=assistant_response.strip(),
            timestamp=time.time(),
            conversation_id=conversation_id,
            user_id=turn_user_id,  # v2.1+: Tag turn with user_id
        )

        self._turns.append(turn)
        self._is_dirty = True

        # Async persistence check (non-blocking)
        self._check_persistence()

        logger.debug(f"Added conversation turn: {len(self._turns)} total turns")

    def get_recent_context(self, max_turns: Optional[int] = None) -> List[ConversationTurn]:
        """
        Get recent conversation context for LLM prompt injection.

        Args:
            max_turns: Maximum turns to return (None = all available)

        Returns:
            List of recent conversation turns
        """
        if max_turns is None:
            return list(self._turns)

        # Return the most recent max_turns
        return list(self._turns)[-max_turns:] if max_turns > 0 else []

    def get_context_as_messages(self, max_turns: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Get conversation context formatted as chat messages for LLM.

        Args:
            max_turns: Maximum conversation turns to include

        Returns:
            List of message dictionaries with 'role' and 'content'
        """
        turns = self.get_recent_context(max_turns)
        messages = []

        for turn in turns:
            messages.extend([
                {"role": "user", "content": turn.user_input},
                {"role": "assistant", "content": turn.assistant_response}
            ])

        return messages

    def get_context_summary(self, max_chars: int = 1000) -> str:
        """
        Get a summary of recent conversation context.

        Args:
            max_chars: Maximum characters in summary

        Returns:
            Formatted conversation summary
        """
        turns = self.get_recent_context()
        if not turns:
            return ""

        summary_parts = []
        total_chars = 0

        for turn in reversed(turns):  # Most recent first
            part = f"User: {turn.user_input}\nAssistant: {turn.assistant_response}\n"
            part_chars = len(part)

            if total_chars + part_chars > max_chars:
                break

            summary_parts.insert(0, part)  # Insert at beginning to maintain order
            total_chars += part_chars

        return "".join(summary_parts).strip()

    def get_compressed_context(
        self, 
        recent_turns: int = 5,
    ) -> List[Dict[str, str]]:
        """
        Get context with recent turns verbatim + summary of older turns.
        
        This reduces token usage while preserving important context.
        The summary is cached and updated in background.
        
        Args:
            recent_turns: Number of recent turns to include verbatim
            
        Returns:
            List of message dicts for LLM
        """
        all_turns = list(self._turns)
        messages = []
        
        # Add cached summary of older turns if available
        with self._summary_lock:
            if self._cached_summary:
                messages.append({
                    "role": "system",
                    "content": f"Previous conversation summary: {self._cached_summary}"
                })
        
        # Add recent turns verbatim
        recent = all_turns[-recent_turns:] if len(all_turns) > recent_turns else all_turns
        for turn in recent:
            messages.extend([
                {"role": "user", "content": turn.user_input},
                {"role": "assistant", "content": turn.assistant_response}
            ])
        
        return messages
    
    def trigger_summary_update(self, recent_turns_to_keep: int = 5) -> None:
        """
        Trigger background update of conversation summary.
        
        Call this during idle time to summarize older conversations.
        Non-blocking - runs in background thread.
        
        Args:
            recent_turns_to_keep: Don't summarize these recent turns
        """
        if not self.llm_summarizer:
            return
        
        all_turns = list(self._turns)
        turns_to_summarize = all_turns[:-recent_turns_to_keep] if len(all_turns) > recent_turns_to_keep else []
        
        # Only update if we have new turns to summarize
        if len(turns_to_summarize) <= self._summary_up_to_index:
            return
        
        # Run summarization in background
        summary_thread = threading.Thread(
            target=self._update_summary_async,
            args=(turns_to_summarize,),
            daemon=True,
            name="ConversationSummarizer"
        )
        summary_thread.start()
    
    def _update_summary_async(self, turns: List[ConversationTurn]) -> None:
        """Background task to update conversation summary."""
        if not turns or not self.llm_summarizer:
            return
        
        try:
            # Format conversation for summarization
            conv_text = "\n".join([
                f"User: {t.user_input}\nAssistant: {t.assistant_response}"
                for t in turns[-10:]  # Summarize last 10 turns max at a time
            ])
            
            prompt = self.SUMMARY_PROMPT.format(conversation=conv_text)
            summary = self.llm_summarizer(prompt)
            
            if summary and len(summary.strip()) > 10:
                with self._summary_lock:
                    # Merge with existing summary if any
                    if self._cached_summary:
                        self._cached_summary = f"{self._cached_summary} {summary.strip()}"
                        # Trim if too long
                        if len(self._cached_summary) > 500:
                            self._cached_summary = self._cached_summary[-500:]
                    else:
                        self._cached_summary = summary.strip()
                    
                    self._summary_up_to_index = len(turns)
                
                logger.debug(f"ConversationMemory: Updated summary ({len(self._cached_summary)} chars)")
                
        except Exception as e:
            logger.warning(f"ConversationMemory: Summary update failed: {e}")

    def clear_memory(self) -> None:
        """Clear all conversation memory."""
        self._turns.clear()
        self._cached_summary = None
        self._summary_up_to_index = 0
        self._is_dirty = True
        self._persist_async()  # Force immediate persistence
        logger.info("Conversation memory cleared")

    def get_stats(self) -> Dict[str, int]:
        """Get memory statistics."""
        return {
            "total_turns": len(self._turns),
            "max_turns": self.max_turns,
            "memory_usage_mb": self._estimate_memory_usage(),
            "has_summary": 1 if self._cached_summary else 0,
        }

    def _estimate_memory_usage(self) -> float:
        """Estimate memory usage in MB."""
        # Rough estimation: each turn ~200 bytes average
        avg_bytes_per_turn = 200
        return (len(self._turns) * avg_bytes_per_turn) / (1024 * 1024)

    def _check_persistence(self) -> None:
        """Check if persistence is needed and trigger async save."""
        current_time = time.time()
        if current_time - self._last_persist_time > self.persist_interval and self._is_dirty:
            self._persist_async()

    def _persist_async(self) -> None:
        """Trigger async persistence to disk."""
        if not self.persist_path:
            return

        # Use a separate thread for persistence to avoid blocking
        persist_thread = threading.Thread(
            target=self._persist_to_disk,
            daemon=True,
            name="MemoryPersistence"
        )
        persist_thread.start()

    def _persist_to_disk(self) -> None:
        """Persist conversation memory to disk."""
        if not self.persist_path:
            return

        try:
            with self._persist_lock:
                data = {
                    "turns": [turn.to_dict() for turn in self._turns],
                    "metadata": {
                        "max_turns": self.max_turns,
                        "created_at": time.time(),
                        "total_turns": len(self._turns),
                        "user_id": self.user_id,  # v2.1+: Store user_id in metadata
                    }
                }

                # Ensure directory exists
                self.persist_path.parent.mkdir(parents=True, exist_ok=True)

                # Write to temporary file first, then rename (atomic write)
                temp_path = self.persist_path.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                temp_path.replace(self.persist_path)

                self._last_persist_time = time.time()
                self._is_dirty = False

                logger.debug(f"Persisted {len(self._turns)} conversation turns to {self.persist_path}")

        except Exception as e:
            logger.error(f"Failed to persist conversation memory: {e}")

    def _load_from_disk(self) -> None:
        """Load conversation memory from disk."""
        if not self.persist_path or not self.persist_path.exists():
            return

        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            turns_data = data.get("turns", [])
            loaded_count = 0

            for turn_data in turns_data:
                turn = ConversationTurn.from_dict(turn_data)

                # v2.1+: Filter by user_id if set (multi-user isolation)
                if self.user_id is not None:
                    # Only load turns that belong to this user
                    if turn.user_id == self.user_id:
                        self._turns.append(turn)
                        loaded_count += 1
                else:
                    # Backward compatibility: load all turns if no user_id set
                    self._turns.append(turn)
                    loaded_count += 1

            logger.info(f"Loaded {loaded_count} conversation turns from {self.persist_path}")
            if self.user_id:
                logger.debug(f"Filtered for user_id: {self.user_id}")

        except Exception as e:
            logger.error(f"Failed to load conversation memory: {e}")
            # Continue with empty memory if loading fails

    def __len__(self) -> int:
        """Return number of conversation turns."""
        return len(self._turns)

    def __bool__(self) -> bool:
        """Return True if memory contains turns."""
        return bool(self._turns)

