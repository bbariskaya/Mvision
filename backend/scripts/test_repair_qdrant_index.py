from types import SimpleNamespace

import pytest

from scripts import repair_qdrant_index


def test_require_single_face_returns_matching_embedding() -> None:
    face = SimpleNamespace(embedding=(1.0, 0.0))
    result = SimpleNamespace(request_id="sample-id", status="OK", error_code="", faces=(face,))

    assert repair_qdrant_index.require_single_face(result, "sample-id") == [1.0, 0.0]


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(request_id="other-id", status="OK", error_code="", faces=(object(),)),
        SimpleNamespace(request_id="sample-id", status="ERROR", error_code="FAILED", faces=()),
        SimpleNamespace(request_id="sample-id", status="OK", error_code="", faces=()),
        SimpleNamespace(
            request_id="sample-id", status="OK", error_code="", faces=(object(), object())
        ),
    ],
)
def test_require_single_face_rejects_ambiguous_results(result) -> None:
    with pytest.raises(RuntimeError):
        repair_qdrant_index.require_single_face(result, "sample-id")
