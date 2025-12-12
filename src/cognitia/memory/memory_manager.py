"""
Memory Manager for Cognitia.

This module provides the core memory management functionality including
storage, retrieval, and search capabilities for conversations, knowledge,
and user data.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chromadb
from chromadb.config import Settings
import numpy as np
from sentence_transformers import SentenceTransformer

from .models import (
    ConversationMemory,
    KnowledgeItem,
    MemoryItem,
    MemoryQuery,
    MemoryType,
    TaskItem,
    TaskQuery,
    TaskStatus,
    TaskType,
    UserProfile,
)


class MemoryManager:
    """
    Manages all memory operations for Cognitia including episodic, semantic,
    and procedural memories, plus task management.
    """

    def __init__(
        self,
        persist_directory: Path,
        embedding_model: str = "all-MiniLM-L6-v2",
        collection_name: str = "cognitia_memory"
    ):
        """
        Initialize the memory manager.

        Args:
            persist_directory: Directory to persist ChromaDB data
            embedding_model: Sentence transformer model name
            collection_name: Name of the ChromaDB collection
        """
        self.persist_directory = persist_directory
        self.collection_name = collection_name

        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(persist_directory),
            settings=Settings(anonymized_telemetry=False)
        )

        # Get or create collection
        try:
            self.collection = self.client.get_collection(name=collection_name)
        except ValueError:
            self.collection = self.client.create_collection(name=collection_name)

        # Initialize embedding model (CPU only for Cognitia constraints)
        self.embedding_model = SentenceTransformer(embedding_model, device="cpu")

        # In-memory caches for frequently accessed data
        self._task_cache: Dict[str, TaskItem] = {}
        self._profile_cache: Optional[UserProfile] = None

        # Load cached data
        self._load_task_cache()
        self._load_profile_cache()

    def _load_task_cache(self) -> None:
        """Load active tasks into memory cache."""
        # This would be implemented to load pending/completed tasks
        # For now, we'll implement a simple version
        pass

    def _load_profile_cache(self) -> None:
        """Load user profile into cache."""
        try:
            results = self.collection.get(
                where={"type": "user_profile"},
                limit=1
            )
            if results["documents"]:
                data = json.loads(results["documents"][0])
                self._profile_cache = UserProfile(**data)
        except Exception:
            # Create default profile if none exists
            self._profile_cache = UserProfile()

    def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text using sentence transformer."""
        embedding = self.embedding_model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def _store_memory_item(self, item: MemoryItem) -> None:
        """Store a memory item in the vector database."""
        if item.embedding is None:
            item.embedding = self._generate_embedding(item.content)

        metadata = {
            "type": item.type.value,
            "timestamp": item.timestamp.isoformat(),
            "importance": item.importance,
            "tags": ",".join(item.tags),
            "related_memories": ",".join(item.related_memories),
            **item.metadata
        }

        self.collection.add(
            embeddings=[item.embedding],
            documents=[item.content],
            metadatas=[metadata],
            ids=[item.id]
        )

    def _store_task_item(self, item: TaskItem) -> None:
        """Store a task item in the vector database and cache."""
        # Create searchable content for the task
        content_parts = [item.title]
        if item.description:
            content_parts.append(item.description)
        if item.tags:
            content_parts.extend(item.tags)
        content = " ".join(content_parts)

        embedding = self._generate_embedding(content)

        metadata = {
            "type": "task",
            "task_type": item.type.value,
            "status": item.status.value,
            "priority": item.priority,
            "is_recurring": item.is_recurring,
            "tags": ",".join(item.tags),
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }

        # Add optional datetime fields
        if item.due_date:
            metadata["due_date"] = item.due_date.isoformat()
        if item.reminder_date:
            metadata["reminder_date"] = item.reminder_date.isoformat()
        if item.start_time:
            metadata["start_time"] = item.start_time.isoformat()
        if item.end_time:
            metadata["end_time"] = item.end_time.isoformat()

        # Add to vector DB
        self.collection.add(
            embeddings=[embedding],
            documents=[content],
            metadatas=[metadata],
            ids=[item.id]
        )

        # Update cache
        self._task_cache[item.id] = item

    def add_conversation_memory(
        self,
        user_message: str,
        assistant_response: str,
        conversation_id: str,
        sentiment: Optional[float] = None,
        tags: Optional[List[str]] = None
    ) -> str:
        """
        Add a conversation memory to the system.

        Returns:
            The ID of the created memory item.
        """
        memory = ConversationMemory(
            user_message=user_message,
            assistant_response=assistant_response,
            conversation_id=conversation_id,
            sentiment=sentiment,
            tags=tags or [],
            metadata={"conversation_id": conversation_id}
        )

        self._store_memory_item(memory)
        return memory.id

    def add_knowledge_item(
        self,
        title: str,
        content: str,
        source: str,
        category: str,
        tags: Optional[List[str]] = None,
        confidence: float = 1.0
    ) -> str:
        """
        Add a knowledge item to the system.

        Returns:
            The ID of the created knowledge item.
        """
        knowledge = KnowledgeItem(
            title=title,
            content=content,
            source=source,
            category=category,
            tags=tags or [],
            confidence=confidence
        )

        self._store_memory_item(knowledge)
        return knowledge.id

    def add_task(self, task: TaskItem) -> str:
        """
        Add a task to the system.

        Returns:
            The ID of the created task.
        """
        self._store_task_item(task)
        return task.id

    def search_memories(self, query: MemoryQuery) -> List[Tuple[MemoryItem, float]]:
        """
        Search for memories based on semantic similarity and filters.

        Returns:
            List of (memory_item, similarity_score) tuples.
        """
        query_embedding = self._generate_embedding(query.query)

        # Build where clause for filtering
        where_clause = {}
        if query.memory_type:
            where_clause["type"] = query.memory_type.value
        if query.tags:
            # ChromaDB doesn't support complex tag filtering easily
            # This would need custom implementation
            pass

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=query.limit,
            where=where_clause if where_clause else None
        )

        memories = []
        for i, doc_id in enumerate(results["ids"][0]):
            metadata = results["metadatas"][0][i]
            distance = results["distances"][0][i]

            # Convert distance to similarity score (cosine similarity)
            similarity = 1 - (distance / 2)  # ChromaDB uses cosine distance

            if similarity >= query.min_importance:
                # Reconstruct memory item from metadata
                memory_item = self._reconstruct_memory_from_metadata(doc_id, metadata)
                memories.append((memory_item, similarity))

        return sorted(memories, key=lambda x: x[1], reverse=True)

    def get_tasks(self, query: TaskQuery) -> List[TaskItem]:
        """Retrieve tasks based on query parameters."""
        # For now, return from cache - in production this would query the vector DB
        tasks = list(self._task_cache.values())

        # Apply filters
        if query.task_type:
            tasks = [t for t in tasks if t.type == query.task_type]
        if query.status:
            tasks = [t for t in tasks if t.status == query.status]
        if query.priority_min is not None:
            tasks = [t for t in tasks if t.priority >= query.priority_min]
        if query.priority_max is not None:
            tasks = [t for t in tasks if t.priority <= query.priority_max]

        return tasks[:query.limit]

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """Update a task with new information."""
        if task_id not in self._task_cache:
            return False

        task = self._task_cache[task_id]
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)

        task.updated_at = task.updated_at.__class__.now()  # Update timestamp

        # Re-store in vector DB
        self._store_task_item(task)
        return True

    def get_user_profile(self) -> UserProfile:
        """Get the current user profile."""
        return self._profile_cache or UserProfile()

    def update_user_profile(self, updates: Dict[str, Any]) -> None:
        """Update user profile."""
        if not self._profile_cache:
            self._profile_cache = UserProfile()

        for key, value in updates.items():
            if hasattr(self._profile_cache, key):
                setattr(self._profile_cache, key, value)

        self._profile_cache.updated_at = self._profile_cache.updated_at.__class__.now()

        # Store in vector DB
        content = f"User profile for {self._profile_cache.name or 'user'}"
        embedding = self._generate_embedding(content)

        metadata = {
            "type": "user_profile",
            "updated_at": self._profile_cache.updated_at.isoformat()
        }

        # Remove existing profile and add new one
        try:
            self.collection.delete(where={"type": "user_profile"})
        except Exception:
            pass

        self.collection.add(
            embeddings=[embedding],
            documents=[self._profile_cache.model_dump_json()],
            metadatas=[metadata],
            ids=[self._profile_cache.user_id]
        )

    def _reconstruct_memory_from_metadata(self, doc_id: str, metadata: Dict[str, Any]) -> MemoryItem:
        """Reconstruct a memory item from ChromaDB metadata."""
        # This is a simplified reconstruction - in practice you'd need more robust deserialization
        memory_type = MemoryType(metadata.get("type", "episodic"))

        return MemoryItem(
            id=doc_id,
            type=memory_type,
            content="",  # Would need to be retrieved separately
            metadata=metadata
        )

    def get_memory_stats(self) -> Dict[str, int]:
        """Get statistics about stored memories."""
        # This would query ChromaDB for collection statistics
        return {
            "total_memories": self.collection.count(),
            "episodic": 0,  # Would need to query with filters
            "semantic": 0,
            "procedural": 0,
            "tasks": len(self._task_cache)
        }



