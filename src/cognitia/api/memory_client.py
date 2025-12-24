"""Memory Add-on Service Client for Cognitia API."""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from loguru import logger

# Memory service URL from environment
MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://localhost:8002")


class MemoryClient:
    """Client for communicating with the Memory Add-on Service."""

    def __init__(self, base_url: str = MEMORY_SERVICE_URL):
        """Initialize memory client.

        Args:
            base_url: Base URL of the memory service
        """
        self.base_url = base_url.rstrip("/")
        self._available = None  # Cache availability check

    async def check_health(self) -> bool:
        """Check if memory service is available.

        Returns:
            True if service is healthy or degraded, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status", "")
                    self._available = status in ("healthy", "degraded")
                    return self._available
                return False
        except Exception as e:
            logger.debug(f"Memory service health check failed: {e}")
            self._available = False
            return False

    async def ingest_conversation(
        self,
        user_id: UUID,
        character_id: UUID,
        user_message: str,
        assistant_response: str,
        timestamp: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """Ingest a conversation turn into memory.

        Args:
            user_id: User ID
            character_id: Character ID
            user_message: User's message
            assistant_response: Assistant's response
            timestamp: Conversation timestamp (defaults to now)

        Returns:
            Ingestion response or None if failed
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        payload = {
            "user_id": str(user_id),
            "character_id": str(character_id),
            "user_message": user_message,
            "assistant_response": assistant_response,
            "extracted_facts": [],
            "timestamp": timestamp.isoformat(),
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/ingest",
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Memory ingestion failed: {e}")
            return None

    async def retrieve_context(
        self,
        user_id: UUID,
        character_id: UUID,
        query: Optional[str] = None,
        limit: int = 10,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve memory context for conversation.

        Args:
            user_id: User ID
            character_id: Character ID
            query: Optional query for semantic search
            limit: Maximum number of memories to retrieve

        Returns:
            Retrieval response with context or None if failed
        """
        payload = {
            "user_id": str(user_id),
            "character_id": str(character_id),
            "query": query,
            "limit": limit,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/retrieve",
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Memory retrieval failed: {e}")
            return None

    async def get_persona(
        self,
        user_id: UUID,
        character_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Get distilled persona for user-character pair.

        Args:
            user_id: User ID
            character_id: Character ID

        Returns:
            Memory service persona payload or None if failed
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/persona/{user_id}/{character_id}",
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.debug(f"Persona retrieval failed: {e}")
            return None

    async def distill_persona(
        self,
        user_id: UUID,
        character_id: UUID,
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Trigger persona distillation.

        Args:
            user_id: User ID
            character_id: Character ID
            force: Force distillation even if recent

        Returns:
            Distillation response or None if failed
        """
        payload = {
            "user_id": str(user_id),
            "character_id": str(character_id),
            "force": force,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:  # Longer timeout for LLM
                response = await client.post(
                    f"{self.base_url}/distill",
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Persona distillation failed: {e}")
            return None

    async def delete_persona(
        self,
        user_id: UUID,
        character_id: UUID,
    ) -> bool:
        """Delete persona for user-character pair.

        Args:
            user_id: User ID
            character_id: Character ID

        Returns:
            True if successful, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(
                    f"{self.base_url}/persona/{user_id}/{character_id}",
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Persona deletion failed: {e}")
            return False

    async def get_graph(
        self,
        user_id: UUID,
        character_id: UUID,
        limit_nodes: int = 200,
        limit_edges: int = 400,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a UI-friendly knowledge graph snapshot (nodes + edges)."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/graph/{user_id}/{character_id}",
                    params={"limit_nodes": limit_nodes, "limit_edges": limit_edges},
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.debug(f"Graph retrieval failed: {e}")
            return None

    async def update_graph_node(
        self,
        user_id: UUID,
        character_id: UUID,
        node_id: str,
        name: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update a graph node (name/summary). Empty string removes the property."""
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if summary is not None:
            payload["summary"] = summary
        if not payload:
            return None

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.patch(
                    f"{self.base_url}/graph/{user_id}/{character_id}/nodes/{node_id}",
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.debug(f"Graph node update failed: {e}")
            return None

    async def delete_graph_node(
        self,
        user_id: UUID,
        character_id: UUID,
        node_id: str,
    ) -> bool:
        """Delete a graph node (DETACH DELETE)."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.delete(
                    f"{self.base_url}/graph/{user_id}/{character_id}/nodes/{node_id}",
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.debug(f"Graph node delete failed: {e}")
            return False

    async def delete_graph_edge(
        self,
        user_id: UUID,
        character_id: UUID,
        edge_id: str,
    ) -> bool:
        """Delete a graph edge."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.delete(
                    f"{self.base_url}/graph/{user_id}/{character_id}/edges/{edge_id}",
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.debug(f"Graph edge delete failed: {e}")
            return False


# Global memory client instance
memory_client = MemoryClient()
