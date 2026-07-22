from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
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
    minio_bucket_videos: str = Field(default="mergenvision-videos")
    minio_bucket_live: str = Field(default="mergenvision-live")
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

    gpu_worker_sockets: str = (
        "/run/mvision/worker-0.sock,/run/mvision/worker-1.sock,/run/mvision/worker-2.sock"
    )
    gpu_worker_timeout_seconds: float = 120.0

    video_max_upload_bytes: int = 500 * 1024 * 1024
    video_max_duration_seconds: int = 300
    video_allowed_containers: str = "mp4,mov,avi,matroska"
    video_allowed_codecs: str = "h264,hevc,mjpeg,mpeg4"
    video_retention_seconds: int = 7 * 24 * 60 * 60
    video_minio_prefix: str = "videos"
    video_default_sampling_mode: str = "frames_per_second"
    video_default_frames_per_second: float = 2.0
    video_job_timeout_seconds: int = 1800
    video_probe_timeout_seconds: float = 30.0
    video_job_lease_seconds: int = 60
    video_job_max_attempts: int = 3
    video_progress_update_interval_seconds: float = 1.0
    video_track_reconciliation_threshold: float = 0.60
    video_track_vote_candidate_floor: float = Field(default=0.70, ge=0.0, le=1.0)
    video_track_vote_min_count: int = Field(default=2, ge=2)
    video_track_vote_min_margin: float = Field(default=0.05, ge=0.0, le=1.0)
    video_track_vote_min_support_ratio: float = Field(default=0.60, gt=0.5, le=1.0)
    video_appearance_max_gap_seconds: float = 1.5
    video_worker_poll_seconds: float = 1.0
    video_worker_gpu_id: int = 0
    video_native_executable: str = "/workspace/build/pipeline/mvision_video_worker"
    video_tracker_config_path: str = "/workspace/configs/video_tracker_nvdcf.yml"
    video_pgie_config_path: str = "/workspace/configs/video_pgie_yolov8_face.txt"
    video_preprocess_config_path: str = "/workspace/configs/video_preprocess_arcface.txt"
    video_sgie_config_path: str = "/workspace/configs/video_sgie_arcface_r50.txt"

    live_enabled: bool = False
    live_uri_encryption_keys: SecretStr | None = None
    live_uri_fingerprint_key: SecretStr | None = None
    live_worker_gpu_id: int = 0
    live_worker_id: str = "live-worker-0"
    live_worker_poll_seconds: float = 1.0
    live_worker_lease_seconds: int = 30
    live_native_executable: str = "/workspace/build/pipeline/mvision_live_worker"
    live_assignment_queue_capacity: int = 256
    live_identity_work_queue_capacity: int = 64
    live_tracker_config_path: str = "/workspace/configs/video_tracker_nvdcf.yml"
    live_pgie_config_path: str = "/workspace/configs/video_pgie_yolov8_face.txt"
    live_preprocess_config_path: str = "/workspace/configs/video_preprocess_arcface.txt"
    live_sgie_config_path: str = "/workspace/configs/video_sgie_arcface_r50.txt"
    live_latency_ms: int = 200
    live_reconnect_interval_seconds: int = 10
    live_reconnect_attempts: int = -1
    live_frame_timeout_ns: int = 5_000_000_000
    live_known_cooldown_seconds: float = 30.0
    live_unknown_min_dwell_seconds: float = 0.5
    live_rtsp_output_host: str = "localhost"
    live_rtsp_output_port: int = 8554
    live_rtp_udp_port: int = 5400

    @model_validator(mode="after")
    def validate_live_secrets(self) -> "Settings":
        encryption_keys = (
            self.live_uri_encryption_keys.get_secret_value().strip()
            if self.live_uri_encryption_keys is not None
            else ""
        )
        fingerprint_key = (
            self.live_uri_fingerprint_key.get_secret_value().strip()
            if self.live_uri_fingerprint_key is not None
            else ""
        )
        if self.live_enabled and (not encryption_keys or not fingerprint_key):
            raise ValueError("LIVE_SECRET_CONFIGURATION_REQUIRED")
        return self

    @property
    def gpu_socket_paths(self) -> list[str]:
        return [path.strip() for path in self.gpu_worker_sockets.split(",") if path.strip()]

    @property
    def video_allowed_container_set(self) -> set[str]:
        return {
            value.strip().lower()
            for value in self.video_allowed_containers.split(",")
            if value.strip()
        }

    @property
    def video_allowed_codec_set(self) -> set[str]:
        return {
            value.strip().lower()
            for value in self.video_allowed_codecs.split(",")
            if value.strip()
        }

    @property
    def live_encryption_key_values(self) -> list[str]:
        if self.live_uri_encryption_keys is None:
            return []
        return [
            value.strip()
            for value in self.live_uri_encryption_keys.get_secret_value().split(",")
            if value.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
