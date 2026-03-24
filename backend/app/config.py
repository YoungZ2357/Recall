
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="",
        populate_by_name=True
    )

    # SQLite
    sqlite_path: str = Field(default="data/recall.db", alias="SQLITE_PATH")

    # Qdrant
    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")
    qdrant_collection: str = Field(default="recall", alias="QDRANT_COLLECTION")

    # Embedding
    embedding_provider: str = Field(default="api", alias="EMBEDDING_PROVIDER")
    embedding_api_key: str | None = Field(default=None, alias="EMBEDDING_API_KEY")
    embedding_model: str = Field(default="embedding-3", alias="EMBEDDING_MODEL")
    embedding_dimension: int = Field(default=1536, alias="EMBEDDING_DIMENSION")

    # Generation
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="deepseek-v3", alias="LLM_MODEL")
    llm_base_url: str = Field(default="https://api.deepseek.com", alias="LLM_BASE_URL")
    llm_max_tokens: int = Field(default=1024, alias="LLM_MAX_TOKENS")
    llm_temperature: float = Field(default=0.7, alias="LLM_TEMPERATURE")

    # Reranker
    reranker_alpha: float = Field(default=0.6, alias="RERANKER_ALPHA")
    reranker_beta: float = Field(default=0.2, alias="RERANKER_BETA")
    reranker_gamma: float = Field(default=0.2, alias="RERANKER_GAMMA")
    reranker_s_base: float = Field(default=24.0, alias="RERANKER_S_BASE")
    reranker_tag_fallback: float = Field(default=0.5, alias="RERANKER_TAG_FALLBACK")
    reranker_score_threshold: float = Field(default=0.60, alias="RERANKER_SCORE_THRESHOLD")

    # Vector search
    vector_score_threshold: float = Field(default=0.35, alias="VECTOR_SCORE_THRESHOLD")

    # RRF
    rrf_k: int = Field(default=60, alias="RRF_K")

    # CORS
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        alias="CORS_ORIGINS",
    )

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # File upload
    upload_file_dir: str = Field(default="data/files", alias="UPLOAD_FILE_DIR")


settings = Settings()
