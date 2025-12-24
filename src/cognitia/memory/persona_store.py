"""PersonaMem-style distilled user persona storage."""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from .config import settings
from .llm_utils import call_ollama, extract_json_from_response

logger = logging.getLogger(__name__)


class PersonaStore:
    """Manage distilled user persona profiles."""

    def __init__(self, storage_dir: str = "./personas"):
        """Initialize persona store.

        Args:
            storage_dir: Directory to store persona JSON files
        """
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
        logger.info(f"Persona store initialized at {storage_dir}")

    async def distill_persona(
        self,
        user_id: str,
        character_id: str,
        graphiti_client,
        qdrant_client,
    ) -> Dict[str, Any]:
        """Generate compact persona profile from memory.

        Steps:
        1. Get high-salience facts from Graphiti
        2. Get important episodes from Qdrant
        3. Use LLM to distill into compact persona (300-1000 tokens)
        4. Save to disk

        Args:
            user_id: User ID
            character_id: Character ID
            graphiti_client: GraphitiMemoryClient instance
            qdrant_client: QdrantMemoryClient instance

        Returns:
            Distilled persona profile
        """
        logger.info(f"Distilling persona for user={user_id}, character={character_id}")

        try:
            # 1. Get high-salience facts from Graphiti (optional)
            person_facts = []
            if graphiti_client:
                try:
                    logger.debug("Retrieving facts from Graphiti...")
                    person_facts = await graphiti_client.retrieve_facts_about_person(
                        person_name=user_id,
                        valid_at=datetime.utcnow(),
                    )
                    logger.info(f"Retrieved {len(person_facts)} facts from Graphiti")
                except Exception as e:
                    logger.warning(f"Graphiti fact retrieval failed (non-critical): {e}")
                    person_facts = []
            else:
                logger.info("Graphiti not available, skipping fact retrieval")

            # 2. Get important episodes from Qdrant
            logger.debug("Retrieving episodes from Qdrant...")
            episodes = await qdrant_client.search_episodes(
                user_id=user_id,
                character_id=character_id,
                query="important life events preferences values personality traits relationships",
                limit=50,
                min_salience=0.7,
            )
            logger.info(f"Retrieved {len(episodes)} high-salience episodes from Qdrant")

            # 3. Use LLM to distill into compact persona
            logger.debug("Distilling persona with LLM...")
            persona = await self._call_llm_distillation(person_facts, episodes)

            # 4. Save to disk
            persona_data = {
                "user_id": user_id,
                "character_id": character_id,
                "persona": persona,
                "updated_at": datetime.utcnow().isoformat(),
                "version": 1,
                "facts_used": len(person_facts),
                "episodes_used": len(episodes),
            }

            persona_path = self._get_persona_path(user_id, character_id)
            with open(persona_path, "w") as f:
                json.dump(persona_data, f, indent=2)

            logger.info(f"Persona saved to {persona_path}")
            return persona

        except Exception as e:
            logger.error(f"Persona distillation failed: {e}")
            raise

    async def get_persona(self, user_id: str, character_id: str) -> Optional[Dict[str, Any]]:
        """Load persona profile from disk.

        Args:
            user_id: User ID
            character_id: Character ID

        Returns:
            Persona profile or None if not found
        """
        persona_path = self._get_persona_path(user_id, character_id)

        if not os.path.exists(persona_path):
            logger.debug(f"No persona found at {persona_path}")
            return None

        try:
            with open(persona_path, "r") as f:
                data = json.load(f)
                logger.debug(
                    f"Loaded persona for user={user_id}, character={character_id} "
                    f"(version={data.get('version')}, updated={data.get('updated_at')})"
                )
                return data["persona"]

        except Exception as e:
            logger.error(f"Failed to load persona: {e}")
            return None

    async def delete_persona(self, user_id: str, character_id: str) -> bool:
        """Delete persona profile.

        Args:
            user_id: User ID
            character_id: Character ID

        Returns:
            True if deleted, False if not found
        """
        persona_path = self._get_persona_path(user_id, character_id)

        if not os.path.exists(persona_path):
            return False

        try:
            os.remove(persona_path)
            logger.info(f"Deleted persona at {persona_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete persona: {e}")
            raise

    def _get_persona_path(self, user_id: str, character_id: str) -> str:
        """Get file path for persona JSON.

        Args:
            user_id: User ID
            character_id: Character ID

        Returns:
            File path
        """
        return os.path.join(self.storage_dir, f"{user_id}_{character_id}.json")

    async def _call_llm_distillation(
        self, person_facts: list, episodes: list
    ) -> Dict[str, Any]:
        """Call LLM to distill persona from facts and episodes.

        Args:
            person_facts: List of facts about the person
            episodes: List of conversation episodes

        Returns:
            Distilled persona JSON
        """
        logger.debug("Preparing persona distillation prompt...")

        # Format facts for prompt (limit to top 30 by relevance)
        facts_text = "\n".join(
            [
                f"- {fact.get('content', '')} (source: {fact.get('source', 'unknown')}, "
                f"relevance: {fact.get('relevance', 0.0):.2f})"
                for fact in person_facts[:30]
            ]
        )

        # Format episodes for prompt (limit to top 30 by score)
        episodes_text = "\n".join(
            [
                f"- User: {ep.get('user_message', '')[:100]}... | "
                f"AI: {ep.get('assistant_response', '')[:100]}... | "
                f"Tone: {ep.get('emotional_tone', 'neutral')}, "
                f"Importance: {ep.get('salience_score', 0.0):.2f}"
                for ep in episodes[:30]
            ]
        )

        distillation_prompt = f"""You are a psychological profiling expert. Distill a compact persona profile from conversation history.

KNOWLEDGE GRAPH FACTS ({len(person_facts)} total, showing top 30):
{facts_text if facts_text else "(No facts available)"}

EPISODIC MEMORY ({len(episodes)} total, showing top 30):
{episodes_text if episodes_text else "(No episodes available)"}

TASK: Create a concise persona profile (300-1000 tokens) that captures the USER'S essence.

INSTRUCTIONS:
1. **Core Values**: What principles guide their decisions? (3-7 values)
2. **Important Preferences**: Categorized preferences (hobbies, food, music, work style, etc.)
3. **Major Life Events**: Significant events mentioned (chronological if possible)
4. **Communication Style**: How do they express themselves? (tone, vocabulary, humor, formality)
5. **Emotional Sensitivities**: Topics that evoke strong emotions (positive or negative)
6. **Relationships**: Key people mentioned and their relationship type

REQUIREMENTS:
- Focus on PATTERNS across multiple conversations, not isolated mentions
- Prioritize high-importance/high-salience information
- Be specific and concrete, avoid generic descriptions
- Keep total output under 1000 tokens
- Return ONLY valid JSON, no explanations

OUTPUT FORMAT (JSON):
{{
  "core_values": ["value1", "value2", "value3"],
  "important_preferences": {{
    "hobbies": ["hobby1", "hobby2"],
    "food": ["preference1", "preference2"],
    "work_style": "description",
    "other_category": "preference"
  }},
  "major_life_events": [
    "event1 description",
    "event2 description"
  ],
  "communication_style": "Detailed description of how they communicate (tone, vocabulary, humor level, formality, etc.)",
  "emotional_sensitivities": [
    "topic1 that triggers strong emotions",
    "topic2 they're passionate about"
  ],
  "relationships": {{
    "person_name1": "relationship type/description",
    "person_name2": "relationship type/description"
  }}
}}

JSON response:"""

        try:
            logger.info("Calling Ollama for persona distillation...")
            response = await call_ollama(
                prompt=distillation_prompt,
                model=settings.OLLAMA_MODEL,
                ollama_url=settings.OLLAMA_URL,
                temperature=0.4,  # Slightly higher for creative synthesis
                response_format="json",
            )

            # Parse JSON response
            persona = extract_json_from_response(response)

            if persona is None:
                logger.warning("Failed to extract valid JSON from LLM response, using default structure")
                persona = {
                    "core_values": [],
                    "important_preferences": {},
                    "major_life_events": [],
                    "communication_style": "Unable to determine from available data",
                    "emotional_sensitivities": [],
                    "relationships": {},
                }
            else:
                # Validate required keys
                required_keys = [
                    "core_values",
                    "important_preferences",
                    "major_life_events",
                    "communication_style",
                    "emotional_sensitivities",
                    "relationships",
                ]
                for key in required_keys:
                    if key not in persona:
                        logger.warning(f"Missing key '{key}' in persona, adding default")
                        persona[key] = [] if key != "communication_style" else "Not specified"

                logger.info(f"Successfully distilled persona with {len(persona.get('core_values', []))} core values")

            return persona

        except Exception as e:
            logger.error(f"LLM distillation failed: {e}")
            # Return minimal valid structure on error
            return {
                "core_values": [],
                "important_preferences": {},
                "major_life_events": [],
                "communication_style": "Error during distillation",
                "emotional_sensitivities": [],
                "relationships": {},
            }
