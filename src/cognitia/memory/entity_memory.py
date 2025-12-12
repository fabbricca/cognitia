"""
Entity Memory System for Cognitia.

A lightweight, async-first entity extraction and storage system.
Uses LLM for intelligent extraction during idle time - no hardcoded patterns.
Designed for speed: zero-latency reads, background writes.
"""

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


@dataclass
class UserEntity:
    """Tracked information about the user. All fields are dynamic."""

    # Core identity
    name: Optional[str] = None
    user_id: Optional[str] = None  # v2.1+: ID of the user this entity belongs to

    # Dynamic key-value store for any extracted information
    # Examples: {"favorite_color": "blue", "job": "engineer", "pet": "dog named Max"}
    attributes: Dict[str, str] = field(default_factory=dict)

    # Relationships: {"mom": "Sarah", "boss": "John"}
    relationships: Dict[str, str] = field(default_factory=dict)

    # Important facts as free-form strings
    facts: List[str] = field(default_factory=list)

    # Timestamps for cache invalidation
    last_updated: float = field(default_factory=time.time)


class EntityMemory:
    """
    Fast, async entity extraction and storage.
    
    Design principles:
    - Reads are instant (from memory cache)
    - Writes happen in background thread
    - LLM extraction runs only during idle time
    - No hardcoded patterns - fully dynamic
    """
    
    # Extraction prompt - tells LLM what to look for
    EXTRACTION_PROMPT = '''Extract any personal information the user revealed about themselves from this conversation turn.
Return a JSON object with these optional fields (only include fields if information was found):
- "name": user's name if mentioned
- "attributes": object of key-value pairs for preferences, facts about user (e.g., {"favorite_color": "blue", "job": "engineer"})
- "relationships": object mapping relationship to name (e.g., {"mom": "Sarah", "friend": "Alex"})
- "facts": array of important facts as strings

User said: "{user_input}"
Assistant replied: "{assistant_response}"

Return only valid JSON, no explanation. Return empty object {{}} if no personal info found.'''

    def __init__(
        self,
        persist_path: Optional[Path] = None,
        llm_caller: Optional[Callable[[str], str]] = None,
        user_id: Optional[str] = None,  # v2.1+: User ID for multi-user isolation
    ):
        """
        Initialize entity memory.

        Args:
            persist_path: Where to save extracted entities
            llm_caller: Async function to call LLM for extraction
                       Signature: (prompt: str) -> str (JSON response)
            user_id: User ID for multi-user isolation (v2.1+, optional for backward compat)
        """
        self.persist_path = persist_path
        self.llm_caller = llm_caller
        self.user_id = user_id  # v2.1+: Filter entities by this user

        # In-memory cache - instant access
        self.user = UserEntity(user_id=user_id)
        
        # Queue for background processing
        self._extraction_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        
        # Background worker state
        self._worker_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._is_idle = threading.Event()
        self._is_idle.set()  # Start as idle
        
        # Load existing data
        if persist_path and persist_path.exists():
            self._load()
        
        # Start background worker
        self._start_worker()
        
        logger.info("EntityMemory initialized")
    
    def _start_worker(self) -> None:
        """Start background extraction worker."""
        self._worker_thread = threading.Thread(
            target=self._extraction_worker,
            daemon=True,
            name="EntityExtractionWorker"
        )
        self._worker_thread.start()
    
    def _extraction_worker(self) -> None:
        """Background worker that processes extraction queue during idle time."""
        while not self._shutdown_event.is_set():
            try:
                # Wait for idle state before processing
                if not self._is_idle.wait(timeout=0.1):
                    continue
                
                # Try to get an item (non-blocking check first)
                try:
                    user_input, assistant_response = self._extraction_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                # Double-check we're still idle (conversation might have started)
                if not self._is_idle.is_set():
                    # Put it back and wait
                    self._extraction_queue.put((user_input, assistant_response))
                    continue
                
                # Perform extraction
                self._extract_with_llm(user_input, assistant_response)
                
            except Exception as e:
                logger.error(f"EntityMemory worker error: {e}")
                time.sleep(0.1)
        
        logger.debug("EntityMemory worker stopped")
    
    def _extract_with_llm(self, user_input: str, assistant_response: str) -> None:
        """Use LLM to extract entities from conversation turn."""
        if not self.llm_caller:
            return
        
        try:
            prompt = self.EXTRACTION_PROMPT.format(
                user_input=user_input,
                assistant_response=assistant_response
            )
            
            response = self.llm_caller(prompt)
            
            # Parse JSON response
            try:
                # Handle potential markdown code blocks
                if "```" in response:
                    # Extract JSON from code block
                    start = response.find("{")
                    end = response.rfind("}") + 1
                    if start >= 0 and end > start:
                        response = response[start:end]
                
                data = json.loads(response.strip())
                
                if not isinstance(data, dict):
                    return
                
                # Update user entity
                updated = False
                
                if "name" in data and data["name"]:
                    self.user.name = str(data["name"]).strip()
                    updated = True
                    logger.debug(f"EntityMemory: Learned user name: {self.user.name}")
                
                if "attributes" in data and isinstance(data["attributes"], dict):
                    for key, value in data["attributes"].items():
                        self.user.attributes[str(key).lower()] = str(value)
                        updated = True
                    logger.debug(f"EntityMemory: Learned attributes: {data['attributes']}")
                
                if "relationships" in data and isinstance(data["relationships"], dict):
                    for rel, name in data["relationships"].items():
                        self.user.relationships[str(rel).lower()] = str(name)
                        updated = True
                    logger.debug(f"EntityMemory: Learned relationships: {data['relationships']}")
                
                if "facts" in data and isinstance(data["facts"], list):
                    for fact in data["facts"]:
                        fact_str = str(fact).strip()
                        if fact_str and fact_str not in self.user.facts:
                            self.user.facts.append(fact_str)
                            updated = True
                    if data["facts"]:
                        logger.debug(f"EntityMemory: Learned facts: {data['facts']}")
                
                if updated:
                    self.user.last_updated = time.time()
                    self._save()
                    
            except json.JSONDecodeError:
                logger.trace(f"EntityMemory: Failed to parse LLM response as JSON: {response[:100]}")
                
        except Exception as e:
            logger.warning(f"EntityMemory: LLM extraction failed: {e}")
    
    def queue_extraction(self, user_input: str, assistant_response: str) -> None:
        """
        Queue a conversation turn for background entity extraction.
        This is non-blocking and returns immediately.
        """
        self._extraction_queue.put((user_input, assistant_response))
    
    def set_busy(self) -> None:
        """Signal that a conversation is active - pause background processing."""
        self._is_idle.clear()
    
    def set_idle(self) -> None:
        """Signal that conversation is idle - resume background processing."""
        self._is_idle.set()
    
    def get_context_string(self) -> str:
        """
        Get a string summarizing what we know about the user.
        This is instant - reads from memory cache only.
        """
        parts = []
        
        if self.user.name:
            parts.append(f"User's name is {self.user.name}.")
        
        if self.user.attributes:
            # Format: "User's favorite_color is blue, job is engineer"
            attr_parts = [f"{k.replace('_', ' ')} is {v}" for k, v in list(self.user.attributes.items())[:5]]
            if attr_parts:
                parts.append(f"User's {', '.join(attr_parts)}.")
        
        if self.user.relationships:
            # Format: "User's mom is Sarah, friend is Alex"
            rel_parts = [f"{rel} is {name}" for rel, name in list(self.user.relationships.items())[:5]]
            if rel_parts:
                parts.append(f"User's {', '.join(rel_parts)}.")
        
        if self.user.facts:
            # Include up to 3 most recent facts
            facts_str = "; ".join(self.user.facts[-3:])
            parts.append(f"About the user: {facts_str}.")
        
        return " ".join(parts) if parts else ""
    
    def get_user_name(self) -> Optional[str]:
        """Get user's name if known. Instant access."""
        return self.user.name
    
    def get_attribute(self, key: str) -> Optional[str]:
        """Get a specific user attribute. Instant access."""
        return self.user.attributes.get(key.lower())
    
    def clear(self) -> None:
        """Clear all stored entities."""
        self.user = UserEntity(user_id=self.user_id)  # v2.1+: Preserve user_id
        self._save()
        logger.info("EntityMemory cleared")
    
    def shutdown(self) -> None:
        """Gracefully shutdown the background worker."""
        self._shutdown_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        self._save()
    
    def _save(self) -> None:
        """Persist entity data to disk."""
        if not self.persist_path:
            return

        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "name": self.user.name,
                "user_id": self.user.user_id,  # v2.1+: Store user_id
                "attributes": self.user.attributes,
                "relationships": self.user.relationships,
                "facts": self.user.facts,
                "last_updated": self.user.last_updated,
            }
            
            # Atomic write
            temp_path = self.persist_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.persist_path)
            
        except Exception as e:
            logger.error(f"EntityMemory: Failed to save: {e}")
    
    def _load(self) -> None:
        """Load entity data from disk."""
        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            loaded_user_id = data.get("user_id")

            # v2.1+: Multi-user isolation check
            if self.user_id is not None:
                # If we have a user_id, only load if it matches
                if loaded_user_id != self.user_id:
                    logger.info(f"EntityMemory: Loaded data for different user "
                               f"({loaded_user_id} != {self.user_id}), starting fresh")
                    self.user = UserEntity(user_id=self.user_id)
                    return

            self.user = UserEntity(
                name=data.get("name"),
                user_id=loaded_user_id,  # v2.1+: Load user_id
                attributes=data.get("attributes", {}),
                relationships=data.get("relationships", {}),
                facts=data.get("facts", []),
                last_updated=data.get("last_updated", time.time()),
            )

            logger.info(f"EntityMemory: Loaded {len(self.user.attributes)} attributes, "
                       f"{len(self.user.relationships)} relationships, {len(self.user.facts)} facts")
            if self.user_id:
                logger.debug(f"EntityMemory: Loaded for user_id: {self.user_id}")

        except Exception as e:
            logger.warning(f"EntityMemory: Failed to load: {e}")
    
    def __len__(self) -> int:
        """Return total number of stored entities."""
        return (
            (1 if self.user.name else 0) +
            len(self.user.attributes) +
            len(self.user.relationships) +
            len(self.user.facts)
        )
