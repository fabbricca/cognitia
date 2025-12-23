"""Background tasks for memory management."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List

from celery_app import app
from config import settings

logger = logging.getLogger(__name__)


@app.task(name="celery_app.auto_distill_personas")
def auto_distill_personas():
    """Automatically distill personas for active users.

    Runs every 6 hours to update personas based on recent conversations.
    Only updates personas that have had significant conversation activity.
    """
    logger.info("Starting automatic persona distillation...")

    try:
        # Import here to avoid circular dependencies
        from graphiti_client import GraphitiMemoryClient
        from qdrant_memory import QdrantMemoryClient
        from persona_store import PersonaStore

        # Initialize clients
        graphiti_client = GraphitiMemoryClient(
            neo4j_uri=settings.NEO4J_URI,
            neo4j_user=settings.NEO4J_USER,
            neo4j_password=settings.NEO4J_PASSWORD,
        )
        qdrant_client = QdrantMemoryClient(
            url=settings.QDRANT_URL,
            collection_name=settings.QDRANT_COLLECTION,
            embedding_model=settings.EMBEDDING_MODEL,
        )
        persona_store = PersonaStore(storage_dir=settings.PERSONA_STORAGE_DIR)

        # Get active user-character pairs (those with recent conversations)
        # This would typically query your database for active pairs
        # For now, we'll use a placeholder
        active_pairs = _get_active_user_character_pairs()

        distilled_count = 0
        for user_id, character_id in active_pairs:
            try:
                # Run async persona distillation
                persona = asyncio.run(
                    persona_store.distill_persona(
                        user_id=user_id,
                        character_id=character_id,
                        graphiti_client=graphiti_client,
                        qdrant_client=qdrant_client,
                    )
                )
                distilled_count += 1
                logger.info(f"Distilled persona for user={user_id}, character={character_id}")
            except Exception as e:
                logger.error(f"Failed to distill persona for user={user_id}, character={character_id}: {e}")

        logger.info(f"Automatic persona distillation complete. Distilled {distilled_count} personas.")
        return {"success": True, "distilled_count": distilled_count}

    except Exception as e:
        logger.error(f"Automatic persona distillation failed: {e}")
        return {"success": False, "error": str(e)}


@app.task(name="celery_app.prune_old_memories")
def prune_old_memories(days: int = 180, min_salience: float = 0.3):
    """Prune old, low-salience memories.

    Args:
        days: Remove memories older than this many days
        min_salience: Only remove memories with salience below this threshold
    """
    logger.info(f"Starting memory pruning (days={days}, min_salience={min_salience})...")

    try:
        # Import here to avoid circular dependencies
        from qdrant_memory import QdrantMemoryClient

        # Initialize Qdrant client
        qdrant_client = QdrantMemoryClient(
            url=settings.QDRANT_URL,
            collection_name=settings.QDRANT_COLLECTION,
            embedding_model=settings.EMBEDDING_MODEL,
        )

        # Calculate cutoff date
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        # Prune episodes from Qdrant
        # This would use Qdrant's delete with filter functionality
        episodes_pruned = asyncio.run(
            _prune_qdrant_episodes(
                qdrant_client=qdrant_client,
                cutoff_date=cutoff_date,
                min_salience=min_salience,
            )
        )

        logger.info(f"Memory pruning complete. Pruned {episodes_pruned} episodes.")
        return {"success": True, "episodes_pruned": episodes_pruned}

    except Exception as e:
        logger.error(f"Memory pruning failed: {e}")
        return {"success": False, "error": str(e)}


@app.task(name="celery_app.distill_persona_for_user")
def distill_persona_for_user(user_id: str, character_id: str, force: bool = False):
    """Distill persona for a specific user-character pair.

    This task can be triggered manually or by the API when a threshold
    of new messages is reached (e.g., every 50 messages).

    Args:
        user_id: User ID
        character_id: Character ID
        force: Force distillation even if recently updated
    """
    logger.info(f"Distilling persona for user={user_id}, character={character_id}, force={force}")

    try:
        # Import here to avoid circular dependencies
        from graphiti_client import GraphitiMemoryClient
        from qdrant_memory import QdrantMemoryClient
        from persona_store import PersonaStore

        # Initialize clients
        graphiti_client = GraphitiMemoryClient(
            neo4j_uri=settings.NEO4J_URI,
            neo4j_user=settings.NEO4J_USER,
            neo4j_password=settings.NEO4J_PASSWORD,
        )
        qdrant_client = QdrantMemoryClient(
            url=settings.QDRANT_URL,
            collection_name=settings.QDRANT_COLLECTION,
            embedding_model=settings.EMBEDDING_MODEL,
        )
        persona_store = PersonaStore(storage_dir=settings.PERSONA_STORAGE_DIR)

        # Run async persona distillation
        persona = asyncio.run(
            persona_store.distill_persona(
                user_id=user_id,
                character_id=character_id,
                graphiti_client=graphiti_client,
                qdrant_client=qdrant_client,
            )
        )

        logger.info(f"Persona distillation complete for user={user_id}, character={character_id}")
        return {
            "success": True,
            "user_id": user_id,
            "character_id": character_id,
            "persona": persona,
        }

    except Exception as e:
        logger.error(f"Persona distillation failed for user={user_id}, character={character_id}: {e}")
        return {"success": False, "error": str(e)}


def _get_active_user_character_pairs() -> List[tuple]:
    """Get list of active user-character pairs that need persona distillation.

    Returns:
        List of (user_id, character_id) tuples
    """
    # TODO: Query the main database for user-character pairs with:
    # - Messages in the last 24 hours
    # - OR personas not updated in the last 7 days
    # - OR message count threshold reached (e.g., 50 new messages)

    # For now, return empty list (this will be integrated with main API database)
    return []


async def _prune_qdrant_episodes(
    qdrant_client,
    cutoff_date: datetime,
    min_salience: float,
) -> int:
    """Prune old episodes from Qdrant.

    Args:
        qdrant_client: QdrantMemoryClient instance
        cutoff_date: Remove episodes older than this date
        min_salience: Only remove episodes with salience below this threshold

    Returns:
        Number of episodes pruned
    """
    from qdrant_client.models import Filter, FieldCondition, Range

    # TODO: Implement actual pruning using Qdrant delete with filter
    # This would use qdrant_client.client.delete() with a filter like:
    # filter = Filter(
    #     must=[
    #         FieldCondition(
    #             key="created_at",
    #             range=Range(lt=cutoff_date.isoformat())
    #         ),
    #         FieldCondition(
    #             key="salience_score",
    #             range=Range(lt=min_salience)
    #         )
    #     ]
    # )

    # For now, return 0 (not implemented)
    logger.info(f"Pruning episodes older than {cutoff_date} with salience < {min_salience}")
    return 0
