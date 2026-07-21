from types import SimpleNamespace

from app.services.face_matcher import FaceMatch
from app.services.enrollment_service import EnrollmentService


def test_select_face_uses_largest_detection():
    small = SimpleNamespace(width=20.0, height=30.0)
    largest = SimpleNamespace(width=80.0, height=90.0)
    medium = SimpleNamespace(width=50.0, height=60.0)

    assert EnrollmentService._select_face((small, largest, medium)) is largest


def test_enrollment_does_not_reuse_differently_named_identity():
    identity = SimpleNamespace(
        face_id="chandler-id",
        lifecycle_status="known",
        name="Chandler",
    )
    match = FaceMatch(identity, "sample-id", 0.82)

    assert EnrollmentService._matching_identity_id(match, "Joey") is None


def test_enrollment_reuses_same_named_identity():
    identity = SimpleNamespace(
        face_id="chandler-id",
        lifecycle_status="known",
        name="Chandler",
    )
    match = FaceMatch(identity, "sample-id", 0.82)

    assert EnrollmentService._matching_identity_id(match, " chandler ") == "chandler-id"
