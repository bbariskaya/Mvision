FROM nvcr.io/nvidia/deepstream:9.0-triton-multiarch@sha256:60888367d4c97ba192411a7694c984080a553f855ad53fc4c5579d70424fafd7

WORKDIR /workspace

COPY build/pipeline/mvision_worker build/pipeline/mvision_worker
COPY build/pipeline/*.so build/pipeline/
COPY backend/models/engines backend/models/engines
COPY configs configs

ENV LD_LIBRARY_PATH=/workspace/build/pipeline:/opt/nvidia/deepstream/deepstream/lib

ENTRYPOINT []
