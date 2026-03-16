
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

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # File upload
    upload_file_dir: str = Field(default="data/files", alias="UPLOAD_FILE_DIR")


settings = Settings()
