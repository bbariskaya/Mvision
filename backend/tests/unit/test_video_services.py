import pytest

from app.config import Settings
from app.services.exceptions import ValidationError
from app.services.video_upload_service import resolve_sampling


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_resolve_sampling_uses_configured_default():
    value = resolve_sampling(_settings(), source_fps=25.0)

    assert value["mode"] == "frames_per_second"
    assert value["requestedFramesPerSecond"] == 2.0
    assert value["everyNFrames"] == 12
    assert value["effectiveFramesPerSecond"] == pytest.approx(25 / 12)


def test_resolve_sampling_validates_mode_specific_fields():
    with pytest.raises(ValidationError) as exc:
        resolve_sampling(
            _settings(),
            source_fps=25.0,
            mode="every_n_frames",
            every_n_frames=0,
        )

    assert exc.value.error_code == "INVALID_SAMPLING"


def test_resolve_sampling_rejects_target_above_source_fps():
    with pytest.raises(ValidationError):
        resolve_sampling(
            _settings(),
            source_fps=25.0,
            mode="frames_per_second",
            frames_per_second=30.0,
        )
