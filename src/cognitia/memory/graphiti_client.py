"""Graphiti temporal knowledge graph integration."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from .config import settings
from .llm_utils import call_ollama, extract_json_array_from_response

logger = logging.getLogger(__name__)


class GraphitiMemoryClient:
    """Client for managing temporal knowledge graph with Graphiti."""

    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_password: str):
        """Initialize Graphiti client.

        Args:
            neo4j_uri: Neo4j database URI (e.g., "bolt://localhost:7687")
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
        """
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.client = None
        self._driver = None

        try:
            from openai import AsyncOpenAI
            from graphiti_core import Graphiti
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

            # Configure Ollama as the LLM provider using OpenAIGenericClient
            # OpenAIGenericClient works with OpenAI-compatible APIs like Ollama
            llm_config = LLMConfig(
                api_key="ollama",  # Placeholder - Ollama doesn't require a real API key
                model=settings.OLLAMA_MODEL,
                base_url=f"{settings.OLLAMA_URL}/v1",  # Ollama's OpenAI-compatible endpoint
            )
            llm_client = OpenAIGenericClient(config=llm_config)

            # Configure Ollama for embeddings as well
            # Use nomic-embed-text model (available in Ollama)
            ollama_client = AsyncOpenAI(
                api_key="ollama",  # Placeholder for Ollama
                base_url=f"{settings.OLLAMA_URL}/v1",
            )
            embedder_config = OpenAIEmbedderConfig(
                embedding_model="nomic-embed-text:latest",
            )
            embedder = OpenAIEmbedder(config=embedder_config, client=ollama_client)

            # Initialize Graphiti with Neo4j connection, Ollama LLM, and Ollama embeddings
            self.client = Graphiti(
                uri=neo4j_uri,
                user=neo4j_user,
                password=neo4j_password,
                llm_client=llm_client,
                embedder=embedder,
            )

            # Neo4j driver for direct graph export queries.
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                neo4j_uri,
                auth=(neo4j_user, neo4j_password),
            )
            logger.info(f"Graphiti client initialized for {neo4j_uri} with Ollama at {settings.OLLAMA_URL}")
        except Exception as e:
            logger.error(f"Failed to initialize Graphiti client: {e}")
            raise

    async def get_subgraph(
        self,
        group_id: str,
        limit_nodes: int = 200,
        limit_edges: int = 400,
    ) -> Dict[str, Any]:
        """Export a scoped subgraph for UI visualization.

        Graphiti stores data partitioned by a `group_id` (we use `{user_id}_{character_id}`).
        This method queries Neo4j directly and returns a UI-friendly nodes/edges payload.

        Returns:
            {"nodes": [...], "edges": [...]} where node/edge IDs are Neo4j element ids.
        """
        if not self._driver:
            return {"nodes": [], "edges": []}

        # Keep the Cypher flexible about how Graphiti stores the group id.
        cypher = """
        MATCH (n)
        WHERE n.group_id = $group_id OR n.groupId = $group_id OR $group_id IN coalesce(n.group_ids, [])
        WITH n
        LIMIT $limit_nodes
        OPTIONAL MATCH (n)-[r]-(m)
        WHERE (m.group_id = $group_id OR m.groupId = $group_id OR $group_id IN coalesce(m.group_ids, []))
        RETURN n, r, m
        LIMIT $limit_edges
        """

        nodes: Dict[str, Dict[str, Any]] = {}
        edges: Dict[str, Dict[str, Any]] = {}

        async with self._driver.session() as session:
            result = await session.run(
                cypher,
                group_id=group_id,
                limit_nodes=int(limit_nodes),
                limit_edges=int(limit_edges),
            )

            async for record in result:
                n = record.get("n")
                r = record.get("r")
                m = record.get("m")

                if n is not None:
                    node_id = getattr(n, "element_id", None) or str(n.id)
                    if node_id not in nodes:
                        nodes[node_id] = {
                            "id": node_id,
                            "labels": list(getattr(n, "labels", [])),
                            "properties": dict(n),
                        }

                if m is not None:
                    node_id = getattr(m, "element_id", None) or str(m.id)
                    if node_id not in nodes:
                        nodes[node_id] = {
                            "id": node_id,
                            "labels": list(getattr(m, "labels", [])),
                            "properties": dict(m),
                        }

                if r is not None:
                    edge_id = getattr(r, "element_id", None) or str(r.id)
                    if edge_id not in edges:
                        start_id = getattr(r.start_node, "element_id", None) or str(r.start_node.id)
                        end_id = getattr(r.end_node, "element_id", None) or str(r.end_node.id)
                        edges[edge_id] = {
                            "id": edge_id,
                            "type": getattr(r, "type", ""),
                            "source": start_id,
                            "target": end_id,
                            "properties": dict(r),
                        }

        return {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
        }

    async def ingest_conversation(
        self,
        user_id: str,
        character_id: str,
        user_message: str,
        assistant_response: str,
        extracted_facts: List[dict],
        timestamp: datetime,
    ) -> Dict[str, Any]:
        """Ingest conversation and create Person/Relationship nodes.

        Steps:
        1. Extract entities (persons, places, events)
        2. Create/update Person nodes for each entity
        3. Extract relationships between entities
        4. Create relationship edges
        5. Create Episode node for this conversation

        Args:
            user_id: User ID
            character_id: Character ID
            user_message: User's message
            assistant_response: Assistant's response
            extracted_facts: Facts extracted from conversation
            timestamp: Conversation timestamp

        Returns:
            Dict with ingestion results
        """
        logger.info(f"Ingesting conversation for user={user_id}, character={character_id}")

        try:
            # 1. Extract entities (persons, places, events)
            entities = await self._extract_entities(user_message, extracted_facts)

            # 2. Extract relationships between entities
            relationships = await self._extract_relationships(user_message, entities)

            # 3. Create Episode node for this conversation
            # Graphiti will automatically extract entities and relationships from the episode body
            await self.client.add_episode(
                name=f"conversation_{user_id}_{character_id}_{int(timestamp.timestamp())}",
                episode_body=f"User: {user_message}\nAssistant: {assistant_response}",
                source_description=f"Conversation between user {user_id} and character {character_id}",
                reference_time=timestamp,
                group_id=f"{user_id}_{character_id}",  # Separate memory spaces per user-character pair
            )

            entities_created = len(entities)
            relationships_created = len(relationships)

            return {
                "entities_created": entities_created,
                "relationships_created": relationships_created,
                "entities": entities,
                "relationships": relationships,
            }

        except Exception as e:
            logger.error(f"Conversation ingestion failed: {e}")
            raise

    async def retrieve_facts_about_person(
        self, person_name: str, valid_at: datetime
    ) -> List[Dict[str, Any]]:
        """Get all facts about a person at a specific time.

        Args:
            person_name: Name of the person
            valid_at: Timestamp to query (for temporal validity)

        Returns:
            List of facts about the person
        """
        logger.info(f"Retrieving facts about {person_name} at {valid_at}")

        try:
            # Search for episodes related to this person
            results = await self.client.search(
                query=f"Facts about {person_name}",
                num_results=10,
            )

            # Format results into facts
            facts = []
            for result in results:
                # Graphiti returns EntityEdge or EpisodicNode objects
                # Access attributes directly, not with .get()
                content = ""
                if hasattr(result, "fact"):
                    content = result.fact
                elif hasattr(result, "content"):
                    content = result.content
                elif hasattr(result, "episode_body"):
                    content = result.episode_body

                timestamp = valid_at
                if hasattr(result, "created_at") and result.created_at:
                    timestamp = result.created_at

                facts.append({
                    "content": content or "",
                    "source": getattr(result, "name", ""),
                    "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
                    "relevance": 1.0,  # Graphiti doesn't return scores directly
                })

            return facts

        except Exception as e:
            logger.error(f"Fact retrieval failed: {e}")
            raise

    async def get_relationship_history(
        self, person_a: str, person_b: str
    ) -> List[Dict[str, Any]]:
        """Get relationship timeline between two people.

        Args:
            person_a: First person's name
            person_b: Second person's name

        Returns:
            List of relationship events over time
        """
        logger.info(f"Getting relationship history: {person_a} <-> {person_b}")

        try:
            # Search for episodes mentioning both persons
            results = await self.client.search(
                query=f"Relationship between {person_a} and {person_b}",
                num_results=10,
            )

            # Format results into relationship events
            relationship_events = []
            for result in results:
                # Graphiti returns EntityEdge or EpisodicNode objects
                content = ""
                if hasattr(result, "fact"):
                    content = result.fact
                elif hasattr(result, "content"):
                    content = result.content
                elif hasattr(result, "episode_body"):
                    content = result.episode_body

                timestamp = ""
                if hasattr(result, "created_at") and result.created_at:
                    timestamp = result.created_at.isoformat() if hasattr(result.created_at, "isoformat") else str(result.created_at)

                relationship_events.append({
                    "content": content or "",
                    "source": getattr(result, "name", ""),
                    "timestamp": timestamp,
                    "relevance": 1.0,
                })

            return relationship_events

        except Exception as e:
            logger.error(f"Relationship history retrieval failed: {e}")
            raise

    async def _extract_entities(
        self, text: str, extracted_facts: List[dict]
    ) -> List[Dict[str, Any]]:
        """Use LLM to extract named entities.

        Args:
            text: Text to extract entities from
            extracted_facts: Pre-extracted facts from conversation

        Returns:
            List of entities: {name, type, properties}
        """
        logger.debug(f"Extracting entities from: {text[:100]}...")

        # Build entity extraction prompt
        facts_context = json.dumps(extracted_facts[:10], indent=2) if extracted_facts else "[]"

        prompt = f"""Extract named entities from this conversation message.

Message: "{text}"

Pre-extracted facts: {facts_context}

Identify all persons, places, organizations, and events mentioned. Return a JSON array:

[
  {{
    "name": "entity name",
    "type": "person|place|organization|event",
    "properties": {{"description": "brief description", "mentions": ["context where mentioned"]}}
  }}
]

Important:
- For persons: Include the user themselves as an entity if relevant
- For places: Cities, countries, locations
- For events: Births, deaths, meetings, trips
- Return empty array [] if no entities found
- Return ONLY valid JSON, no explanations

JSON array:"""

        try:
            response = await call_ollama(
                prompt=prompt,
                model=settings.OLLAMA_MODEL,
                ollama_url=settings.OLLAMA_URL,
                temperature=0.3,
                response_format="json",
            )

            entities = extract_json_array_from_response(response)
            if entities is None:
                logger.warning("Failed to extract entities, using empty list")
                return []

            logger.info(f"Extracted {len(entities)} entities")
            return entities

        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return []

    async def _extract_relationships(
        self, text: str, entities: List[dict]
    ) -> List[Dict[str, Any]]:
        """Use LLM to extract relationships between entities.

        Args:
            text: Text to extract relationships from
            entities: Previously extracted entities

        Returns:
            List of relationships: {source, target, type, strength}
        """
        logger.debug(f"Extracting relationships from: {text[:100]}...")

        if not entities or len(entities) < 2:
            logger.debug("Not enough entities for relationship extraction")
            return []

        # Build relationship extraction prompt
        entities_list = "\n".join(
            [f"- {e.get('name')} ({e.get('type')})" for e in entities]
        )

        prompt = f"""Extract relationships between entities from this conversation message.

Message: "{text}"

Entities found:
{entities_list}

Identify relationships between these entities. Return a JSON array:

[
  {{
    "source": "entity name 1",
    "target": "entity name 2",
    "type": "relationship type",
    "strength": 0.0-1.0,
    "description": "brief description"
  }}
]

Relationship types: knows, likes, dislikes, works_with, related_to, located_in, attended, owns, etc.

Strength guidelines:
- 0.9-1.0: Very strong (family, close friends, romantic)
- 0.6-0.8: Strong (colleagues, good friends)
- 0.3-0.5: Moderate (acquaintances, casual)
- 0.1-0.2: Weak (mentioned once, distant)

Return empty array [] if no clear relationships found.
Return ONLY valid JSON, no explanations.

JSON array:"""

        try:
            response = await call_ollama(
                prompt=prompt,
                model=settings.OLLAMA_MODEL,
                ollama_url=settings.OLLAMA_URL,
                temperature=0.3,
                response_format="json",
            )

            relationships = extract_json_array_from_response(response)
            if relationships is None:
                logger.warning("Failed to extract relationships, using empty list")
                return []

            logger.info(f"Extracted {len(relationships)} relationships")
            return relationships

        except Exception as e:
            logger.error(f"Relationship extraction failed: {e}")
            return []
