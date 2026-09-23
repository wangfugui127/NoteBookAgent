from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "NotebookAgent"
    app_env: str = "development"
    app_secret_key: str = "development-only-change-me-at-least-32-bytes"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_database: str = "notebookagent"
    mysql_user: str = "notebookagent"
    mysql_password: str = "notebookagent"

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "document_chunks_v2"
    milvus_document_collection: str = "notebook_documents_v1"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "notebookagent-neo4j"

    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_api_key: str = ""
    model_context_window: int = 1_048_576
    max_output_tokens: int = 32_768
    context_safety_ratio: float = Field(default=0.95, gt=0.5, le=1.0)
    context_trim_threshold: float = Field(default=0.6, gt=0.1, le=1.0)
    context_summary_threshold: float = Field(default=0.75, gt=0.1, le=1.0)
    context_keep_recent_turns: int = Field(default=6, ge=1, le=50)
    context_keep_recent_tool_results: int = Field(default=4, ge=0, le=50)
    history_recent_runs: int = Field(default=8, ge=1, le=50)

    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    openalex_mailto: str = ""
    upload_dir: Path = Path("./uploads")
    mcp_servers_config: Path = Path("../config/mcp_servers.yaml")
    mcp_expose_config: Path = Path("../config/mcp_expose.yaml")
    skills_config: Path = Path("../config/skills.yaml")
    run_live_provider_tests: bool = False

    @computed_field
    @property
    def mysql_dsn(self) -> str:
        return (
            f"mysql+asyncmy://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    @computed_field
    @property
    def effective_input_budget(self) -> int:
        safe_window = int(self.model_context_window * self.context_safety_ratio)
        return max(1, safe_window - self.max_output_tokens)


@lru_cache
def get_settings() -> Settings:
    return Settings()
