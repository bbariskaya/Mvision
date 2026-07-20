from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MergenVision API"
    debug: bool = False

    database_url: str = Field(
        default="postgresql+psycopg://mergen:mergen@postgres:5432/mergenvision",
        description="Async SQLAlchemy PostgreSQL URL.",
    )

    qdrant_url: str = Field(default="http://qdrant:6333")
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "face_samples_arcface_r50_webface_v1"
    qdrant_vector_size: int = 512
    qdrant_distance: str = "Cosine"

    minio_endpoint: str = Field(default="minio:9000")
    minio_access_key: str = Field(default="minioadmin")
    minio_secret_key: SecretStr = Field(default=SecretStr("minioadmin"))
    minio_bucket_faces: str = Field(default="mergenvision-faces")
    minio_secure: bool = False

    model_version: str = "arcface_r50_webface4m_v1"
    preprocess_version: str = "five-point-umeyama-112x112"
    detector_version: str = "yolov8n-face-v1"
    alignment_version: str = "umeyama-5point-112x112"

    max_upload_bytes: int = 10 * 1024 * 1024
    aligned_sample_max_bytes: int = 5 * 1024 * 1024

    recognition_threshold: float = 0.55
    anonymous_threshold: float = 0.40
    min_confidence: float = 0.25


@lru_cache
def get_settings() -> Settings:
    return Settings()
