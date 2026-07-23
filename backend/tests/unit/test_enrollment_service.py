from types import SimpleNamespace

import pytest

from app.services.enrollment_service import EnrollmentService
from app.services.exceptions import ValidationError
from app.services.face_matcher import FaceMatch


def test_select_face_accepts_exactly_one_detection():
    face = SimpleNamespace()

    assert EnrollmentService._select_face((face,)) is face


def test_enrollment_rejects_multiple_faces():
    with pytest.raises(ValidationError) as raised:
        EnrollmentService._select_face((SimpleNamespace(), SimpleNamespace()))

    assert raised.value.error_code == "MULTIPLE_FACES"


def test_enrollment_reuses_matching_anonymous_identity():
    identity = SimpleNamespace(
        face_id="anonymous-id",
        lifecycle_status="anonymous",
        name=None,
    )
    match = FaceMatch(identity, "sample-id", 0.91)

    assert EnrollmentService._matching_identity_id(match) == "anonymous-id"


def test_enrollment_reuses_matching_known_identity_when_name_changes():
    identity = SimpleNamespace(
        face_id="known-id",
        lifecycle_status="known",
        name="Old Name",
    )
    match = FaceMatch(identity, "sample-id", 0.91)

    assert EnrollmentService._matching_identity_id(match) == "known-id"
