from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST

from app.main import app


def test_metrics_endpoint_uses_prometheus_content_type_and_no_secret_labels() -> None:
    response = TestClient(app).get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"] == CONTENT_TYPE_LATEST
    assert "mvision_live_worker_up" in response.text
    for forbidden in (
        "camera_id=",
        "run_id=",
        "track_id=",
        "face_id=",
        "trace_id=",
        "span_id=",
        "rtsp://",
    ):
        assert forbidden not in response.text
