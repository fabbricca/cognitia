"""Qdrant vector database integration for episodic memory."""

import logging
from datetime import datetime
from typing import Any, Dict, List
import uuid

logger = logging.getLogger(__name__)


class QdrantMemoryClient:
    """Client for managing episodic memory with Qdrant vector database."""

    def __init__(self, url: str, collection_name: str, embedding_model: str):
        """Initialize Qdrant client.

        Args:
            url: Qdrant server URL (e.g., "http://localhost:6333")
            collection_name: Name of the collection to use
            embedding_model: SentenceTransformer model name
        """
        self.url = url
        self.collection_name = collection_name
        self.embedding_model_name = embedding_model
        self.client = None
        self.encoder = None

        try:
            from qdrant_client import QdrantClient
            from fastembed import TextEmbedding

            self.client = QdrantClient(url=url)
            self.encoder = TextEmbedding(model_name=embedding_model)

            # Create collection if not exists
            self._ensure_collection()

            logger.info(
                f"Qdrant client initialized for {url}, collection={collection_name}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client: {e}")
            raise

    def _ensure_collection(self):
        """Create Qdrant collection for episodic memory if it doesn't exist."""
        from qdrant_client.models import Distance, VectorParams

        collections = self.client.get_collections().collections
        if self.collection_name not in [c.name for c in collections]:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=384,  # BAAI/bge-small-en-v1.5 embedding size
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Created collection: {self.collection_name}")

    async def ingest_episode(
        self,
        episode_id: str,
        user_id: str,
        character_id: str,
        user_message: str,
        assistant_response: str,
        timestamp: datetime,
        emotional_tone: str,
        salience_score: float,
    ) -> str:
        """Store conversation episode with embedding.

        Steps:
        1. Create episode summary
        2. Generate embedding
        3. Store in Qdrant with metadata

        Args:
            episode_id: Unique episode ID
            user_id: User ID
            character_id: Character ID
            user_message: User's message
            assistant_response: Assistant's response
            timestamp: Episode timestamp
            emotional_tone: Detected emotional tone
            salience_score: Importance score (0.0-1.0)

        Returns:
            Episode ID
        """
        logger.info(f"Ingesting episode {episode_id} for user={user_id}, character={character_id}")

        try:
            from qdrant_client.models import PointStruct
            from datetime import timezone

            # 1. Create episode summary
            episode_text = f"User: {user_message}\nAI: {assistant_response}"

            # 2. Generate embedding (FastEmbed returns generator, get first result)
            embedding = list(self.encoder.embed([episode_text]))[0].tolist()

            # 3. Ensure timestamp is timezone-aware
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            # 4. Store in Qdrant with metadata
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=episode_id,
                        vector=embedding,
                        payload={
                            "user_id": user_id,
                            "character_id": character_id,
                            "user_message": user_message,
                            "assistant_response": assistant_response,
                            "timestamp": timestamp.isoformat(),
                            "emotional_tone": emotional_tone,
                            "salience_score": salience_score,
                        },
                    )
                ],
            )

            logger.debug(f"Episode {episode_id} stored successfully")
            return episode_id

        except Exception as e:
            logger.error(f"Episode ingestion failed: {e}")
            raise

    async def search_episodes(
        self,
        user_id: str,
        character_id: str,
        query: str,
        limit: int = 10,
        min_salience: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """Semantic search for relevant episodes.

        Steps:
        1. Embed query
        2. Search with filters (user_id, character_id, salience)
        3. Apply recency decay to scores
        4. Re-sort by combined score

        Args:
            user_id: User ID
            character_id: Character ID
            query: Search query
            limit: Maximum results to return
            min_salience: Minimum salience threshold

        Returns:
            List of scored episodes
        """
        logger.info(
            f"Searching episodes for user={user_id}, character={character_id}, query={query[:50]}"
        )

        try:
            from qdrant_client.models import Filter, FieldCondition, Range, MatchValue
            import math

            # 1. Embed query (FastEmbed returns generator)
            query_embedding = list(self.encoder.embed([query]))[0].tolist()

            # 2. Search with filters
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                query_filter=Filter(
                    must=[
                        FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                        FieldCondition(key="character_id", match=MatchValue(value=character_id)),
                        FieldCondition(
                            key="salience_score",
                            range=Range(gte=min_salience),
                        ),
                    ]
                ),
                limit=limit * 2,  # Get more results for re-ranking
            )

            # 3. Apply recency decay to scores
            scored_results = []
            from datetime import timezone
            now = datetime.now(timezone.utc)

            for result in results:
                timestamp_str = result.payload["timestamp"]
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

                # Ensure timestamp is timezone-aware
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)

                days_old = (now - timestamp).days

                # Recency decay: weight = exp(-(days_old) / T)
                recency_weight = math.exp(-days_old / 30)  # T=30 days

                # Combined score
                combined_score = (
                    result.score * 0.5  # Semantic similarity
                    + result.payload["salience_score"] * 0.3  # Importance
                    + recency_weight * 0.2  # Recency
                )

                scored_results.append({
                    "episode_id": result.id,
                    "score": combined_score,
                    "user_message": result.payload["user_message"],
                    "assistant_response": result.payload["assistant_response"],
                    "timestamp": timestamp,
                    "emotional_tone": result.payload["emotional_tone"],
                    "salience_score": result.payload["salience_score"],
                })

            # 4. Re-sort by combined score
            scored_results.sort(key=lambda x: x["score"], reverse=True)
            return scored_results[:limit]

        except Exception as e:
            logger.error(f"Episode search failed: {e}")
            raise

    async def delete_old_episodes(self, older_than_days: int, min_salience: float = 0.3) -> int:
        """Delete low-salience episodes older than specified days.

        Args:
            older_than_days: Delete episodes older than this
            min_salience: Only delete episodes below this salience

        Returns:
            Number of episodes deleted
        """
        logger.info(f"Deleting episodes older than {older_than_days} days with salience < {min_salience}")

        try:
            from datetime import timedelta, timezone

            from qdrant_client.models import Filter, FieldCondition, Range

            cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
            deleted_count = 0

            next_offset = None
            while True:
                points, next_offset = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="salience_score",
                                range=Range(lt=min_salience),
                            )
                        ]
                    ),
                    limit=256,
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=False,
                )

                if not points:
                    break

                ids_to_delete = []
                for point in points:
                    payload = getattr(point, "payload", None) or {}
                    timestamp_str = payload.get("timestamp")
                    if not timestamp_str:
                        continue

                    try:
                        parsed = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                    except Exception:
                        continue

                    if parsed < cutoff:
                        ids_to_delete.append(point.id)

                if ids_to_delete:
                    self.client.delete(
                        collection_name=self.collection_name,
                        points_selector=ids_to_delete,
                    )
                    deleted_count += len(ids_to_delete)

                if next_offset is None:
                    break

            logger.info(f"Deleted {deleted_count} old episodes")
            return deleted_count

        except Exception as e:
            logger.error(f"Episode deletion failed: {e}")
            raise
