FROM nvcr.io/nvidia/deepstream:9.0-triton-multiarch@sha256:60888367d4c97ba192411a7694c984080a553f855ad53fc4c5579d70424fafd7

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libpq-dev \
    python3-pip \
    && apt-get install -y --reinstall --no-install-recommends \
    libflac12t64 \
    libmp3lame0 \
    libmpg123-0t64 \
    libvpx9 \
    libx264-164 \
    libx265-199 \
    && ffmpeg -version >/dev/null \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN python3 -m pip install --no-cache-dir --break-system-packages -e "/workspace/backend"

COPY build/pipeline/mvision_worker build/pipeline/mvision_worker
COPY build/pipeline/mvision_video_worker build/pipeline/mvision_video_worker
COPY build/pipeline/*.so build/pipeline/
COPY backend/models/engines backend/models/engines
COPY configs configs

ENV LD_LIBRARY_PATH=/workspace/build/pipeline:/opt/nvidia/deepstream/deepstream/lib
ENV PYTHONPATH=/workspace/backend

ENTRYPOINT []
