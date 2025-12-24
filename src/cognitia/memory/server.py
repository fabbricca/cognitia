"""FastAPI server for Cognitia Memory Add-on Service."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .models import (
    DistillRequest,
    DistillResponse,
    GraphResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    PersonaDeleteResponse,
    PersonaGetResponse,
    PersonRequest,
    PersonResponse,
    PruneRequest,
    PruneResponse,
    RetrieveRequest,
    RetrieveResponse,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global clients (initialized on startup)
graphiti_client: Optional[Any] = None
qdrant_client: Optional[Any] = None
persona_store: Optional[Any] = None
neo4j_driver: Optional[Any] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI app."""
    global graphiti_client, qdrant_client, persona_store, neo4j_driver

    logger.info("Initializing Memory Add-on Service...")

    # Initialize clients
    try:
        # Import here to avoid circular dependencies
        from .qdrant_memory import QdrantMemoryClient
        from .persona_store import PersonaStore

        # Initialize raw Neo4j driver for graph export (optional).
        # This should work even if Graphiti/LLM init fails.
        try:
            from neo4j import AsyncGraphDatabase

            logger.info(f"Connecting to Neo4j at {settings.NEO4J_URI}...")
            neo4j_driver = AsyncGraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            )
            logger.info("Neo4j async driver initialized")
        except Exception as e:
            logger.warning(f"Neo4j driver initialization failed (optional): {e}")
            neo4j_driver = None

        # Initialize Graphiti (optional - depends on Graphiti + Ollama/OpenAI-compatible endpoint)
        try:
            from .graphiti_client import GraphitiMemoryClient

            graphiti_client = GraphitiMemoryClient(
                neo4j_uri=settings.NEO4J_URI,
                neo4j_user=settings.NEO4J_USER,
                neo4j_password=settings.NEO4J_PASSWORD,
            )
            logger.info("Graphiti client initialized")
        except Exception as e:
            logger.warning(f"Graphiti initialization failed (optional): {e}")
            logger.warning("Continuing without Graphiti - only Qdrant and PersonaMem will be available")
            graphiti_client = None

        # Initialize Qdrant (required)
        logger.info(f"Connecting to Qdrant at {settings.QDRANT_URL}...")
        qdrant_client = QdrantMemoryClient(
            url=settings.QDRANT_URL,
            collection_name=settings.QDRANT_COLLECTION,
            embedding_model=settings.EMBEDDING_MODEL,
        )
        logger.info("Qdrant client initialized")

        # Initialize Persona Store (required)
        logger.info(f"Initializing Persona Store at {settings.PERSONA_STORAGE_DIR}...")
        persona_store = PersonaStore(storage_dir=settings.PERSONA_STORAGE_DIR)
        logger.info("Persona Store initialized")

        logger.info("Memory Add-on Service initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize Memory Add-on Service: {e}")
        raise

    yield

    # Cleanup on shutdown
    logger.info("Shutting down Memory Add-on Service...")
    try:
        if neo4j_driver is not None:
            await neo4j_driver.close()
    except Exception:
        pass


# Create FastAPI app
app = FastAPI(
    title="Cognitia Memory Add-on",
    description="Temporal knowledge graph + episodic memory + persona modeling for AI companions",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    try:
        # Check connections
        graphiti_ok = graphiti_client is not None
        qdrant_ok = qdrant_client is not None
        ollama_ok = False
        try:
            import httpx

            async with httpx.AsyncClient(timeout=2.5) as client:
                # Ollama supports /api/tags even without a model loaded.
                response = await client.get(f"{settings.OLLAMA_URL}/api/tags")
                ollama_ok = response.status_code == 200
        except Exception:
            ollama_ok = False

        if not (graphiti_ok and qdrant_ok):
            return HealthResponse(
                status="degraded",
                graphiti_connected=graphiti_ok,
                qdrant_connected=qdrant_ok,
                ollama_available=ollama_ok,
            )

        return HealthResponse(
            status="healthy",
            graphiti_connected=graphiti_ok,
            qdrant_connected=qdrant_ok,
            ollama_available=ollama_ok,
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            graphiti_connected=False,
            qdrant_connected=False,
            ollama_available=False,
        )


@app.post("/ingest", response_model=IngestResponse)
async def ingest_conversation(request: IngestRequest):
    """Ingest conversation turn and extract memory.

    Steps:
    1. Extract facts and emotional tone from conversation
    2. Write to Graphiti knowledge graph (if available)
    3. Embed conversation and store in Qdrant
    4. Return ingestion results
    """
    try:
        logger.info(
            f"Ingesting conversation for user={request.user_id}, character={request.character_id}"
        )

        # 1. Extract facts and emotional context from conversation
        from llm_utils import call_ollama, extract_json_from_response
        import uuid

        extraction_prompt = f'''Extract facts and emotional context from this conversation exchange.

User: "{request.user_message}"
AI: "{request.assistant_response}"

Return JSON with:
{{
  "facts": [
    {{"key": "...", "value": "...", "category": "personal|preference|relationship|event"}},
    ...
  ],
  "emotional_tone": "happy|sad|excited|neutral|...",
  "salience_score": 0.0-1.0,
  "user_name": "name if mentioned, else null"
}}

Focus on:
- Personal information the user revealed
- Preferences, likes, dislikes
- Relationships with people
- Important events or experiences
- Extract user's name if they introduce themselves

Return ONLY valid JSON:'''

        extraction = None
        llm_error: Optional[str] = None
        try:
            response_text = await call_ollama(
                prompt=extraction_prompt,
                model=settings.OLLAMA_MODEL,
                ollama_url=settings.OLLAMA_URL,
                temperature=0.3,
                timeout=15.0,
            )
            extraction = extract_json_from_response(response_text)
        except Exception as e:
            # Ollama connectivity is environment-dependent (GPU server / in-cluster routing).
            # Do not hard-fail ingestion if LLM is temporarily unavailable.
            llm_error = str(e)
            logger.warning(f"Ollama unavailable during ingestion; continuing without extraction: {e}")

        if not extraction:
            logger.info("No LLM extraction available; using request.extracted_facts (if any) and defaults")
            extraction = {}

        # Prefer extracted facts from the LLM, but allow upstream callers (Entrance) to supply facts.
        facts = extraction.get("facts") or request.extracted_facts or []
        emotional_tone = extraction.get("emotional_tone", "neutral")

        # If we didn't run extraction, keep salience conservative so we don't store every turn.
        try:
            salience_score = float(extraction.get("salience_score", 0.0))
        except Exception:
            salience_score = 0.0

        user_name = extraction.get("user_name")

        logger.info(f"Extracted {len(facts)} facts, tone={emotional_tone}, salience={salience_score}")

        # Decide whether this turn is worth persisting.
        # Goal: keep high-signal facts/entities, avoid storing every exchange verbatim.
        should_persist = (len(facts) >= settings.MIN_FACTS_FOR_STORAGE) or (
            salience_score >= settings.MIN_EPISODE_SALIENCE_TO_STORE
        )

        # 2. Store in Graphiti knowledge graph (if available)
        entities_created = 0
        relationships_created = 0

        if graphiti_client and should_persist:
            try:
                result = await graphiti_client.ingest_conversation(
                    user_id=str(request.user_id),
                    character_id=str(request.character_id),
                    user_message=request.user_message,
                    assistant_response=request.assistant_response,
                    extracted_facts=facts,
                    timestamp=request.timestamp or datetime.utcnow(),
                )
                entities_created = result.get("entities_created", 0)
                relationships_created = result.get("relationships_created", 0)
                logger.info(f"Graphiti: {entities_created} entities, {relationships_created} relationships")
            except Exception as e:
                logger.warning(f"Graphiti ingestion failed (non-critical): {e}")

        # 3. Store episode in Qdrant (only if worth persisting)
        episode_id = None

        if qdrant_client and should_persist:
            episode_id = str(uuid.uuid4())
            try:
                await qdrant_client.ingest_episode(
                    episode_id=episode_id,
                    user_id=str(request.user_id),
                    character_id=str(request.character_id),
                    user_message=request.user_message,
                    assistant_response=request.assistant_response,
                    timestamp=request.timestamp or datetime.utcnow(),
                    emotional_tone=emotional_tone,
                    salience_score=salience_score,
                )
                logger.info(f"Qdrant: Episode {episode_id} stored")
            except Exception as e:
                logger.warning(f"Qdrant ingestion failed (non-critical): {e}")

        return IngestResponse(
            success=True,
            entities_created=entities_created,
            relationships_created=relationships_created,
            episode_id=episode_id,
            salience_score=salience_score,
            status=(
                (
                    f"Stored ({len(facts)} facts, salience={salience_score:.2f})"
                    if should_persist
                    else f"Skipped storage (low-signal: {len(facts)} facts, salience={salience_score:.2f})"
                )
                + (
                    " (LLM unavailable)"
                    if llm_error is not None
                    else ""
                )
            ),
        )

    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Ingestion failed: {str(e)}"
        )


@app.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_memory(request: RetrieveRequest):
    """Retrieve relevant memory for conversation context.

    Steps:
    1. Query Qdrant for semantically relevant episodes
    2. Query Graphiti for facts about mentioned persons (if available)
    3. Load persona summary if available
    4. Combine and format context
    5. Return memory context block
    """
    try:
        logger.info(
            f"Retrieving memory for user={request.user_id}, character={request.character_id}, query={request.query[:50] if request.query else 'None'}"
        )

        memories = []
        context_parts = []

        # 1. Query Qdrant for relevant episodes
        if qdrant_client:
            try:
                # If query is empty, use a generic query to retrieve recent episodes
                query_text = request.query if request.query else "recent conversation history"

                episodes = await qdrant_client.search_episodes(
                    user_id=str(request.user_id),
                    character_id=str(request.character_id),
                    query=query_text,
                    limit=request.limit or 5,
                    min_salience=0.3,
                )

                for episode in episodes:
                    memories.append({
                        "type": "episode",
                        "content": f"User: {episode['user_message']}\nAI: {episode['assistant_response']}",
                        "timestamp": episode["timestamp"].isoformat(),
                        "score": episode["score"],
                        "emotional_tone": episode.get("emotional_tone", "neutral"),
                    })

                if episodes:
                    context_parts.append("## Recent Relevant Conversations")
                    for i, episode in enumerate(episodes[:3], 1):
                        context_parts.append(
                            f"{i}. [{episode['timestamp'].strftime('%Y-%m-%d')}] "
                            f"User said: \"{episode['user_message'][:100]}...\""
                        )

                logger.info(f"Qdrant: Retrieved {len(episodes)} relevant episodes")

            except Exception as e:
                logger.warning(f"Qdrant retrieval failed (non-critical): {e}")

        # 2. Query Graphiti for facts if query mentions persons (if available)
        if graphiti_client and request.query:
            try:
                # Simple entity detection - look for capitalized words that might be names
                import re
                potential_names = re.findall(r'\b[A-Z][a-z]+\b', request.query)

                if potential_names:
                    for name in potential_names[:2]:  # Limit to 2 names
                        facts = await graphiti_client.retrieve_facts_about_person(
                            person_name=name,
                            valid_at=datetime.utcnow(),
                        )

                        if facts:
                            context_parts.append(f"\n## Facts about {name}")
                            for fact in facts[:3]:
                                context_parts.append(f"- {fact['content'][:150]}")

                            for fact in facts:
                                memories.append({
                                    "type": "fact",
                                    "content": fact["content"],
                                    "timestamp": fact.get("timestamp"),
                                    "score": fact.get("relevance", 0.5),
                                    "source": fact.get("source", "knowledge_graph"),
                                })

                    logger.info(f"Graphiti: Retrieved facts for {len(potential_names)} potential entities")

            except Exception as e:
                logger.warning(f"Graphiti retrieval failed (non-critical): {e}")

        # 3. Load persona summary if available
        persona_summary = None
        if persona_store:
            try:
                persona = await persona_store.get_persona(
                    user_id=str(request.user_id),
                    character_id=str(request.character_id),
                )

                if persona:
                    persona_summary = persona.get("summary", "")
                    if persona_summary:
                        context_parts.insert(0, f"## User Profile\n{persona_summary}\n")
                        logger.info(f"Persona: Loaded summary ({len(persona_summary)} chars)")

            except Exception as e:
                logger.warning(f"Persona loading failed (non-critical): {e}")

        # 4. Combine context
        context = "\n".join(context_parts) if context_parts else ""

        # 5. Estimate token count (rough approximation: 1 token ≈ 4 characters)
        total_tokens = len(context) // 4

        logger.info(f"Retrieved {len(memories)} memories, context length={len(context)} chars (~{total_tokens} tokens)")

        return RetrieveResponse(
            context=context,
            memories=memories,
            persona_summary=persona_summary,
            total_tokens=total_tokens,
        )

    except Exception as e:
        logger.error(f"Retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Retrieval failed: {str(e)}"
        )


@app.get("/person/{person_id}", response_model=PersonResponse)
async def get_person(person_id: str, user_id: str, character_id: str):
    """Get Person object and relationships from knowledge graph."""
    try:
        logger.info(f"Getting person={person_id} for user={user_id}, character={character_id}")

        # Query Graphiti for person information
        if graphiti_client:
            try:
                # Get facts about this person
                facts = await graphiti_client.retrieve_facts_about_person(
                    person_name=person_id,
                    valid_at=datetime.utcnow(),
                )

                # Get relationship history
                relationships = await graphiti_client.get_relationship_history(
                    person_a=user_id,
                    person_b=person_id,
                )

                # Extract properties from facts
                properties = {}
                for fact in facts:
                    properties[fact.get("source", "unknown")] = fact.get("content", "")

                # Format relationships
                formatted_relationships = []
                for rel in relationships:
                    formatted_relationships.append({
                        "type": "related_to",
                        "target": person_id,
                        "description": rel.get("content", ""),
                        "timestamp": rel.get("timestamp", ""),
                    })

                logger.info(f"Person retrieval: {len(facts)} facts, {len(relationships)} relationships")

                return PersonResponse(
                    name=person_id,
                    entity_type="person",
                    properties=properties,
                    relationships=formatted_relationships,
                )

            except Exception as e:
                logger.warning(f"Graphiti person retrieval failed: {e}")
                # Return minimal response on error
                return PersonResponse(
                    name=person_id,
                    entity_type="person",
                    properties={"error": str(e)},
                    relationships=[],
                )
        else:
            # Graphiti not available
            return PersonResponse(
                name=person_id,
                entity_type="person",
                properties={"note": "Knowledge graph not available"},
                relationships=[],
            )

    except Exception as e:
        logger.error(f"Person retrieval failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Person retrieval failed: {str(e)}",
        )


@app.get("/graph/{user_id}/{character_id}", response_model=GraphResponse)
async def get_graph(user_id: str, character_id: str, limit_nodes: int = 200, limit_edges: int = 400):
    """Export a UI-friendly subgraph for this user-character pair.

    This is intended for visualization/debugging in the web UI.
    """
    group_id = f"{user_id}_{character_id}"

    if neo4j_driver is None:
        return GraphResponse(
            available=False,
            group_id=group_id,
            nodes=[],
            edges=[],
        )

    limit_nodes = max(1, min(2000, int(limit_nodes)))
    limit_edges = max(1, min(5000, int(limit_edges)))

    cypher = """
    MATCH (n)
    WHERE n.group_id = $group_id
       OR n.groupId = $group_id
       OR $group_id IN coalesce(n.group_ids, [])
       OR $group_id IN coalesce(n.groupIds, [])
    WITH n LIMIT $limit_nodes
    WITH collect(DISTINCT n) AS ns
    CALL {
      WITH ns
      UNWIND ns AS n
      MATCH (n)-[r]-(m)
      WHERE m.group_id = $group_id
         OR m.groupId = $group_id
         OR $group_id IN coalesce(m.group_ids, [])
         OR $group_id IN coalesce(m.groupIds, [])
      RETURN DISTINCT r LIMIT $limit_edges
    }
    WITH ns, collect(DISTINCT r) AS rs
    RETURN
      [n IN ns | {id: elementId(n), labels: labels(n), properties: properties(n)}] AS nodes,
      [r IN rs | {id: elementId(r), type: type(r), source: elementId(startNode(r)), target: elementId(endNode(r)), properties: properties(r)}] AS edges
    """

    try:
        async with neo4j_driver.session() as session:
            result = await session.run(
                cypher,
                group_id=group_id,
                limit_nodes=limit_nodes,
                limit_edges=limit_edges,
            )
            record = await result.single()

        nodes = record.get("nodes", []) if record else []
        edges = record.get("edges", []) if record else []
        return GraphResponse(
            available=True,
            group_id=group_id,
            nodes=nodes,
            edges=edges,
        )
    except Exception as e:
        logger.warning(f"Graph export failed (non-critical): {e}")
        return GraphResponse(
            available=False,
            group_id=group_id,
            nodes=[],
            edges=[],
        )


@app.post("/distill", response_model=DistillResponse)
async def distill_persona(request: DistillRequest):
    """Trigger persona distillation for user."""
    try:
        logger.info(f"Distilling persona for user={request.user_id}, character={request.character_id}")

        # Require at least Qdrant and PersonaStore (Graphiti is optional)
        if not (qdrant_client and persona_store):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Memory services not initialized (Qdrant or PersonaStore missing)",
            )

        # Distill persona using PersonaStore.
        # Distillation depends on Ollama; failures should not crash the service.
        try:
            persona = await persona_store.distill_persona(
                user_id=request.user_id,
                character_id=request.character_id,
                graphiti_client=graphiti_client,
                qdrant_client=qdrant_client,
            )
        except Exception as e:
            logger.warning(f"Persona distillation failed (non-fatal): {e}")
            return DistillResponse(
                success=False,
                persona={"error": str(e)},
                facts_processed=0,
                episodes_processed=0,
                token_count=0,
            )

        # Count facts and episodes (from saved metadata)
        persona_data_path = persona_store._get_persona_path(request.user_id, request.character_id)
        import json

        with open(persona_data_path, "r") as f:
            saved_data = json.load(f)
            facts_processed = saved_data.get("facts_used", 0)
            episodes_processed = saved_data.get("episodes_used", 0)

        # Estimate token count (rough approximation: ~0.75 tokens per character)
        persona_str = json.dumps(persona)
        token_count = int(len(persona_str) * 0.75)

        logger.info(
            f"Persona distilled successfully: {facts_processed} facts, "
            f"{episodes_processed} episodes, ~{token_count} tokens"
        )

        return DistillResponse(
            success=True,
            persona=persona,
            facts_processed=facts_processed,
            episodes_processed=episodes_processed,
            token_count=token_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Persona distillation failed: {e}")
        return DistillResponse(
            success=False,
            persona={"error": str(e)},
            facts_processed=0,
            episodes_processed=0,
            token_count=0,
        )


@app.get("/persona/{user_id}/{character_id}", response_model=PersonaGetResponse)
async def get_persona(user_id: str, character_id: str):
    """Get distilled persona for user-character pair."""
    try:
        logger.info(f"Getting persona for user={user_id}, character={character_id}")

        if not persona_store:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Persona store not initialized",
            )

        # Get persona data
        persona_data_path = persona_store._get_persona_path(user_id, character_id)
        import json
        import os

        if not os.path.exists(persona_data_path):
            return PersonaGetResponse(
                exists=False, persona=None, updated_at=None, version=None
            )

        with open(persona_data_path, "r") as f:
            saved_data = json.load(f)

        return PersonaGetResponse(
            exists=True,
            persona=saved_data.get("persona"),
            updated_at=saved_data.get("updated_at"),
            version=saved_data.get("version"),
        )

    except Exception as e:
        logger.error(f"Get persona failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Get persona failed: {str(e)}",
        )


@app.delete("/persona/{user_id}/{character_id}", response_model=PersonaDeleteResponse)
async def delete_persona(user_id: str, character_id: str):
    """Delete persona for user-character pair."""
    try:
        logger.info(f"Deleting persona for user={user_id}, character={character_id}")

        if not persona_store:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Persona store not initialized",
            )

        # Delete persona
        existed = await persona_store.delete_persona(user_id, character_id)

        return PersonaDeleteResponse(success=True, existed=existed)

    except Exception as e:
        logger.error(f"Delete persona failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Delete persona failed: {str(e)}",
        )


@app.post("/admin/prune", response_model=PruneResponse)
async def prune_old_memories(request: PruneRequest):
    """Remove very old, low-salience memories."""
    try:
        logger.info(f"Pruning memories older than {request.days} days with salience < {request.min_salience}")

        if not qdrant_client:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Qdrant client not initialized",
            )

        episodes_pruned = await qdrant_client.delete_old_episodes(
            older_than_days=int(request.days),
            min_salience=float(request.min_salience),
        )

        return PruneResponse(success=True, episodes_pruned=int(episodes_pruned), entities_pruned=0)

    except Exception as e:
        logger.error(f"Memory pruning failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Pruning failed: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
