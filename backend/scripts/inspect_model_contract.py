import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tensor_shape(value_info: Any) -> list[int | str]:
    dimensions: list[int | str] = []
    for dimension in value_info.type.tensor_type.shape.dim:
        dimensions.append(dimension.dim_param or dimension.dim_value)
    return dimensions


def _tensor_contract(value_info: Any, onnx: Any) -> dict[str, Any]:
    tensor_type = value_info.type.tensor_type
    return {
        "name": value_info.name,
        "dtype": onnx.TensorProto.DataType.Name(tensor_type.elem_type),
        "shape": _tensor_shape(value_info),
    }


def inspect_model(path: Path) -> dict[str, Any]:
    import onnx  # type: ignore[import-not-found]
    from onnx import numpy_helper

    model = onnx.load(path, load_external_data=False)
    inferred = onnx.shape_inference.infer_shapes(model)
    small_initializers = {
        initializer.name: numpy_helper.to_array(initializer).reshape(-1).tolist()
        for initializer in inferred.graph.initializer
        if numpy_helper.to_array(initializer).size <= 16
    }
    return {
        "filename": path.name,
        "sha256": artifact_sha256(path),
        "ir_version": inferred.ir_version,
        "opsets": {
            (entry.domain or "ai.onnx"): entry.version
            for entry in sorted(inferred.opset_import, key=lambda item: item.domain)
        },
        "metadata": {
            entry.key: entry.value
            for entry in sorted(inferred.metadata_props, key=lambda item: item.key)
        },
        "inputs": [_tensor_contract(value, onnx) for value in inferred.graph.input],
        "outputs": [_tensor_contract(value, onnx) for value in inferred.graph.output],
        "operators": sorted({node.op_type for node in inferred.graph.node}),
        "small_initializers": dict(sorted(small_initializers.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect frozen ONNX model contracts.")
    parser.add_argument("models", nargs="*", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    model_paths = args.models or [
        Path(__file__).parents[1] / "models" / "yolov8n-face.onnx",
        Path(__file__).parents[1] / "models" / "arcface_r50_dynamic.onnx",
    ]
    report = {path.name: inspect_model(path) for path in model_paths}
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
