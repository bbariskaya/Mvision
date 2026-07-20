FROM nvcr.io/nvidia/deepstream:9.0-triton-multiarch@sha256:60888367d4c97ba192411a7694c984080a553f855ad53fc4c5579d70424fafd7

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        libmsgpack-cxx-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --break-system-packages onnx==1.22.0

WORKDIR /workspace
