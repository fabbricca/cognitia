"""Configuration for Cognitia Memory Add-on Service."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Memory Add-on configuration settings."""

    # Neo4j for Graphiti
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "cognitia_episodes"

    # Embedding model (FastEmbed compatible)
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"  # 384 dims, fast, lightweight

    # Ollama for LLM
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"

    # Salience scoring weights
    SALIENCE_LLM_WEIGHT: float = 0.6
    SALIENCE_EMOTION_WEIGHT: float = 0.3
    SALIENCE_MANUAL_WEIGHT: float = 0.1

    # Recency decay constant (days)
    RECENCY_DECAY_T: int = 30

    # Minimum salience to persist a conversation turn as an "episode".
    # Low-salience turns without any extracted facts will be skipped.
    MIN_EPISODE_SALIENCE_TO_STORE: float = 0.6

    # Minimum number of extracted facts required to persist even if salience is low.
    # Set to 1 to persist turns that teach the system something concrete.
    MIN_FACTS_FOR_STORAGE: int = 1

    # Persona storage
    PERSONA_STORAGE_DIR: str = "./personas"

    # Redis for Celery
    REDIS_HOST: str = "redis-memory"
    REDIS_PORT: int = 6379

    class Config:
        env_file = ".env"


# Global settings instance
settings = Settings()
