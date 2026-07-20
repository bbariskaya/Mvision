from pathlib import Path

import pytest

from scripts.inspect_model_contract import artifact_sha256, inspect_model
from scripts.prepare_arcface_model import prepare_arcface_model
from scripts.prepare_yolo_model import prepare_yolo_model

MODEL_DIR = Path(__file__).parents[2] / "models"
EXPECTED_SHA256 = {
    "yolov8n-face.onnx": "33f3951af7fc0c4d9b321b29cdcd8c9a59d0a29a8d4bdc01fcb5507d5c714809",
    "arcface_r50_dynamic.onnx": (
        "ebbeb12e1162ff839e7c1ad3b6f63758198a001d9ad871b6e2f09256210995bf"
    ),
}


@pytest.mark.parametrize(("filename", "expected_sha256"), EXPECTED_SHA256.items())
def test_model_artifact_sha256_is_frozen(filename: str, expected_sha256: str) -> None:
    artifact = MODEL_DIR / filename

    assert artifact.is_file(), f"Missing frozen model artifact: {artifact}"
    assert artifact_sha256(artifact) == expected_sha256


def test_yolov8_face_contract_contains_three_pose_heads() -> None:
    contract = inspect_model(MODEL_DIR / "yolov8n-face.onnx")

    assert contract["inputs"] == [
        {"name": "images", "dtype": "FLOAT", "shape": ["batch", 3, "height", "width"]}
    ]
    assert [output["name"] for output in contract["outputs"]] == ["output0", "442", "450"]
    assert [output["shape"][1] for output in contract["outputs"]] == [80, 80, 80]
    assert contract["metadata"]["task"] == "pose"
    assert contract["metadata"]["kpt_shape"] == "[5, 3]"
    assert contract["metadata"]["stride"] == "32"


def test_arcface_contract_owns_preprocessing_and_l2_normalization() -> None:
    contract = inspect_model(MODEL_DIR / "arcface_r50_dynamic.onnx")

    assert contract["inputs"] == [
        {"name": "input.1", "dtype": "FLOAT", "shape": ["input.1_0", 3, 112, 112]}
    ]
    assert contract["outputs"] == [{"name": "output", "dtype": "FLOAT", "shape": ["output_0", 512]}]
    assert contract["small_initializers"]["arcface_mean"] == [127.5, 127.5, 127.5]
    assert contract["small_initializers"]["arcface_std"] == [128.0, 128.0, 128.0]
    assert "LpNormalization" in contract["operators"]


def test_arcface_tensorrt_artifact_uses_nchw_broadcast_constants(tmp_path: Path) -> None:
    import onnx

    source = MODEL_DIR / "arcface_r50_dynamic.onnx"
    output = tmp_path / "arcface_r50_tensorrt.onnx"
    prepare_arcface_model(source, output)

    model = onnx.load(output)
    shapes = {
        initializer.name: list(initializer.dims)
        for initializer in model.graph.initializer
        if initializer.name in {"arcface_mean", "arcface_std"}
    }
    assert shapes == {"arcface_mean": [1, 3, 1, 1], "arcface_std": [1, 3, 1, 1]}
    assert artifact_sha256(source) == EXPECTED_SHA256[source.name]


def test_yolo_tensorrt_artifact_fuses_compact_gpu_postprocess(tmp_path: Path) -> None:
    import onnx

    source = MODEL_DIR / "yolov8n-face.onnx"
    output = tmp_path / "yolov8n_face_tensorrt.onnx"
    prepare_yolo_model(source, output)

    model = onnx.load(output)
    assert [value.name for value in model.graph.output] == [
        "num_dets",
        "boxes",
        "scores",
        "landmarks",
    ]
    assert model.graph.node[-1].op_type == "MvisionYoloFacePostprocess"
    assert list(model.graph.node[-1].input) == ["output0", "442", "450"]
    assert artifact_sha256(source) == EXPECTED_SHA256[source.name]
