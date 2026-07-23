from app.presentation.schemas.live_sessions import (
    LiveCapabilitiesResponse,
    LiveSessionResponse,
)


def test_live_session_response_schema_contains_no_secret_or_runtime_fields() -> None:
    schema = str(LiveSessionResponse.model_json_schema())

    for forbidden in (
        "sourceCiphertext",
        "sourceUrl",
        "internalRtsp",
        "mediamtxControl",
        "publisherCredential",
        "gpuId",
        "configPath",
        "rtpPort",
    ):
        assert forbidden not in schema


def test_capabilities_schema_exposes_only_safe_choices() -> None:
    properties = LiveCapabilitiesResponse.model_json_schema()["properties"]

    assert set(properties) == {
        "schemaVersions",
        "profiles",
        "sourceTypes",
        "processingModes",
        "samplingModes",
        "connectorTypes",
        "maxConcurrentSessions",
    }
