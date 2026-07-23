from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    FaceSampleRepository,
    LiveCameraRepository,
    LiveConnectorRepository,
    LiveEventRepository,
    LiveRunRepository,
    LiveSessionRepository,
    ProcessEventRepository,
    ProcessRecordRepository,
    RecognitionResultRepository,
    VideoJobRepository,
    VideoTrackRepository,
)
from app.infrastructure.gpu.worker_pool import GpuWorkerPool
from app.infrastructure.live.native_runner import NativeLiveRunner
from app.infrastructure.live.uri_cipher import LiveUriCipher
from app.infrastructure.media.mediamtx_client import MediaMtxClient
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter
from app.infrastructure.video.native_runner import NativeVideoRunner
from app.observability.metrics import MvisionMetrics
from app.observability.telemetry import TelemetryRuntime
from app.services.enrollment_service import EnrollmentService
from app.services.face_matcher import FaceMatcher
from app.services.face_sample_persistence_service import FaceSamplePersistenceService
from app.services.identity_service import IdentityService
from app.services.live_camera_service import LiveCameraService
from app.services.live_connector_service import LiveConnectorService
from app.services.live_event_service import InMemoryLiveNotifier, LiveEventService
from app.services.live_identity_service import LiveIdentityService
from app.services.live_session_compiler import LiveSessionCompiler
from app.services.live_session_service import LiveSessionService
from app.services.live_supervisor import LiveSupervisor
from app.services.mediamtx_reconciliation_service import MediaMtxReconciliationService
from app.services.process_query_service import ProcessQueryService
from app.services.recognition_service import RecognitionService
from app.services.video_identity_voting_service import VideoIdentityVotingService
from app.services.video_job_service import VideoJobService
from app.services.video_processor import VideoJobProcessor
from app.services.video_result_service import VideoResultService
from app.services.video_tracking_service import VideoTrackingService
from app.services.video_upload_service import VideoUploadService


@dataclass(frozen=True)
class ServiceContainer:
    settings: Settings
    minio: MinIOAdapter
    qdrant: QdrantAdapter
    recognition: RecognitionService
    enrollment: EnrollmentService
    identities: IdentityService
    processes: ProcessQueryService
    video_uploads: VideoUploadService
    video_jobs: VideoJobService
    video_results: VideoResultService
    video_processor: VideoJobProcessor
    live_cameras: LiveCameraService
    live_supervisor: LiveSupervisor
    live_connectors: LiveConnectorService
    live_sessions: LiveSessionService
    mediamtx_client: MediaMtxClient
    mediamtx_reconciler: MediaMtxReconciliationService


@lru_cache
def get_container(
    telemetry: TelemetryRuntime | None = None,
    metrics: MvisionMetrics | None = None,
) -> ServiceContainer:
    settings = get_settings()
    identity_repo = FaceIdentityRepository()
    sample_repo = FaceSampleRepository()
    process_repo = ProcessRecordRepository()
    result_repo = RecognitionResultRepository()
    event_repo = ProcessEventRepository()
    video_job_repo = VideoJobRepository()
    video_track_repo = VideoTrackRepository()
    live_camera_repo = LiveCameraRepository()
    live_run_repo = LiveRunRepository()
    live_event_repo = LiveEventRepository()
    live_connector_repo = LiveConnectorRepository()
    live_session_repo = LiveSessionRepository()
    minio = MinIOAdapter(settings)
    qdrant = QdrantAdapter(settings, telemetry)
    workers = GpuWorkerPool(settings.gpu_socket_paths, settings.gpu_worker_timeout_seconds)
    matcher = FaceMatcher(settings, identity_repo, qdrant)
    samples = FaceSamplePersistenceService(
        settings,
        identity_repo,
        sample_repo,
        process_repo,
        event_repo,
        minio,
        qdrant,
    )
    recognition = RecognitionService(
        settings, workers, matcher, samples, process_repo, result_repo, event_repo
    )
    enrollment = EnrollmentService(
        settings,
        workers,
        matcher,
        samples,
        identity_repo,
        process_repo,
        result_repo,
        event_repo,
    )
    identities = IdentityService(
        identity_repo, sample_repo, process_repo, result_repo, event_repo, qdrant
    )
    processes = ProcessQueryService(process_repo, result_repo, event_repo)
    video_uploads = VideoUploadService(settings, minio, video_job_repo, process_repo, event_repo)
    video_jobs = VideoJobService(video_job_repo, video_track_repo, process_repo, minio)
    video_tracking = VideoTrackingService(
        settings.video_track_reconciliation_threshold,
        settings.video_appearance_max_gap_seconds,
    )
    video_voter = VideoIdentityVotingService(settings, matcher)
    video_results = VideoResultService(
        settings,
        video_tracking,
        video_voter,
        samples,
        result_repo,
        video_track_repo,
        video_job_repo,
        process_repo,
    )
    video_processor = VideoJobProcessor(
        settings,
        minio,
        video_job_repo,
        process_repo,
        NativeVideoRunner(settings),
        video_results.finalize,
        event_repo,
    )
    live_cipher = None
    if settings.live_encryption_key_values and settings.live_uri_fingerprint_key is not None:
        live_cipher = LiveUriCipher(
            settings.live_encryption_key_values,
            settings.live_uri_fingerprint_key.get_secret_value(),
        )
    live_cameras = LiveCameraService(
        live_camera_repo,
        live_run_repo,
        live_event_repo,
        live_cipher,
        output_host=settings.live_rtsp_output_host,
        output_port=settings.live_rtsp_output_port,
    )
    live_voter = VideoIdentityVotingService(
        settings, matcher, eligible_lifecycle_statuses=frozenset({"known"})
    )
    live_identity = LiveIdentityService(settings, live_voter, qdrant, telemetry)
    live_events = LiveEventService(
        settings,
        live_event_repo,
        minio,
        InMemoryLiveNotifier(),
        telemetry=telemetry,
    )
    live_supervisor = LiveSupervisor(
        settings,
        live_camera_repo,
        live_run_repo,
        live_cipher,
        NativeLiveRunner(settings),
        identity_service=live_identity,
        event_service=live_events,
        telemetry=telemetry,
        metrics=metrics,
        session_repository=live_session_repo,
    )
    mediamtx_client = MediaMtxClient(
        settings.mediamtx_control_url,
        settings.mediamtx_request_timeout_seconds,
    )
    mediamtx_reconciler = MediaMtxReconciliationService(
        mediamtx_client,
        live_session_repo,
        live_cipher,
    )
    live_connectors = LiveConnectorService(live_connector_repo, live_cipher)
    live_sessions = LiveSessionService(
        settings,
        live_session_repo,
        live_connector_repo,
        LiveSessionCompiler(
            settings.live_profile_id,
            settings.live_profile_version,
        ),
        live_cipher,
        mediamtx_reconciler,
    )
    return ServiceContainer(
        settings,
        minio,
        qdrant,
        recognition,
        enrollment,
        identities,
        processes,
        video_uploads,
        video_jobs,
        video_results,
        video_processor,
        live_cameras,
        live_supervisor,
        live_connectors,
        live_sessions,
        mediamtx_client,
        mediamtx_reconciler,
    )


def get_recognition_service() -> RecognitionService:
    return get_container().recognition


def get_enrollment_service() -> EnrollmentService:
    return get_container().enrollment


def get_identity_service() -> IdentityService:
    return get_container().identities


def get_process_service() -> ProcessQueryService:
    return get_container().processes


def get_video_upload_service() -> VideoUploadService:
    return get_container().video_uploads


def get_video_job_service() -> VideoJobService:
    return get_container().video_jobs


def get_live_camera_service() -> LiveCameraService:
    return get_container().live_cameras


def get_live_connector_service() -> LiveConnectorService:
    return get_container().live_connectors


def get_live_session_service() -> LiveSessionService:
    return get_container().live_sessions
