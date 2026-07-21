from scripts import annotate_video


def test_build_ass_renders_known_and_anonymous_detections() -> None:
    result = {
        "video": {
            "width": 1920,
            "height": 1080,
            "duration": 10.0,
            "sampling": {"effectiveFramesPerSecond": 2.0},
        },
        "persons": [
            {
                "trackId": "track-known",
                "status": "known",
                "name": "Jennifer {Aniston}",
                "confidence": 0.75,
                "detections": [
                    {
                        "timestamp": 1.0,
                        "boundingBox": {"x": 10, "y": 20, "width": 30, "height": 40},
                        "confidence": 0.9,
                        "landmarks": [
                            {"x": 12, "y": 22},
                            {"x": 18, "y": 22},
                            {"x": 15, "y": 26},
                            {"x": 13, "y": 30},
                            {"x": 17, "y": 30},
                        ],
                    }
                ],
            },
            {
                "trackId": "track-anonymous",
                "status": "new_anonymous",
                "name": None,
                "confidence": 0.0,
                "detections": [
                    {
                        "timestamp": 2.0,
                        "boundingBox": {"x": 50, "y": 60, "width": 70, "height": 80},
                        "confidence": 0.8,
                        "landmarks": [],
                    }
                ],
            },
        ],
    }

    content, event_count = annotate_video.build_ass(result)

    assert event_count == 9
    assert "Jennifer \\{Aniston\\} | cos 0.750 | det 0.900" in content
    assert "Unknown | cos 0.000 | det 0.800" in content
    assert "m 0 0 l 30 0 l 30 40 l 0 40" in content
    assert "\\pos(12,22)" in content
    assert "PlayResX: 1920" in content
