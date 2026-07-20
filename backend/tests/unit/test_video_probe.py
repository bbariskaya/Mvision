import json

import pytest

from app.infrastructure.video.probe import VideoProbeError, parse_probe_payload


def _payload(**stream_overrides):
    stream = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30000/1001",
        "nb_frames": "300",
    }
    stream.update(stream_overrides)
    return json.dumps(
        {
            "streams": [stream],
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "10.01"},
        }
    ).encode()


def test_parse_probe_uses_display_dimensions_after_rotation():
    metadata = parse_probe_payload(
        _payload(side_data_list=[{"side_data_type": "Display Matrix", "rotation": -90}])
    )

    assert metadata.container == "mp4"
    assert metadata.codec == "h264"
    assert (metadata.width, metadata.height) == (1080, 1920)
    assert metadata.rotation_degrees == 270
    assert metadata.fps == pytest.approx(29.97, rel=1e-3)
    assert metadata.total_frames == 300


def test_parse_probe_calculates_frames_when_container_omits_count():
    metadata = parse_probe_payload(_payload(nb_frames="N/A"))

    assert metadata.total_frames == 300


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"not-json", "VIDEO_INVALID"),
        (json.dumps({"streams": [], "format": {}}).encode(), "VIDEO_INVALID"),
        (_payload(avg_frame_rate="0/0"), "VIDEO_INVALID"),
    ],
)
def test_parse_probe_rejects_unusable_media(payload, code):
    with pytest.raises(VideoProbeError) as exc:
        parse_probe_payload(payload)

    assert exc.value.code == code
