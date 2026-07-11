from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    DEFAULT_AGENT_RUN_LIST_LIMIT,
    DEFAULT_AGENT_RUN_STATUS_TTL_SECONDS,
    DEFAULT_IMAGE_API_TIMEOUT_SECONDS,
    DEFAULT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
    DEFAULT_IMAGE_INPUT_MAX_BYTES,
    DEFAULT_IMAGE_PROMPT_MAX_LENGTH,
    DEFAULT_UPLOAD_MAX_BYTES,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = Field(default="local", alias="APP_ENV")
    app_name: str = Field(default="HY-chat", alias="APP_NAME")
    app_port: int = Field(default=8000, alias="APP_PORT")

    database_url: str = Field(
        default="postgresql+psycopg://hy_chat:hy_chat_password@localhost:5432/hy_chat_db",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    jwt_secret_key: str = Field(
        default="change-me-in-production-hy-chat-secret",
        alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_minutes: int = Field(default=30, alias="JWT_ACCESS_TOKEN_MINUTES")
    jwt_refresh_token_days: int = Field(default=30, alias="JWT_REFRESH_TOKEN_DAYS")
    default_rpm_limit: int = Field(default=30, alias="DEFAULT_RPM_LIMIT")
    default_monthly_token_quota: int = Field(
        default=1_000_000,
        alias="DEFAULT_MONTHLY_TOKEN_QUOTA",
    )
    default_allow_image_generation: bool = Field(
        default=True,
        alias="DEFAULT_ALLOW_IMAGE_GENERATION",
    )
    default_allow_high_cost_tools: bool = Field(
        default=False,
        alias="DEFAULT_ALLOW_HIGH_COST_TOOLS",
    )

    zhipu_api_key: str = Field(default="", alias="ZHIPU_API_KEY")
    zhipu_base_url: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4", alias="ZHIPU_BASE_URL"
    )
    zhipu_chat_model: str = Field(default="glm-5.2", alias="ZHIPU_CHAT_MODEL")
    zhipu_chat_models: str = Field(
        default="glm-5.2,glm-4.5,glm-4-flash",
        alias="ZHIPU_CHAT_MODELS",
    )
    zhipu_image_model: str = Field(default="glm-image", alias="ZHIPU_IMAGE_MODEL")
    openai_image_api_key: str = Field(default="", alias="OPENAI_IMAGE_API_KEY")
    openai_image_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_IMAGE_BASE_URL",
    )
    openai_image_model: str = Field(default="gpt-image-2", alias="OPENAI_IMAGE_MODEL")
    image_api_timeout_seconds: float = Field(
        default=DEFAULT_IMAGE_API_TIMEOUT_SECONDS,
        alias="IMAGE_API_TIMEOUT_SECONDS",
    )
    image_download_timeout_seconds: float = Field(
        default=DEFAULT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
        alias="IMAGE_DOWNLOAD_TIMEOUT_SECONDS",
    )
    image_prompt_max_length: int = Field(
        default=DEFAULT_IMAGE_PROMPT_MAX_LENGTH,
        alias="IMAGE_PROMPT_MAX_LENGTH",
    )
    image_input_max_bytes: int = Field(
        default=DEFAULT_IMAGE_INPUT_MAX_BYTES,
        alias="IMAGE_INPUT_MAX_BYTES",
    )
    zhipu_embedding_model: str = Field(
        default="embedding-3", alias="ZHIPU_EMBEDDING_MODEL"
    )
    embedding_dimensions: int = Field(default=1024, alias="EMBEDDING_DIMENSIONS")

    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    alpha_vantage_api_key: str = Field(default="", alias="ALPHA_VANTAGE_API_KEY")
    external_api_timeout: float = Field(default=20.0, alias="EXTERNAL_API_TIMEOUT")

    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")
    cache_default_ttl: int = Field(default=600, alias="CACHE_DEFAULT_TTL")
    cache_embedding_ttl: int = Field(default=604800, alias="CACHE_EMBEDDING_TTL")

    rag_upload_dir: str = Field(default="/data/rag/uploads", alias="RAG_UPLOAD_DIR")
    rag_chunk_size: int = Field(default=1000, alias="RAG_CHUNK_SIZE")
    rag_chunk_overlap: int = Field(default=150, alias="RAG_CHUNK_OVERLAP")
    rag_top_k: int = Field(default=4, alias="RAG_TOP_K")

    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    local_storage_dir: str = Field(default="/data/storage", alias="LOCAL_STORAGE_DIR")
    s3_endpoint_url: str = Field(default="", alias="S3_ENDPOINT_URL")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    s3_access_key_id: str = Field(default="", alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(default="", alias="S3_SECRET_ACCESS_KEY")
    s3_public_base_url: str = Field(default="", alias="S3_PUBLIC_BASE_URL")
    s3_presign_expiry_seconds: int = Field(
        default=900, alias="S3_PRESIGN_EXPIRY_SECONDS"
    )
    max_upload_bytes: int = Field(
        default=DEFAULT_UPLOAD_MAX_BYTES,
        alias="MAX_UPLOAD_BYTES",
    )
    backend_public_url: str = Field(
        default="http://localhost:8000",
        alias="BACKEND_PUBLIC_URL",
    )

    agent_run_status_ttl_seconds: int = Field(
        default=DEFAULT_AGENT_RUN_STATUS_TTL_SECONDS,
        alias="AGENT_RUN_STATUS_TTL_SECONDS",
    )
    agent_run_list_limit: int = Field(
        default=DEFAULT_AGENT_RUN_LIST_LIMIT,
        alias="AGENT_RUN_LIST_LIMIT",
    )

    workspace_root: str = Field(default="/workspace", alias="WORKSPACE_ROOT")
    enable_command_tool: bool = Field(default=False, alias="ENABLE_COMMAND_TOOL")

    api_version: str = Field(default="v1", alias="API_VERSION")
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ORIGINS",
    )

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_root).resolve()

    @property
    def available_chat_models(self) -> list[str]:
        models = [
            model.strip()
            for model in self.zhipu_chat_models.split(",")
            if model.strip()
        ]
        if self.zhipu_chat_model not in models:
            models.insert(0, self.zhipu_chat_model)
        return list(dict.fromkeys(models))

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def s3_enabled(self) -> bool:
        return self.storage_backend.lower() == "s3" and bool(self.s3_bucket)


@lru_cache
def get_settings() -> Settings:
    return Settings()
