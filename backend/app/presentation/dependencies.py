from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    FaceSampleRepository,
    ProcessEventRepository,
    ProcessRecordRepository,
    RecognitionResultRepository,
    VideoJobRepository,
)
from app.infrastructure.gpu.worker_pool import GpuWorkerPool
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter
from app.services.enrollment_service import EnrollmentService
from app.services.face_matcher import FaceMatcher
from app.services.face_sample_persistence_service import FaceSamplePersistenceService
from app.services.identity_service import IdentityService
from app.services.process_query_service import ProcessQueryService
from app.services.recognition_service import RecognitionService
from app.services.video_job_service import VideoJobService
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


@lru_cache
def get_container() -> ServiceContainer:
    settings = get_settings()
    identity_repo = FaceIdentityRepository()
    sample_repo = FaceSampleRepository()
    process_repo = ProcessRecordRepository()
    result_repo = RecognitionResultRepository()
    event_repo = ProcessEventRepository()
    video_job_repo = VideoJobRepository()
    minio = MinIOAdapter(settings)
    qdrant = QdrantAdapter(settings)
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
    video_uploads = VideoUploadService(
        settings, minio, video_job_repo, process_repo, event_repo
    )
    video_jobs = VideoJobService(video_job_repo)
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
