"""
Thread-safe state management for Cognitia.

Provides immutable snapshots and thread-safe updates for shared state.
"""

import threading
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class ConversationMessage:
    """
    Immutable conversation message.

    Attributes:
        role: Message role (system, user, assistant)
        content: Message text content
        timestamp: When message was created
        metadata: Additional message metadata
    """
    role: Literal["system", "user", "assistant"]
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str]:
        """Convert to LLM API format."""
        return {"role": self.role, "content": self.content}


class ThreadSafeConversationState:
    """
    Thread-safe conversation history with versioning.

    Provides:
    - Thread-safe read/write operations
    - Version tracking for change detection
    - Immutable message snapshots
    - Deep copy protection

    Thread Safety:
        All public methods use RLock for protection.
        Snapshots return deep copies to prevent external mutation.
    """

    def __init__(self, initial_messages: list[dict[str, str]] | None = None):
        """
        Initialize conversation state.

        Args:
            initial_messages: Initial messages (e.g., system prompts)
        """
        self._messages: list[ConversationMessage] = []
        self._lock = threading.RLock()
        self._version = 0

        # Convert initial messages if provided
        if initial_messages:
            for msg in initial_messages:
                self._messages.append(
                    ConversationMessage(
                        role=msg["role"],
                        content=msg["content"],
                        metadata=msg.get("metadata", {})
                    )
                )

    # ========================================================================
    # Public API
    # ========================================================================

    def add_message(
        self,
        role: Literal["system", "user", "assistant"],
        content: str,
        metadata: dict[str, Any] | None = None
    ) -> int:
        """
        Add message to conversation history.

        Args:
            role: Message role
            content: Message content
            metadata: Optional metadata

        Returns:
            New version number

        Thread Safety:
            Fully thread-safe with RLock protection
        """
        with self._lock:
            message = ConversationMessage(
                role=role,
                content=content,
                metadata=metadata or {}
            )
            self._messages.append(message)
            self._version += 1
            return self._version

    def get_messages(self, as_dict: bool = True) -> list[dict[str, str]] | list[ConversationMessage]:
        """
        Get immutable copy of all messages.

        Args:
            as_dict: If True, return dict format; otherwise ConversationMessage objects

        Returns:
            Deep copy of messages (prevents external mutation)

        Thread Safety:
            Returns deep copy, original data protected
        """
        with self._lock:
            if as_dict:
                return [msg.to_dict() for msg in self._messages]
            else:
                return deepcopy(self._messages)

    def get_recent_messages(
        self,
        count: int,
        as_dict: bool = True
    ) -> list[dict[str, str]] | list[ConversationMessage]:
        """
        Get last N messages.

        Args:
            count: Number of recent messages to retrieve
            as_dict: Return format

        Returns:
            Recent messages snapshot
        """
        with self._lock:
            recent = self._messages[-count:] if count < len(self._messages) else self._messages
            if as_dict:
                return [msg.to_dict() for msg in recent]
            else:
                return deepcopy(recent)

    def get_version(self) -> int:
        """
        Get current version number.

        Useful for change detection without copying data.

        Returns:
            Current version (increments on each modification)
        """
        with self._lock:
            return self._version

    def clear(self, keep_system_prompts: bool = True) -> None:
        """
        Clear conversation history.

        Args:
            keep_system_prompts: If True, preserve system role messages
        """
        with self._lock:
            if keep_system_prompts:
                self._messages = [
                    msg for msg in self._messages
                    if msg.role == "system"
                ]
            else:
                self._messages = []
            self._version += 1

    def __len__(self) -> int:
        """Get message count (thread-safe)."""
        with self._lock:
            return len(self._messages)

    def __repr__(self) -> str:
        """String representation."""
        with self._lock:
            return f"ConversationState(messages={len(self._messages)}, version={self._version})"
