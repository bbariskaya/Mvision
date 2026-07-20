import argparse
from pathlib import Path


def prepare_yolo_model(source: Path, output: Path) -> None:
    import onnx  # type: ignore[import-not-found]
    from onnx import TensorProto, helper

    model = onnx.load(source, load_external_data=False)
    original_outputs = [value.name for value in model.graph.output]
    if original_outputs != ["output0", "442", "450"]:
        raise ValueError(f"unexpected YOLO outputs: {original_outputs}")

    plugin_node = helper.make_node(
        "MvisionYoloFacePostprocess",
        inputs=original_outputs,
        outputs=["num_dets", "boxes", "scores", "landmarks"],
        domain="trt.plugins",
        plugin_version="1",
        plugin_namespace="",
        confidence_threshold=0.25,
        iou_threshold=0.45,
        name="mvision_yolo_face_postprocess",
    )
    model.graph.node.append(plugin_node)
    del model.graph.output[:]
    model.graph.output.extend(
        [
            helper.make_tensor_value_info("num_dets", TensorProto.INT32, ["batch"]),
            helper.make_tensor_value_info("boxes", TensorProto.FLOAT, ["batch", 100, 4]),
            helper.make_tensor_value_info("scores", TensorProto.FLOAT, ["batch", 100]),
            helper.make_tensor_value_info("landmarks", TensorProto.FLOAT, ["batch", 100, 10]),
        ]
    )
    if not any(opset.domain == "trt.plugins" for opset in model.opset_import):
        plugin_opset = model.opset_import.add()
        plugin_opset.domain = "trt.plugins"
        plugin_opset.version = 1

    onnx.checker.check_model(model)
    output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse GPU postprocess into YOLO ONNX.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare_yolo_model(args.source, args.output)


if __name__ == "__main__":
    main()
