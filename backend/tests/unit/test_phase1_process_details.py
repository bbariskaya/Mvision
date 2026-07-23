from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import app.services.enrollment_service as enrollment_module
import app.services.identity_service as identity_module
import app.services.recognition_service as recognition_module
from app.config import Settings
from app.services.enrollment_service import EnrollmentService
from app.services.face_matcher import FaceMatch
from app.services.identity_service import IdentityService
from app.services.recognition_service import RecognitionService

PROCESS_ID = "019f8000-0000-7000-8000-000000000001"
FACE_ID = "019f8000-0000-7000-8000-000000000002"


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        pass


class _Processes:
    def __init__(self):
        self.completions = []

    async def create(self, session, process_id, process_type):
        self.created = (process_id, process_type)

    async def complete(self, session, process_id, face_count, details=None):
        self.completions.append((process_id, face_count, details))

    async def fail(self, session, process_id, error_code):
        self.failed = (process_id, error_code)


class _Results:
    async def create(self, session, **kwargs):
        self.created = kwargs


class _Events:
    async def create(self, session, process_id, event_type, details):
        self.created = (process_id, event_type, details)


class _Samples:
    async def persist(self, **kwargs):
        self.persisted = kwargs


class _Workers:
    def __init__(self, detection):
        self.detection = detection

    async def process(self, image, process_id):
        return SimpleNamespace(faces=(self.detection,))


class _Matcher:
    def __init__(self, match):
        self.result = match

    async def match(self, embedding):
        return self.result


class _Identities:
    def __init__(self, identity):
        self.identity = identity

    async def get_active_by_id(self, session, face_id):
        return self.identity if face_id == self.identity.face_id else None

    async def update_known(self, session, face_id, name, metadata):
        self.identity.lifecycle_status = "known"
        self.identity.name = name
        self.identity.metadata_ = metadata
        return self.identity

    async def soft_delete(self, session, face_id):
        return self.identity if face_id == self.identity.face_id else None


class _SampleRepository:
    async def list_by_face(self, session, face_id, active_only):
        return []

    async def deactivate_by_face(self, session, face_id):
        return []


class _Qdrant:
    async def deactivate(self, sample_id):
        pass


def _identity(status="known", name="Ada"):
    now = datetime.now(UTC)
    return SimpleNamespace(
        face_id=FACE_ID,
        lifecycle_status=status,
        name=name,
        metadata_={"team": "vision"} if status == "known" else {},
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _detection():
    return SimpleNamespace(
        embedding=(1.0,) + (0.0,) * 511,
        aligned_jpeg=b"aligned-jpeg",
        x=1.0,
        y=2.0,
        width=3.0,
        height=4.0,
        landmarks_xy=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0),
        detector_confidence=0.95,
    )


@pytest.mark.asyncio
async def test_recognition_persists_face_snapshots_in_process_details(monkeypatch):
    monkeypatch.setattr(recognition_module, "AsyncSessionLocal", _Session)
    identity = _identity()
    processes = _Processes()
    service = RecognitionService(
        Settings(_env_file=None),
        _Workers(_detection()),
        _Matcher(FaceMatch(identity, "sample-1", 0.91)),
        _Samples(),
        processes,
        _Results(),
        _Events(),
    )

    await service.recognize(b"image", PROCESS_ID)

    assert processes.completions == [
        (
            PROCESS_ID,
            1,
            {
                "operation": "recognize",
                "face_count": 1,
                "faces": [{"face_id": FACE_ID, "status": "known"}],
            },
        )
    ]


@pytest.mark.asyncio
async def test_enrollment_persists_promoted_identity_in_process_details(monkeypatch):
    monkeypatch.setattr(enrollment_module, "AsyncSessionLocal", _Session)
    identity = _identity("anonymous", None)
    processes = _Processes()
    service = EnrollmentService(
        Settings(_env_file=None),
        _Workers(_detection()),
        _Matcher(FaceMatch(identity, "sample-1", 0.91)),
        _Samples(),
        _Identities(identity),
        processes,
        _Results(),
        _Events(),
    )

    await service.enroll(b"image", "Ada", {"team": "vision"}, process_id=PROCESS_ID)

    assert processes.completions == [
        (
            PROCESS_ID,
            1,
            {
                "operation": "enroll",
                "face_count": 1,
                "faces": [{"face_id": FACE_ID, "status": "known"}],
            },
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_identity_mutations_persist_process_details(monkeypatch, operation):
    monkeypatch.setattr(identity_module, "AsyncSessionLocal", _Session)
    identity = _identity()
    processes = _Processes()
    service = IdentityService(
        _Identities(identity),
        _SampleRepository(),
        processes,
        _Results(),
        _Events(),
        _Qdrant(),
    )

    if operation == "update":
        await service.update(FACE_ID, "Ada Lovelace", {"team": "vision"})
    else:
        await service.delete(FACE_ID)

    generated_process_id, face_count, details = processes.completions[0]
    assert generated_process_id
    assert face_count == 1
    assert details == {
        "operation": operation,
        "face_count": 1,
        "faces": [{"face_id": FACE_ID, "status": "known"}],
    }
