import argparse
from pathlib import Path


def prepare_arcface_model(source: Path, output: Path) -> None:
    import onnx  # type: ignore[import-not-found]

    model = onnx.load(source, load_external_data=False)
    initializers = {initializer.name: initializer for initializer in model.graph.initializer}
    for name in ("arcface_mean", "arcface_std"):
        initializer = initializers.get(name)
        if initializer is None or list(initializer.dims) != [3]:
            raise ValueError(f"unexpected {name} shape")
        initializer.dims[:] = [1, 3, 1, 1]

    onnx.checker.check_model(model)
    output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare frozen ArcFace ONNX for TensorRT.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare_arcface_model(args.source, args.output)


if __name__ == "__main__":
    main()
