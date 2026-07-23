import pytest
from pydantic import ValidationError

from app.presentation.schemas.live_sessions import LiveSessionCreateRequest
from app.services.live_session_compiler import LiveSessionCompiler


def _request(**overrides) -> dict:
    value = {
        "schemaVersion": 1,
        "cameraId": "gate-1",
        "profile": "face-recognition-v1",
        "source": {"type": "whipPush"},
        "processing": {"mode": "recognize"},
        "json": {"connectorRefs": ["019f0000-0000-7000-8000-000000000001"]},
    }
    value.update(overrides)
    return value


def test_source_union_rejects_url_for_whip_push() -> None:
    with pytest.raises(ValidationError):
        LiveSessionCreateRequest.model_validate(
            _request(source={"type": "whipPush", "url": "rtsp://forbidden"})
        )


def test_source_union_requires_url_for_pull_source() -> None:
    with pytest.raises(ValidationError):
        LiveSessionCreateRequest.model_validate(_request(source={"type": "rtspPull"}))


@pytest.mark.parametrize(
    "source",
    [
        {"type": "rtspPull", "url": "rtsp://"},
        {"type": "whepPull", "url": "wheps://"},
        {"type": "rtspPull", "url": "rtsp://camera/live\nforged"},
    ],
)
def test_source_union_rejects_malformed_pull_urls(source: dict) -> None:
    with pytest.raises(ValidationError):
        LiveSessionCreateRequest.model_validate(_request(source=source))


def test_live_request_rejects_unknown_or_internal_fields() -> None:
    with pytest.raises(ValidationError):
        LiveSessionCreateRequest.model_validate(_request(gpuId=2))


def test_live_request_rejects_malformed_connector_reference() -> None:
    with pytest.raises(ValidationError):
        LiveSessionCreateRequest.model_validate(_request(json={"connectorRefs": ["not-a-uuid"]}))


def test_compile_is_hash_stable_and_five_point_aligned() -> None:
    parsed = LiveSessionCreateRequest.model_validate(_request())

    first = LiveSessionCompiler().compile(parsed)
    second = LiveSessionCompiler().compile(parsed)

    assert first.spec_hash == second.spec_hash
    assert first.processing.alignment == "fivePoint"
    assert first.profile_version == 1


def test_compiler_uses_configured_profile_identity_and_version() -> None:
    parsed = LiveSessionCreateRequest.model_validate(_request(profile="face-recognition-v2"))

    resolved = LiveSessionCompiler(profile_id="face-recognition-v2", profile_version=2).compile(
        parsed
    )

    assert resolved.profile_id == "face-recognition-v2"
    assert resolved.profile_version == 2


def test_compile_hash_excludes_pull_url_plaintext() -> None:
    first = LiveSessionCreateRequest.model_validate(
        _request(source={"type": "rtspPull", "url": "rtsp://user:one@camera/a"})
    )
    second = LiveSessionCreateRequest.model_validate(
        _request(source={"type": "rtspPull", "url": "rtsp://user:two@camera/b"})
    )

    assert (
        LiveSessionCompiler().compile(first).spec_hash
        == LiveSessionCompiler().compile(second).spec_hash
    )


def test_json_requires_connector_or_persistence() -> None:
    parsed = LiveSessionCreateRequest.model_validate(
        _request(json={"connectorRefs": [], "persistFrames": False})
    )

    with pytest.raises(ValueError, match="LIVE_JSON_SINK_REQUIRED"):
        LiveSessionCompiler().compile(parsed)


def test_persistent_anonymous_requires_recognition() -> None:
    parsed = LiveSessionCreateRequest.model_validate(
        _request(processing={"mode": "detectTrack", "persistentAnonymous": True})
    )

    with pytest.raises(ValueError, match="LIVE_SESSION_SPEC_INVALID"):
        LiveSessionCompiler().compile(parsed)
