# Phase 2 Video Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the complete asynchronous uploaded-video recognition backend from `requirements/videorequirements.md` with a DeepStream GPU hot path, durable jobs, person aggregation, retention, cancellation, and appearance history.

**Architecture:** FastAPI validates and stores uploads, then records pending jobs in PostgreSQL. GPU-pinned Python workers claim jobs with leases, run a native C++ DeepStream file pipeline, reconcile tracker fragments, resolve one identity per canonical track through Qdrant, and persist person-level results. MinIO retains source videos until an environment-configured expiry.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, async SQLAlchemy 2, PostgreSQL 16, MinIO, Qdrant, MessagePack, C++17, GStreamer, NVIDIA DeepStream 9, NvDCF, CUDA, TensorRT, Docker Compose, pytest, CTest.

## Global Constraints

- Preserve every existing PostgreSQL, Qdrant, and MinIO record; migrations are additive.
- Do not reset or recreate Docker volumes.
- Do not modify frontend files.
- Do not add Redis or Celery.
- Do not send decoded full frames from native code to Python; only metadata, representative embedding, and bounded evidence bytes may cross the boundary.
- Read SGIE embeddings from each object's `NvDsInferTensorMeta`, never from raw callback row order.
- The tracker sees every decoded frame; ArcFace and output collection run only on sampled frames.
- All returned boxes use original display coordinates.
- Do not commit, create worktrees, or dispatch subagents unless the user explicitly changes that instruction.

---

## File Structure

### Python API and Domain

- `backend/app/config.py`: video limits, worker, sampling, retention, and DeepStream paths.
- `backend/app/infrastructure/database/models.py`: `VideoJob` and `VideoTrack`; additive process fields.
- `backend/app/infrastructure/database/repositories/video_job_repository.py`: CRUD, claims, leases, progress, cancellation, retention claims.
- `backend/app/infrastructure/database/repositories/video_track_repository.py`: idempotent track replacement and appearance queries.
- `backend/app/infrastructure/video/probe.py`: bounded `ffprobe` execution and metadata parsing.
- `backend/app/infrastructure/video/protocol.py`: native MessagePack event decoder.
- `backend/app/infrastructure/video/native_runner.py`: cancellable native process runner.
- `backend/app/infrastructure/object_storage/minio_adapter.py`: video upload/download/range/delete operations.
- `backend/app/services/video_upload_service.py`: upload validation, process/job creation, source retrieval.
- `backend/app/services/video_tracking_service.py`: tracklet reconciliation and appearance intervals.
- `backend/app/services/video_result_service.py`: identity resolution, result persistence, query mapping.
- `backend/app/services/video_job_service.py`: status, cancellation, worker processing, retention cleanup.
- `backend/app/presentation/schemas/videos.py`: public camelCase contracts.
- `backend/app/presentation/routers/videos.py`: video endpoints.
- `backend/app/worker/video_worker_main.py`: PostgreSQL poll/lease loop.

### Native DeepStream Worker

- `backend/pipeline/include/mvision/video_protocol.hpp`: native event structs and encoder.
- `backend/pipeline/include/mvision/video_pipeline.hpp`: file-pipeline interface and result structs.
- `backend/pipeline/src/video_protocol.cpp`: MessagePack event encoding.
- `backend/pipeline/src/video_pipeline.cpp`: DeepStream graph, probes, tracking, sampling, coordinates, EOS.
- `backend/pipeline/src/video_worker_main.cpp`: CLI, signals, protocol output, stable exit codes.
- `configs/video_tracker_nvdcf.yml`: tracker behavior.
- `configs/video_pgie_yolov8_face.txt`: batch-one dynamic detector settings.
- `configs/video_preprocess_arcface.txt`: object preprocess settings.
- `configs/video_sgie_arcface_r50.txt`: batch face recognizer settings.

### Tests and Deployment

- `backend/tests/unit/test_video_probe.py`
- `backend/tests/unit/test_video_protocol.py`
- `backend/tests/unit/test_video_tracking_service.py`
- `backend/tests/unit/test_video_job_repository.py`
- `backend/tests/unit/test_video_services.py`
- `backend/tests/contract/test_videos_api.py`
- `backend/pipeline/tests/test_video_protocol.cpp`
- `backend/pipeline/tests/test_video_aggregation.cpp`
- `backend/alembic/versions/<revision>_phase2_video_backend.py`
- `backend/pipeline/CMakeLists.txt`
- `backend/pipeline/Dockerfile`
- `backend/Dockerfile`
- `backend/.env.example`
- `docker-compose.sprint01.yml`

---

### Task 1: Add Video Configuration and Additive Schema

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/infrastructure/database/models.py`
- Modify: `backend/app/infrastructure/database/repositories/process_repository.py`
- Modify: `backend/app/infrastructure/database/repositories/__init__.py`
- Create: `backend/app/infrastructure/database/repositories/video_job_repository.py`
- Create: `backend/app/infrastructure/database/repositories/video_track_repository.py`
- Create: `backend/alembic/versions/c21d7a1e4f02_phase2_video_backend.py`
- Test: `backend/tests/unit/test_video_job_repository.py`

**Interfaces:**
- Produces: `VideoJobRepository.create`, `get_by_id`, `claim_next`, `renew_lease`, `update_progress`, `request_cancel`, `complete`, `fail`, `mark_cancelled`, and `claim_expired_sources`.
- Produces: `VideoTrackRepository.replace_for_job`, `list_by_job`, and `list_by_face`.
- Produces: `Settings.video_*` values used by every later task.

- [ ] **Step 1: Write model and settings tests**

Add tests that instantiate `Settings` with environment overrides and assert defaults, then inspect
SQLAlchemy constraints for all required states:

```python
def test_video_settings_have_bounded_defaults(monkeypatch):
    monkeypatch.setenv("VIDEO_MAX_DURATION_SECONDS", "60")
    settings = Settings(_env_file=None)
    assert settings.video_max_duration_seconds == 60
    assert settings.video_default_frames_per_second > 0
    assert settings.video_job_lease_seconds > 0

def test_video_job_supports_required_states():
    sql = " ".join(str(item.sqltext) for item in VideoJob.__table__.constraints if hasattr(item, "sqltext"))
    for state in ("pending", "processing", "cancelling", "cancelled", "completed", "failed"):
        assert state in sql
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest backend/tests/unit/test_video_job_repository.py -q`

Expected: import failures for `VideoJob`, `VideoTrack`, and the repositories.

- [ ] **Step 3: Add explicit settings**

Add typed settings using these names and defaults:

```python
video_max_upload_bytes: int = 500 * 1024 * 1024
video_max_duration_seconds: int = 300
video_allowed_containers: str = "mp4,mov,avi,matroska"
video_allowed_codecs: str = "h264,hevc,mjpeg,mpeg4"
video_retention_seconds: int = 7 * 24 * 60 * 60
video_minio_prefix: str = "videos"
video_default_sampling_mode: str = "frames_per_second"
video_default_frames_per_second: float = 2.0
video_job_timeout_seconds: int = 1800
video_job_lease_seconds: int = 60
video_job_max_attempts: int = 3
video_progress_update_interval_seconds: float = 1.0
video_track_reconciliation_threshold: float = 0.60
video_appearance_max_gap_seconds: float = 1.5
video_worker_poll_seconds: float = 1.0
video_worker_gpu_id: int = 0
video_native_executable: str = "/workspace/build/pipeline/mvision_video_worker"
video_tracker_config_path: str = "/workspace/configs/video_tracker_nvdcf.yml"
video_pgie_config_path: str = "/workspace/configs/video_pgie_yolov8_face.txt"
video_preprocess_config_path: str = "/workspace/configs/video_preprocess_arcface.txt"
video_sgie_config_path: str = "/workspace/configs/video_sgie_arcface_r50.txt"
```

Expose parsed `video_allowed_container_set` and `video_allowed_codec_set` properties.

- [ ] **Step 4: Add database models and migration**

Add `details JSONB NOT NULL DEFAULT '{}'`, `video_recognize` process type, and `cancelled` process
status. Add `VideoJob` and `VideoTrack` exactly as specified in the design, using UUID strings,
timezone-aware timestamps, JSONB for sampling/metadata/appearances/detections, and indexes for
queue, lease, retention, job, and face queries. The migration must backfill `details` before
making it non-null and must not drop existing constraints until replacement constraints are
created in the same migration.

- [ ] **Step 5: Implement repository state transitions**

Use one atomic claim statement:

```python
stmt = (
    select(VideoJob)
    .where(
        VideoJob.status == "pending",
        VideoJob.available_at <= now,
        VideoJob.attempt_count < VideoJob.max_attempts,
    )
    .order_by(VideoJob.created_at)
    .with_for_update(skip_locked=True)
    .limit(1)
)
```

After selecting, assign `processing`, worker ID, lease token, expiry, and increment attempts in
the same transaction. Every lease-sensitive update filters by job ID, worker ID, and lease token.

- [ ] **Step 6: Run focused tests and migration SQL checks**

Run: `pytest backend/tests/unit/test_video_job_repository.py -q`

Run: `ruff check backend/app/config.py backend/app/infrastructure/database backend/tests/unit/test_video_job_repository.py`

Expected: all tests pass and Ruff reports no errors.

---

### Task 2: Implement Video Probe and MinIO Source Storage

**Files:**
- Create: `backend/app/infrastructure/video/__init__.py`
- Create: `backend/app/infrastructure/video/probe.py`
- Modify: `backend/app/infrastructure/object_storage/minio_adapter.py`
- Create: `backend/tests/unit/test_video_probe.py`
- Create: `backend/tests/unit/test_video_storage.py`

**Interfaces:**
- Produces: `VideoMetadata`, `async probe_video(path: Path, timeout_seconds: float) -> VideoMetadata`.
- Produces: `MinIOAdapter.upload_video`, `download_video`, `stat_video`, `read_video_range`, and `delete_video`.

- [ ] **Step 1: Write probe parsing and rejection tests**

Use a fake subprocess JSON payload and cover fraction FPS, rotation, missing video streams,
zero duration, timeout, and malformed output:

```python
def test_parse_probe_uses_display_dimensions_after_rotation():
    metadata = parse_probe_payload(PROBE_JSON_WITH_ROTATION_90)
    assert (metadata.width, metadata.height) == (1080, 1920)
    assert metadata.fps == pytest.approx(29.97, rel=1e-3)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest backend/tests/unit/test_video_probe.py backend/tests/unit/test_video_storage.py -q`

Expected: missing module and method failures.

- [ ] **Step 3: Implement bounded ffprobe execution**

Run `ffprobe -v error -show_streams -show_format -of json <path>` with
`asyncio.create_subprocess_exec` and `asyncio.wait_for`. Parse `avg_frame_rate`, fall back to
`r_frame_rate`, read rotation from side data/tags, require one video stream, and return:

```python
@dataclass(frozen=True)
class VideoMetadata:
    container: str
    codec: str
    duration_seconds: float
    fps: float
    width: int
    height: int
    total_frames: int
    rotation_degrees: int
```

- [ ] **Step 4: Add generic video object operations**

Validate keys with `^videos/[0-9a-f-]{36}/source$`. Stream files with `fput_object`/`fget_object`,
preserve SHA-256 metadata, implement range reads through `get_object(offset=..., length=...)`, and
close/release every MinIO response in `finally`.

- [ ] **Step 5: Run focused verification**

Run: `pytest backend/tests/unit/test_video_probe.py backend/tests/unit/test_video_storage.py -q`

Expected: all tests pass.

---

### Task 3: Implement Upload Service and Submit/Status Contracts

**Files:**
- Create: `backend/app/services/video_upload_service.py`
- Create: `backend/app/services/video_job_service.py`
- Create: `backend/app/presentation/schemas/videos.py`
- Create: `backend/app/presentation/routers/videos.py`
- Modify: `backend/app/presentation/dependencies.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/exceptions.py`
- Create: `backend/tests/unit/test_video_services.py`
- Create: `backend/tests/contract/test_videos_api.py`

**Interfaces:**
- Produces: `VideoUploadService.submit(video, sampling_mode, every_n_frames, frames_per_second, process_id)`.
- Produces: `VideoJobService.get`, `cancel`, `get_source`, and later `get_result`.
- Produces endpoints `POST /api/v1/videos/recognize`, `GET /api/v1/videos/jobs/{jobId}`, and `DELETE /api/v1/videos/jobs/{jobId}`.

- [ ] **Step 1: Write contract tests**

Assert `202`, camelCase fields, default sampling, stable validation codes, `404`, and idempotent
cancellation:

```python
def test_submit_video_returns_pending_job_urls():
    response = client().post(
        "/api/v1/videos/recognize",
        files={"video": ("clip.mp4", b"video", "video/mp4")},
        data={"samplingMode": "every_n_frames", "everyNFrames": "5"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["resultUrl"].endswith("/result")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest backend/tests/contract/test_videos_api.py backend/tests/unit/test_video_services.py -q`

Expected: missing router/service failures.

- [ ] **Step 3: Implement the upload transaction sequence**

Create the process first, stream at most `video_max_upload_bytes + 1`, reject empty/oversized
inputs, probe and validate metadata, upload `videos/{job_id}/source`, create the pending job, and
write sanitized process events. On failure, mark the process failed and delete temp/partial
objects best-effort.

- [ ] **Step 4: Implement schemas and routes**

Define `VideoSubmitResponse`, `VideoJobResponse`, `VideoMetadataResponse`, and cancellation
responses with the existing `ApiModel`. Extend service errors with explicit status/code support
for `VIDEO_*`, `JOB_NOT_FOUND`, and `JOB_NOT_COMPLETED`.

- [ ] **Step 5: Wire dependencies and router**

Extend `ServiceContainer` with video repositories/services and include `videos_router` in
`app.main`. Startup continues to ensure existing MinIO and Qdrant resources without deleting
anything.

- [ ] **Step 6: Run API/unit tests**

Run: `pytest backend/tests/contract/test_videos_api.py backend/tests/unit/test_video_services.py -q`

Expected: all tests pass.

---

### Task 4: Add the Video Native Protocol and Pure Aggregation Primitives

**Files:**
- Create: `backend/pipeline/include/mvision/video_protocol.hpp`
- Create: `backend/pipeline/src/video_protocol.cpp`
- Create: `backend/pipeline/tests/test_video_protocol.cpp`
- Create: `backend/app/infrastructure/video/protocol.py`
- Create: `backend/tests/unit/test_video_protocol.py`
- Modify: `backend/pipeline/CMakeLists.txt`

**Interfaces:**
- Produces native `VideoProgress`, `VideoTrackOutput`, `VideoCompleted`, `VideoFailed`, and `encode_video_event`.
- Produces Python `decode_video_event(frame: bytes) -> VideoEvent` with matching frozen dataclasses.

- [ ] **Step 1: Write cross-language shape tests**

Cover protocol version, event discriminator, 512-vector validation, bbox bounds, truncated frames,
oversized frames, binary representative JPEG, and completed counters.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest backend/tests/unit/test_video_protocol.py -q`

Expected: missing protocol module failure.

- [ ] **Step 3: Implement versioned MessagePack framing**

Use a four-byte network-order payload length followed by a map containing
`protocol_version=1` and `event_type`. Set a bounded 64 MiB event size. Reject non-finite floats,
embeddings not exactly 512 values, negative frame numbers, and invalid PTS.

- [ ] **Step 4: Add CMake targets and run both suites**

Run: `cmake --build build --target test_video_protocol && ctest --test-dir build -R video_protocol --output-on-failure`

Run: `pytest backend/tests/unit/test_video_protocol.py -q`

Expected: CTest and pytest pass.

---

### Task 5: Implement the Native DeepStream File Pipeline

**Files:**
- Create: `backend/pipeline/include/mvision/video_pipeline.hpp`
- Create: `backend/pipeline/src/video_pipeline.cpp`
- Create: `backend/pipeline/src/video_worker_main.cpp`
- Create: `backend/pipeline/tests/test_video_aggregation.cpp`
- Modify: `backend/pipeline/CMakeLists.txt`
- Create: `configs/video_tracker_nvdcf.yml`
- Create: `configs/video_pgie_yolov8_face.txt`
- Create: `configs/video_preprocess_arcface.txt`
- Create: `configs/video_sgie_arcface_r50.txt`

**Interfaces:**
- Produces CLI:
  `mvision_video_worker <video> <gpu-id> <sample-every-n> <width> <height> <total-frames> <tracker-config> <pgie-config> <preprocess-config> <sgie-config>`.
- Produces only framed protocol events on stdout; logs go to stderr.

- [ ] **Step 1: Write pure aggregation tests before GStreamer code**

Feed synthetic observations and assert stable tracker grouping, normalized mean embeddings,
appearance ordering, representative quality ties, empty video handling, and bbox clamping.

- [ ] **Step 2: Run native tests and verify RED**

Run: `cmake --build build --target test_video_aggregation`

Expected: missing video aggregation symbols.

- [ ] **Step 3: Implement the pipeline graph**

Build `uridecodebin -> nvvideoconvert -> capsfilter(NVMM) -> nvstreammux -> pgie -> nvtracker ->
nvdspreprocess -> sgie -> fakesink`. Link decode pads only for `video/*` with `memory:NVMM`.
Configure every element with container-local GPU ID `0`, dynamic display dimensions, non-live mux,
async disabled sink, and batch one for frame inference while SGIE retains face batching.

- [ ] **Step 4: Implement sampling and metadata probes**

Set PGIE interval to `sample_every_n - 1`. At tracker src, remove objects on frames where
`frame_num % sample_every_n != 0`. At SGIE src, walk frame/object metadata, require a valid tracker
ID, read the object's SGIE tensor meta, normalize 512 floats, and collect original-coordinate
bbox plus frame/PTS.

- [ ] **Step 5: Implement progress, EOS, error, and cancellation**

Watch the bus for EOS/error. Emit throttled progress events. SIGTERM sets an atomic cancel flag,
posts application shutdown to the GLib context, sets the pipeline to `GST_STATE_NULL`, and exits
with the dedicated cancelled code. Flush every accumulated track on EOS before `completed`.

- [ ] **Step 6: Verify native tests and compile warnings**

Run: `cmake --build build --target mvision_video_worker test_video_aggregation -j$(nproc)`

Run: `ctest --test-dir build -R 'video_(protocol|aggregation)' --output-on-failure`

Expected: build succeeds with `-Werror`; both tests pass.

---

### Task 6: Implement Cancellable Native Runner and Durable Worker Loop

**Files:**
- Create: `backend/app/infrastructure/video/native_runner.py`
- Create: `backend/app/worker/__init__.py`
- Create: `backend/app/worker/video_worker_main.py`
- Create: `backend/tests/unit/test_native_video_runner.py`
- Create: `backend/tests/unit/test_video_worker.py`

**Interfaces:**
- Produces: `NativeVideoRunner.run(job, local_path, on_event, cancellation_requested) -> NativeCompleted`.
- Produces: `process_one_job(worker_id: str, gpu_id: int) -> bool`.

- [ ] **Step 1: Write subprocess and worker state tests**

Use a short fake executable that emits framed progress/completed events. Assert incremental
decoding, stderr isolation, timeout SIGTERM/SIGKILL fallback, cancellation, lease renewal, retry,
and max-attempt failure.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest backend/tests/unit/test_native_video_runner.py backend/tests/unit/test_video_worker.py -q`

Expected: missing runner/worker failures.

- [ ] **Step 3: Implement the async native runner**

Use `asyncio.create_subprocess_exec`, read four-byte frames with `readexactly`, decode incrementally,
drain stderr concurrently into sanitized logs, and poll cancellation/timeout. Send SIGTERM once,
wait five seconds, then SIGKILL only if still alive.

- [ ] **Step 4: Implement claim/download/run loop**

Claim with lease, download source to a per-job temp directory, renew lease in a background task,
map progress events into throttled DB updates, pass track events to result processing, and always
remove local temp data. A stale lease must abort persistence.

- [ ] **Step 5: Run focused worker tests**

Run: `pytest backend/tests/unit/test_native_video_runner.py backend/tests/unit/test_video_worker.py -q`

Expected: all tests pass.

---

### Task 7: Reconcile Tracks, Resolve Identities, and Persist Results

**Files:**
- Create: `backend/app/services/video_tracking_service.py`
- Create: `backend/app/services/video_result_service.py`
- Modify: `backend/app/services/video_job_service.py`
- Create: `backend/tests/unit/test_video_tracking_service.py`
- Create: `backend/tests/unit/test_video_result_service.py`

**Interfaces:**
- Produces: `VideoTrackingService.reconcile(raw_tracks) -> list[CanonicalTrack]`.
- Produces: `VideoResultService.finalize(job, raw_tracks) -> dict`.

- [ ] **Step 1: Write deterministic reconciliation tests**

Cover non-overlap merge, overlap cannot-link, below-threshold split, chronological ordering,
gap-based appearance intervals, total duration, empty results, and stable tie ordering.

- [ ] **Step 2: Write identity outcome tests**

Use fakes for Qdrant and repositories. Assert known, existing anonymous, new anonymous, top-two
threshold behavior, overlapping-track duplicate prevention, one recognition result per canonical
track, and process completion.

- [ ] **Step 3: Run tests and verify RED**

Run: `pytest backend/tests/unit/test_video_tracking_service.py backend/tests/unit/test_video_result_service.py -q`

Expected: missing service failures.

- [ ] **Step 4: Implement reconciliation**

Normalize representative embeddings, sort tracklets by first frame, reject interval overlaps,
merge the highest cosine candidate at or above the configured threshold, then derive appearance
intervals using `video_appearance_max_gap_seconds`.

- [ ] **Step 5: Implement identity and persistence transaction**

Resolve each canonical track through the existing `FaceMatcher`. Use
`FaceSamplePersistenceService` for unmatched tracks with representative JPEG evidence, create a
`RecognitionResult`, build identity snapshots, then call `VideoTrackRepository.replace_for_job`.
Only after tracks persist successfully may the job/process become completed.

- [ ] **Step 6: Run focused tests**

Run: `pytest backend/tests/unit/test_video_tracking_service.py backend/tests/unit/test_video_result_service.py -q`

Expected: all tests pass.

---

### Task 8: Add Result, Source, Appearance, and Retention APIs

**Files:**
- Modify: `backend/app/presentation/schemas/videos.py`
- Modify: `backend/app/presentation/routers/videos.py`
- Modify: `backend/app/presentation/routers/faces.py`
- Modify: `backend/app/services/video_job_service.py`
- Modify: `backend/app/services/identity_service.py`
- Modify: `backend/app/infrastructure/database/repositories/video_job_repository.py`
- Modify: `backend/app/infrastructure/database/repositories/video_track_repository.py`
- Modify: `backend/tests/contract/test_videos_api.py`
- Create: `backend/tests/unit/test_video_retention.py`

**Interfaces:**
- Produces endpoints `GET /api/v1/videos/jobs/{jobId}/result`,
  `GET /api/v1/videos/jobs/{jobId}/video`, and
  `GET /api/v1/faces/{faceId}/appearances`.
- Produces: `VideoJobService.cleanup_expired_sources(limit: int) -> int`.

- [ ] **Step 1: Extend contract tests**

Assert `409 JOB_NOT_COMPLETED`, completed no-face output, full known/anonymous person fields,
appearances/detections, source bytes and range headers, unknown job `404`, expired source `410`,
and newest-first face appearances.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest backend/tests/contract/test_videos_api.py backend/tests/unit/test_video_retention.py -q`

Expected: missing routes and cleanup method failures.

- [ ] **Step 3: Implement result and appearance mapping**

Map persisted job/track snapshots into the exact camelCase requirements contract. Preserve
`name=null` and empty metadata for anonymous outcomes. Return every stored sampled detection.

- [ ] **Step 4: Implement retained source streaming**

Support a single RFC 7233 byte range, return `206` plus `Content-Range`/`Accept-Ranges`, return
full source as `200` without Range, and use `410 VIDEO_EXPIRED` after `source_deleted_at`.

- [ ] **Step 5: Implement retention sweep**

Claim expired source rows with `SKIP LOCKED`, delete each MinIO object, and mark deletion only
after success. Invoke a bounded sweep from the worker loop; leave result rows untouched.

- [ ] **Step 6: Run API and retention tests**

Run: `pytest backend/tests/contract/test_videos_api.py backend/tests/unit/test_video_retention.py -q`

Expected: all tests pass.

---

### Task 9: Package Three GPU Video Workers and Run End-to-End Verification

**Files:**
- Modify: `backend/pipeline/Dockerfile`
- Modify: `backend/Dockerfile`
- Modify: `backend/.env.example`
- Modify: `docker-compose.sprint01.yml`
- Modify: `backend/pyproject.toml` only if a required runtime package is missing.

**Interfaces:**
- Produces Compose services `video-worker-0`, `video-worker-1`, and `video-worker-2`.

- [ ] **Step 1: Package API validation dependencies**

Install `ffmpeg` in the API image so `ffprobe` is present. Keep the existing Alembic startup and
do not alter volume declarations.

- [ ] **Step 2: Package the native executable and Python worker**

Copy `mvision_video_worker`, shared libraries, backend Python package, models, and configs into
the DeepStream image. Set `PYTHONPATH=/workspace/backend` and invoke
`python -m app.worker.video_worker_main` per video-worker service.

- [ ] **Step 3: Add GPU-pinned Compose services**

Set `VIDEO_WORKER_GPU_ID=0` inside every GPU-isolated container because each container sees one
reserved device. Give each service a unique worker ID, Postgres/MinIO/Qdrant settings, nofile
limit 65536, and `restart: unless-stopped`. Do not mount or recreate data volumes.

- [ ] **Step 4: Run static and unit verification**

Run: `ruff check backend/app backend/tests`

Run: `mypy backend/app`

Run: `pytest backend/tests -q`

Run: `cmake --build build -j$(nproc) && ctest --test-dir build --output-on-failure`

Expected: all commands pass.

- [ ] **Step 5: Apply migration without resetting data**

Run: `docker compose -f docker-compose.sprint01.yml run --rm --no-deps api alembic upgrade head`

Expected: the Phase 2 revision applies; existing identity/sample counts remain unchanged.

- [ ] **Step 6: Start services and run real GPU smoke**

Run: `docker compose -f docker-compose.sprint01.yml up -d --build postgres minio qdrant gpu-worker-0 gpu-worker-1 gpu-worker-2 api video-worker-0 video-worker-1 video-worker-2`

Submit `tmp/face-recognition-deepstream/data/media/friends_s1e1_cut.mp4`, poll status, retrieve
result, and assert progress reaches 100, status is completed, boxes fit source dimensions, and
each person has a stable track ID plus detections.

- [ ] **Step 7: Run cancellation and restart recovery smoke tests**

Submit a video, cancel it while processing, and verify durable `cancelled`. Submit another job,
restart its video worker, wait for lease expiry/reclaim, and verify either completed or failed at
the configured attempt limit without duplicate tracks.

- [ ] **Step 8: Check Phase 1 regressions and data preservation**

Run the existing face API tests and one real image recognition request. Compare PostgreSQL face
identity/sample counts before and after migration and assert no pre-existing records disappeared.

## Plan Self-Review

- Every design section maps to a task: upload/probe/storage (2-3), schema/queue (1), native GPU
  path (4-5), worker/cancellation (6), aggregation/identity (7), results/history/retention (8),
  and deployment/verification (9).
- Public and internal names are consistent across tasks.
- Every implementation step names its concrete output.
- Native and Python boundaries use one explicit MessagePack protocol.
- Existing volumes and Phase 1 behavior have explicit regression checks.
