# Tek Kamera Livestream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Existing Mvision face pipeline'ini tek aktif RTSP kamera icin
guvenilir lifecycle, quality-gated track recognition, durable events,
observability ve annotate RTSP output ile calistirmak.

**Architecture:** FastAPI/PostgreSQL/Qdrant/object-storage control plane'i,
bir Python live supervisor uzerinden tek bir C++ DeepStream worker'i yonetir.
Native worker RTSP/NVDEC, detector, tracker, GPU alignment, ArcFace, OSD ve RTSP
output'u tasir; Python worker framed MessagePack ile gelen bounded track
evidence'i existing named-gallery voting ile cozer ve revision'li label
assignment'i geri gonderir.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, PostgreSQL 16,
Qdrant, S3-compatible private object storage, MessagePack, C++17, GStreamer
1.24.2, DeepStream 9.0, CUDA 13.0, TensorRT 10.16, GstRtspServer, pytest,
CTest, OpenTelemetry Python SDK/OTLP, OpenTelemetry Collector Contrib,
Prometheus, Loki, Tempo and Grafana.

## Global Constraints

- Kullanici Phase 2'nin tamamlandigini ve Phase 3 livestream'in aktif sonraki
  hareket oldugunu belirledi.
- Ilk milestone tam olarak bir aktif RTSP kameradir.
- Mevcut image/video endpoint, table, Qdrant collection ve identity lifecycle
  davranisi korunur.
- `face_id` global identity; native `track_id` run-local hareket identity'sidir.
- Named label bir track icinde immutable'dir; ambiguous sonuc Unknown kalir.
- Anonymous gallery named candidate'i baskilayamaz.
- Pad probe HTTP, PostgreSQL, Qdrant, object storage veya blocking IPC cagirmaz.
- Full decoded frame/tensor Python process'ine gecmez.
- RTSP URI argv, log, error, metric veya API response'a girmez.
- Queue'lar bounded ve policy'leri explicit olur.
- OpenTelemetry logs/traces, Prometheus, Collector, Loki, Tempo and provisioned
  Grafana are required milestone gates, not optional hosted services.
- C++ performs no OTLP/network export; Python owns bounded telemetry export and
  converts native semantic operation events into spans.
- No per-frame/detection/embedding/track spans. Telemetry never contains URI,
  host, credentials, person name, face ID, embedding or snapshot bytes.
- No Redis, Celery, Kafka, paid SaaS veya hosted model/export dependency.
- Existing volume/data destructive reset edilmez.
- Model, engine, threshold veya SGIE config kanitsiz degistirilmez.
- No-license upstream source kopyalanmaz; yalniz `ORACLE_ONLY` kullanilir.
- Upstream adaptation URL, commit, license ve degisiklikle kaydedilir.
- Her behavior RED test/reproducer ile baslar.
- Unit mock sonucu GPU/runtime PASS degildir.
- Git commit/push ancak kullanici ayrica isterse yapilir; plan task'lari commit
  yerine scope/evidence checkpoint'iyle biter.

## Source Evidence Frozen For This Plan

| Repository | Checkout | Plan icinde kullanilan bulgu |
|---|---|---|
| `Abdirayimov/multi-stream-face-recognition` | `fc885546f2c56de5e989dac38c39b97ca7d2ad31` | source lifecycle/backpressure problemi, batched evidence fikri, absolute threshold + top-2 margin |
| `Limitless-Blue/AI_Enhanced_Surveillance_System` | `48058b6dae1ef87fb4edd16db54926447f9621af` | camera start/stop contract, 5-frame buffer/cooldown/review fikirleri, initial quality metric adaylari |
| `wjli699/DeepStream-Multi-Stream-Video-Intelligence-Pipeline` | `001500fabc2784f1e2754cf6d45de37173f51aac` on `feat/phase3-reid` | PGIE->tracker->SGIE ordering, embedding coverage/norm probe, DONTWAIT/HWM semantics, immutable track assignment |
| `Ocel-Labs/Osprey` | `b1d81e870ebc9203522c3b60bb5e42fe1098cdea` | source factory/spot lifecycle, lock discipline, readiness, per-stream output topology |
| `iam-ajmunna/ha_meem_ai_surveillance` | `00081489369bb6bd150f47f04aa8d92b081af7ad` | temporal quality aggregation, track expiry, shadow percentile calibration |
| `NVIDIA-AI-IOT/deepstream_python_apps` | `8ad0349ed7a496fae35ebb21c350641727070b89` | DeepStream 9 RTSP-in/out skeleton, GstRtspServer, `--rtsp-ts`, source removal flush/release pattern |

## File Structure

### Native data plane

- Create `backend/pipeline/include/mvision/live_protocol.hpp`: shared command
  and event value types plus framing API.
- Create `backend/pipeline/src/live_protocol.cpp`: strict MessagePack
  encode/decode.
- Create `backend/pipeline/include/mvision/live_track_state.hpp`: quality,
  bounded evidence and immutable assignment types.
- Create `backend/pipeline/src/live_track_state.cpp`: deterministic evidence
  selection and expiry.
- Create `backend/pipeline/include/mvision/live_pipeline.hpp`: one-camera
  DeepStream lifecycle API.
- Create `backend/pipeline/src/live_pipeline.cpp`: ingest, inference, watchdog,
  OSD and output graph.
- Create `backend/pipeline/src/live_worker_main.cpp`: duplex protocol loop,
  writer queue and signal handling.
- Create `backend/pipeline/tools/inspect_live_runtime.cpp`: installed plugin
  and property inventory.
- Create `backend/pipeline/tools/smoke_live_pipeline.cpp`: local RTSP fixture
  metadata/teardown probe.
- Create `backend/pipeline/tests/test_live_protocol.cpp`: protocol parity and
  malformed frame tests.
- Create `backend/pipeline/tests/test_live_track_state.cpp`: quality/evidence
  and assignment state tests.
- Create `backend/pipeline/tests/test_live_lifecycle.cpp`: state transition,
  watchdog and idempotent close tests.
- Modify `backend/pipeline/CMakeLists.txt`: native libraries, tools, worker and
  tests.

### Python control plane

- Create `backend/app/infrastructure/live/protocol.py`: Python protocol types
  and strict codec.
- Create `backend/app/infrastructure/live/uri_cipher.py`: Fernet encryption,
  HMAC fingerprint and redaction.
- Create `backend/app/infrastructure/live/native_runner.py`: child process,
  duplex pipes and bounded queues.
- Create `backend/app/infrastructure/database/repositories/live_camera_repository.py`:
  camera desired state and queries.
- Create `backend/app/infrastructure/database/repositories/live_run_repository.py`:
  lease, generation and runtime state.
- Create `backend/app/infrastructure/database/repositories/live_event_repository.py`:
  idempotent event persistence and cursor pagination.
- Create `backend/app/services/live_camera_service.py`: camera commands and
  sanitized query behavior.
- Create `backend/app/services/live_identity_service.py`: live evidence
  adapter over existing named-gallery voting.
- Create `backend/app/services/live_event_service.py`: cooldown, snapshot and
  durable event orchestration.
- Create `backend/app/services/live_supervisor.py`: claim/renew/recover/run
  loop.
- Create `backend/app/worker/live_worker_main.py`: one supervisor process.
- Create `backend/app/presentation/schemas/cameras.py`: request/response types.
- Create `backend/app/presentation/controllers/cameras.py`: HTTP mapping only.
- Create `backend/app/presentation/routers/cameras.py`: camera/event/health
  routes.
- Create `backend/app/presentation/routers/live_events.py`: bounded WebSocket
  notification route.
- Create `backend/app/observability/live_metrics.py`: low-cardinality
  Prometheus collectors.
- Create `backend/app/observability/telemetry.py`: Python OpenTelemetry setup,
  context propagation, structured-log injection and bounded fail-open export.
- Modify `backend/app/config.py`, `backend/app/main.py`,
  `backend/app/presentation/dependencies.py`, database models/repository exports
  and object-storage adapter.

### Persistence, config and deployment

- Create `backend/alembic/versions/7d6f0b3a9c21_add_live_stream_tables.py`:
  additive `live_camera`, `live_camera_run`, `live_detection_event` schema.
- Create `configs/live_pgie_yolov8_face.txt`,
  `configs/live_preprocess_arcface.txt`,
  `configs/live_sgie_arcface_r50.txt`, and
  `configs/live_tracker_nvdcf.yml` only after compatibility tests identify
  justified differences from current video configs.
- Create `backend/tests/fixtures/rtsp/README.md`: deterministic local RTSP
  fixture generation/use, without committing generated media.
- Create `docker-compose.live.yml`: additive self-hosted live worker and test
  fixture profile.
- Create `docker-compose.observability.yml` and `configs/observability/`:
  Collector, Prometheus, Loki, Tempo, Grafana provisioning, dashboards and
  alert rules with isolated retention volumes.
- Create `docs/implementation/live-source-attribution.md`: source/commit/license
  and adaptation ledger.
- Modify `backend/.env.example`, `backend/pyproject.toml`, object storage configuration,
  `README.md`, and `docs/implementation/CURRENT_SPRINT.md`.

---

## Packet 1 - Compatibility and Contracts

### Task 1: Installed DeepStream Live Capability Gate

**Files:**
- Create: `backend/pipeline/tools/inspect_live_runtime.cpp`
- Create: `backend/pipeline/tests/test_live_runtime_contract.cpp`
- Create: `docs/implementation/live-source-attribution.md`
- Modify: `backend/pipeline/CMakeLists.txt`

**Interfaces:**
- Produces: `inspect_live_runtime` JSON with plugin factories, exact property
  types/defaults, DeepStream/GStreamer versions and GstRtspServer availability.
- Produces: frozen source-attribution rows used by every later task.
- Consumes: installed DeepStream 9 container only; no model/config mutation.

- [x] **Step 1: Record the RED runtime assertions**

Add `test_live_runtime_contract.cpp` that returns non-zero unless these element
factories exist:

```cpp
const std::array required{
    "nvurisrcbin", "nvvideoconvert", "nvstreammux", "nvinfer",
    "nvtracker", "nvdspreprocess", "nvdsosd", "nvv4l2h264enc",
    "h264parse", "rtph264pay", "udpsink"};
```

It must also call `g_object_class_find_property` for:

```cpp
const std::array source_properties{
    "uri", "latency", "drop-on-latency",
    "rtsp-reconnect-interval", "rtsp-reconnect-attempts"};
```

and fail when `gst_rtsp_server_new()` cannot be linked/constructed.

- [x] **Step 2: Run RED before adding the target**

Run:

```bash
cmake -S backend/pipeline -B build/pipeline
cmake --build build/pipeline --target test_live_runtime_contract
```

Expected: target-not-found failure.

- [x] **Step 3: Add the inspector and test target**

`inspect_live_runtime` must print one JSON object to stdout and diagnostics to
stderr. The JSON keys are exact:

```json
{
  "gstreamerVersion": "1.24.2",
  "deepstreamVersion": "9.0.0",
  "gstRtspServer": true,
  "elements": {},
  "nvurisrcbinProperties": {}
}
```

Link `gstreamer-rtsp-server-1.0` through `pkg_check_modules` and add CTest name
`live_runtime_contract`.

- [x] **Step 4: Run GREEN in the real GPU image**

Run:

```bash
docker compose -f docker-compose.sprint01.yml run --rm --no-deps video-worker-0 ./build/pipeline/test_live_runtime_contract
docker compose -f docker-compose.sprint01.yml run --rm --no-deps video-worker-0 ./build/pipeline/inspect_live_runtime
```

Expected: test exit `0`; JSON includes every required factory/property.

- [x] **Step 5: Freeze source usage**

Write one attribution row per six reference repositories with repository URL,
exact checkout, license classification, exact pattern used and exact behavior
rejected. No-license wjli/Ha-Meem rows are `ORACLE_ONLY`.

- [x] **Step 6: Scope checkpoint**

Run `git diff --check` and `git status --short`. Do not continue if any required
installed property is absent; record `BLOCKED` instead of emulating reconnect
with an unverified property.

### Task 2: Live Settings, URI Encryption and Redaction

**Files:**
- Create: `backend/app/infrastructure/live/__init__.py`
- Create: `backend/app/infrastructure/live/uri_cipher.py`
- Create: `backend/tests/unit/test_live_uri_cipher.py`
- Modify: `backend/app/config.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/.env.example`

**Interfaces:**
- Produces: `LiveUriCipher.encrypt(uri: str) -> str`.
- Produces: `LiveUriCipher.decrypt(ciphertext: str) -> SecretStr`.
- Produces: `LiveUriCipher.fingerprint(uri: str) -> str` using keyed HMAC-SHA256.
- Produces: `redact_live_text(value: str) -> str`.
- Consumes: `LIVE_URI_ENCRYPTION_KEYS` as comma-separated Fernet keys, newest
  first, and `LIVE_URI_FINGERPRINT_KEY` as a separate secret.

- [x] **Step 1: Write RED secret tests**

Tests must prove:

```python
def test_uri_round_trip_never_exposes_plaintext() -> None:
    cipher = LiveUriCipher([TEST_FERNET_KEY], TEST_HMAC_KEY)
    uri = "rtsp://alice:secret@10.0.0.12:554/live?token=hidden"
    encrypted = cipher.encrypt(uri)
    assert uri not in encrypted
    assert cipher.decrypt(encrypted).get_secret_value() == uri
    assert uri not in repr(cipher.decrypt(encrypted))


def test_redactor_removes_userinfo_query_and_host() -> None:
    text = "connect rtsp://alice:secret@10.0.0.12/live?token=hidden failed"
    assert redact_live_text(text) == "connect rtsp://[REDACTED] failed"
```

Also test invalid scheme, empty host, invalid Fernet key, tampered ciphertext,
stable fingerprint and different fingerprint keys.

- [x] **Step 2: Run RED**

Run `pytest backend/tests/unit/test_live_uri_cipher.py -q`.

Expected: import failure for missing module.

- [x] **Step 3: Add verified crypto dependency and settings**

Add a pinned compatible `cryptography` range after building it in the Python
3.12 image. Use `Fernet`/`MultiFernet`; the first key encrypts, every listed key
may decrypt. The upstream API was inspected at pyca/cryptography commit
`8f75811f8d3d87d918ea4b0f230ec733e04b01ea`.

Settings are:

```python
live_enabled: bool = False
live_uri_encryption_keys: SecretStr | None = None
live_uri_fingerprint_key: SecretStr | None = None
live_worker_gpu_id: int = 0
live_worker_id: str = "live-worker-0"
live_worker_poll_seconds: float = 1.0
live_worker_lease_seconds: int = 30
live_native_executable: str = "/workspace/build/pipeline/mvision_live_worker"
live_rtsp_output_host: str = "localhost"
live_rtsp_output_port: int = 8554
live_rtp_udp_port: int = 5400
```

If `live_enabled` is true and either secret is absent, settings validation
raises `LIVE_SECRET_CONFIGURATION_REQUIRED`.

- [x] **Step 4: Implement URI contract**

Accept only `rtsp`/`rtsps`, require hostname, reject control characters and
URIs above 4096 characters. Encode plaintext as UTF-8 bytes only inside
`encrypt`; convert decrypted bytes directly into `SecretStr`. Catch
`InvalidToken` and raise `LiveUriDecryptionError` without including token or
URI.

- [x] **Step 5: Run GREEN and secret scan**

Run:

```bash
pytest backend/tests/unit/test_live_uri_cipher.py -q
ruff check backend/app/infrastructure/live backend/tests/unit/test_live_uri_cipher.py backend/app/config.py
mypy backend/app/infrastructure/live backend/app/config.py
```

Expected: all pass and no test output contains `alice`, `secret`, `10.0.0.12`
or `hidden`.

- [x] **Step 6: Scope checkpoint**

Run `git diff --check` and inspect `git diff -- backend/pyproject.toml
backend/app/config.py backend/.env.example`. Confirm no generated key or real URI is
tracked.

### Task 3: Additive Camera, Run and Event Persistence

**Files:**
- Create: `backend/alembic/versions/7d6f0b3a9c21_add_live_stream_tables.py`
- Create: `backend/app/infrastructure/database/repositories/live_camera_repository.py`
- Create: `backend/app/infrastructure/database/repositories/live_run_repository.py`
- Create: `backend/app/infrastructure/database/repositories/live_event_repository.py`
- Create: `backend/tests/integration/persistence/test_live_repositories.py`
- Modify: `backend/app/infrastructure/database/models.py`
- Modify: `backend/app/infrastructure/database/repositories/__init__.py`

**Interfaces:**
- Produces: `LiveCameraRepository.create/get/list_active/set_desired/soft_delete`.
- Produces: `LiveRunRepository.claim/renew/update_state/update_metrics/finish`.
- Produces: `LiveEventRepository.create_once/list_page/get`.
- Consumes: existing UUIDv7 generator and async SQLAlchemy session pattern.

- [x] **Step 1: Write RED model/repository integration tests**

Tests against `_test` PostgreSQL must assert:

```python
camera = await cameras.create(session, name="north", uri_ciphertext="token", uri_fingerprint="fp")
run = await runs.claim(session, camera.camera_id, "worker-0", lease_token, now, 30)
assert run.generation == 1
assert run.runtime_state == "STARTING"
```

They must also prove:

- only one active row can have `desired_state='running'`;
- generation increments after a terminal run;
- stale lease token cannot update state or metrics;
- duplicate `(run_id, native_track_id, event_type)` returns existing event;
- cursor pagination is deterministic by `(occurred_at, event_id)`;
- soft-deleted camera is not claimable;
- downgrade removes only live tables/types/indexes.

- [x] **Step 2: Run RED**

Run:

```bash
pytest backend/tests/integration/persistence/test_live_repositories.py -q
```

Expected: missing model/repository failure.

- [x] **Step 3: Add exact migration**

Use `down_revision = "c21d7a1e4f02"`. Create:

```text
live_camera
live_camera_run
live_detection_event
```

Add a partial unique index that permits only one non-deleted running camera:

```sql
CREATE UNIQUE INDEX uq_live_single_running
ON live_camera (desired_state)
WHERE desired_state = 'running' AND deleted_at IS NULL;
```

Add unique constraints `(camera_id, generation)` and
`(run_id, native_track_id, event_type)`. Use JSONB defaults through server-side
`'{}'::jsonb`; do not rewrite prior migrations.

- [x] **Step 4: Add strict models and fenced repositories**

Every run mutation includes:

```text
WHERE run_id = :run_id
  AND worker_id = :worker_id
  AND lease_token = :lease_token
  AND lease_expires_at > :now
```

Repository methods call `flush()` but never `commit()`/`rollback()`.
`claim()` executes the equivalent of this exact selection and atomically
inserts the next generation:

```sql
SELECT camera_id
FROM live_camera
WHERE desired_state = 'running' AND deleted_at IS NULL
ORDER BY updated_at, camera_id
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

- [x] **Step 5: Verify migration and repository GREEN**

Run against isolated stores:

```bash
alembic upgrade head
alembic current
pytest backend/tests/integration/persistence/test_live_repositories.py -q
```

Expected: Alembic head `7d6f0b3a9c21`; tests pass.

- [x] **Step 6: Verify downgrade/upgrade on a disposable test DB**

Run `alembic downgrade c21d7a1e4f02` then `alembic upgrade head` only against
the `_test` database. Expected: existing Phase 1/2 tables and rows remain.

- [x] **Step 7: Scope checkpoint**

Run `git diff --check` and inspect migration SQL. Confirm production database,
Qdrant collection and object buckets were not touched.

### Task 4: Camera API and Durable Desired State

**Files:**
- Create: `backend/app/presentation/schemas/cameras.py`
- Create: `backend/app/presentation/controllers/cameras.py`
- Create: `backend/app/presentation/routers/cameras.py`
- Create: `backend/app/services/live_camera_service.py`
- Create: `backend/tests/contract/test_cameras_api.py`
- Create: `backend/tests/unit/test_live_camera_service.py`
- Modify: `backend/app/presentation/dependencies.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/exceptions.py`

**Interfaces:**
- Produces: endpoints listed in the design API table.
- Produces: `LiveCameraService.register/list/get/start/stop/delete/events/snapshot`.
- Consumes: URI cipher and camera/run/event repositories.

- [x] **Step 1: Write RED API contract tests**

Create requests for registration, list, get, start, repeated start, stop,
delete, events and health. Assert every response lacks all URI components:

```python
body = response.text
for forbidden in ("rtsp://", "alice", "secret", "10.0.0.12", "token="):
    assert forbidden not in body
```

Assert a concurrent second-camera start maps the database invariant to:

```json
{"error":{"code":"LIVE_CAMERA_LIMIT_REACHED"}}
```

with HTTP `409`.

- [x] **Step 2: Run RED**

Run `pytest backend/tests/contract/test_cameras_api.py backend/tests/unit/test_live_camera_service.py -q`.

Expected: missing router/service failures.

- [x] **Step 3: Add schemas and service**

Public camera response fields are exact:

```python
cameraId: UUID
name: str
desiredState: Literal["stopped", "running"]
runtimeState: Literal["STOPPED", "STARTING", "ACTIVE", "RECONNECTING", "STOPPING", "FAILED"]
outputUrl: str | None
createdAt: datetime
updatedAt: datetime
```

No schema contains `uri`, `rtsp_uri`, `uri_ciphertext` or fingerprint.
Registration encrypts before repository create. Start/stop only write desired
state; they never report ACTIVE without a native state event.

- [x] **Step 4: Keep presentation boundaries strict**

Router wires dependencies and paths. Controller maps schema/service errors.
Service owns transactions and lifecycle decisions. Controller/router must not
import SQLAlchemy, Qdrant, MinIO or native runner modules.

- [x] **Step 5: Run GREEN**

Run:

```bash
pytest backend/tests/contract/test_cameras_api.py backend/tests/unit/test_live_camera_service.py -q
ruff check backend/app/presentation backend/app/services/live_camera_service.py backend/tests/contract/test_cameras_api.py
mypy backend/app/presentation backend/app/services/live_camera_service.py
```

Expected: all pass; OpenAPI includes camera endpoints and no secret field.

- [x] **Step 6: Scope checkpoint**

Run `git diff --check` and verify existing faces/videos contract tests remain
unchanged and pass.

---

## Packet 2 - Protocol and Native Track State

### Task 5: Duplex MessagePack Protocol Parity

**Files:**
- Create: `backend/pipeline/include/mvision/live_protocol.hpp`
- Create: `backend/pipeline/src/live_protocol.cpp`
- Create: `backend/pipeline/tests/test_live_protocol.cpp`
- Create: `backend/app/infrastructure/live/protocol.py`
- Create: `backend/tests/unit/test_live_protocol.py`
- Create: `backend/tests/contract/test_live_protocol_parity.py`
- Modify: `backend/pipeline/CMakeLists.txt`

**Interfaces:**
- Produces C++/Python codecs for `StartCommand`, `IdentityAssignment`,
  `StopCommand`, `HelloEvent`, `StateEvent`, `OutputReadyEvent`,
  `TrackEvidenceEvent`, `TrackExpiredEvent`, `MetricsEvent`, `FailedEvent`, and
  `StoppedEvent`.
- Framing: unsigned 32-bit network-order length plus MessagePack map.
- Maximum command/event frame: `4 MiB`; maximum aligned JPEG: `512 KiB`.

- [x] **Step 1: Write RED Python and C++ malformed-frame tests**

Cover truncated header/body, payload over 4 MiB, unknown protocol/message type,
invalid UUID, wrong generation, non-finite metric, embedding length not 512,
norm outside `[0.99, 1.01]`, landmarks length not 10, snapshot over 512 KiB,
and out-of-order assignment revision.

Canonical header map:

```python
{
    "protocol_version": 1,
    "message_type": "state",
    "camera_id": "019b0000-0000-7000-8000-000000000001",
    "run_id": "019b0000-0000-7000-8000-000000000002",
    "generation": 1,
    "sequence": 7,
}
```

- [x] **Step 2: Run RED**

Run:

```bash
pytest backend/tests/unit/test_live_protocol.py backend/tests/contract/test_live_protocol_parity.py -q
cmake --build build/pipeline --target test_live_protocol
```

Expected: Python import and CMake target failures.

- [x] **Step 3: Implement Python strict codec**

Use frozen dataclasses and one `LiveMessage` union. Decode maps unknown/missing
keys to stable `ValueError` codes. Preserve embeddings as tuples, JPEG as
bytes, and timestamps as integer nanoseconds. Never accept bool as integer.

- [x] **Step 4: Implement C++ strict codec**

Use `std::variant` for commands/events, `std::array<float, 512>` for embedding,
`std::array<float, 10>` for landmarks and `std::vector<std::byte>` for bounded
JPEG. Validate before constructing the variant.

- [x] **Step 5: Add cross-language golden frames**

The parity test launches a tiny native codec executable, sends Python-encoded
commands, and decodes native events. Compare every field and byte payload; do
not compare only message type.

- [x] **Step 6: Run GREEN**

Run:

```bash
cmake --build build/pipeline --target test_live_protocol
./build/pipeline/test_live_protocol
pytest backend/tests/unit/test_live_protocol.py backend/tests/contract/test_live_protocol_parity.py -q
```

Expected: all pass.

- [x] **Step 7: Scope checkpoint**

Run `git diff --check`; verify current image/video protocol files were not
changed to perpetual/live semantics.

### Task 6: Quality Metrics and Bounded Track Evidence

**Files:**
- Create: `backend/pipeline/include/mvision/live_track_state.hpp`
- Create: `backend/pipeline/src/live_track_state.cpp`
- Create: `backend/pipeline/tests/test_live_track_state.cpp`
- Modify: `backend/pipeline/CMakeLists.txt`

**Interfaces:**
- Produces: `QualityMeasurement`, `LiveObservation`, `TrackEvidenceBank`,
  `IdentityAssignmentState`.
- Produces: `TrackEvidenceBank::consider(const LiveObservation&) -> EvidenceChange`.
- Produces: `IdentityAssignmentState::apply(const IdentityAssignment&) -> bool`.
- Consumes: compact source-space metadata and normalized embeddings only.

- [x] **Step 1: Write RED deterministic evidence tests**

Tests cover:

```cpp
TrackEvidenceBank bank(/*capacity=*/10, /*min_spacing_ns=*/200'000'000);
bank.consider(low_quality);
bank.consider(higher_quality_same_time_and_view);
assert(bank.observations().size() == 1);
assert(bank.observations().front().quality_score ==
       higher_quality_same_time_and_view.quality_score);
```

Also assert:

- capacity never exceeds 10;
- non-finite/wrong-norm embedding is rejected;
- bbox/landmarks outside configured tolerance receive a reject mask;
- time-spaced different views can coexist;
- tie breaks by earlier timestamp then detection ordinal;
- expired bank releases JPEG/vector capacity;
- `Pending -> Known(A)` succeeds;
- `Known(A) -> Known(B)` and `Known -> Unknown` fail;
- stale assignment revision fails.

- [x] **Step 2: Run RED**

Run `cmake --build build/pipeline --target test_live_track_state`.

Expected: target-not-found failure.

- [x] **Step 3: Implement hard validation and shadow quality**

Hard rejects are only invalid geometry, invalid embedding, impossible
landmarks and configured safety bounds. Detector confidence, face side,
clipping, pose, brightness and sharpness each produce a metric plus reject bit.
`shadow_mode=true` records candidate reject bits but does not exclude those
observations except hard rejects.

The quality score is deterministic:

```text
detector_confidence
* clamp(sqrt(face_area/frame_area) / target_area_ratio, 0, 1)
* pose_weight
* exposure_weight
* sharpness_weight
```

All weights are clamped `[0,1]`; no identity cosine score enters this value.

- [x] **Step 4: Implement bounded replacement**

Pre-reserve capacity 10. For a near-time/near-pose observation, replace only
when its score is greater. At capacity, replace the lowest score only when the
new sample also increases pose diversity or exceeds it by the configured
replacement margin. No unbounded map/vector grows per frame.

- [x] **Step 5: Run GREEN and sanitizer test**

Run:

```bash
cmake --build build/pipeline --target test_live_track_state
./build/pipeline/test_live_track_state
```

Then build this target with ASan/UBSan in a separate disposable build directory
and run 100,000 synthetic observations. Expected: constant bank capacity, no
sanitizer finding.

- [x] **Step 6: Scope checkpoint**

Run `git diff --check`; ensure borrowed thresholds are config values marked
shadow candidates, not universal constants.

### Task 6A: W3C Trace Context and Native Operation Protocol

This approved observability amendment must complete before Task 7 so the native
pipeline is not retrofitted after its protocol boundary ships.

**Files:**
- Modify: `backend/app/infrastructure/live/protocol.py`
- Modify: `backend/pipeline/include/mvision/live_protocol.hpp`
- Modify: `backend/pipeline/src/live_protocol.cpp`
- Modify: `backend/pipeline/tests/test_live_protocol.cpp`
- Modify: `backend/tests/unit/test_live_protocol.py`
- Modify: `backend/tests/contract/test_live_protocol_parity.py`
- Modify: `docs/implementation/live-source-attribution.md`

**Interfaces:**
- Extends `ProtocolHeader` with `traceparent: str` and
  `tracestate: str | None`.
- Adds `NativeOperationEvent` to `LiveMessage` with one completed bounded native
  operation record.
- Produces `validate_trace_context(traceparent: str, tracestate: str | None)` in
  both codecs without importing an OpenTelemetry SDK.
- Consumes W3C Trace Context; native events echo the validated Start context.

- [x] **Step 1: Write RED trace-context and native-operation tests**

Python and C++ tests must accept this canonical context:

```text
traceparent=00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
tracestate=vendor=value
```

Reject uppercase/short/all-zero trace or span IDs, unsupported traceparent
version, malformed flags, tracestate over 512 bytes and more than 32 members.
Reject a native operation unless:

```text
operation in source_connect|first_frame|reconnect|graph_rebuild|
             inference_window|output_start|output_stop|teardown
status in ok|error
ended_monotonic_ns >= started_monotonic_ns
error status has a stable error_code
attributes has <= 16 entries
attribute key in attempt|reason|state|outcome|batch_size|object_count
attribute value is finite numeric or allowlisted enum string
```

- [x] **Step 2: Run RED**

Run:

```bash
pytest backend/tests/unit/test_live_protocol.py backend/tests/contract/test_live_protocol_parity.py -q
cmake --build build/pipeline --target test_live_protocol
./build/pipeline/test_live_protocol
```

Expected: constructor/import/compiler failures for absent trace fields and
`NativeOperationEvent`.

- [x] **Step 3: Implement strict Python types and validation**

Add frozen dataclass:

```python
@dataclass(frozen=True)
class NativeOperationEvent:
    header: ProtocolHeader
    operation: Literal[
        "source_connect", "first_frame", "reconnect", "graph_rebuild",
        "inference_window", "output_start", "output_stop", "teardown",
    ]
    started_monotonic_ns: int
    ended_monotonic_ns: int
    status: Literal["ok", "error"]
    error_code: str | None
    attributes: dict[str, str | int | float]
```

Validate fields before constructing the dataclass. Never accept bool as an
integer or metric value. Preserve unknown/missing-field stable error codes.

- [x] **Step 4: Implement matching C++ value type**

Add `NativeOperationEvent` to the `std::variant`; attributes use:

```cpp
using NativeAttribute = std::variant<std::string, std::int64_t, double>;
std::map<std::string, NativeAttribute> attributes;
```

No OpenTelemetry C++ dependency is introduced. Encoding/decoding remains
MessagePack-only and validates before variant construction.

- [x] **Step 5: Extend cross-language parity**

Python sends Start with canonical trace context. Native echoes that context in
Hello/Evidence/Stopped and emits one `NativeOperationEvent`. Compare every
trace field, timestamp, status, error code, attribute key/type/value and payload
byte; no substring-only assertions.

- [x] **Step 6: Run GREEN**

Run the Task 5 native build and mounted parity executable, then:

```bash
pytest backend/tests/unit/test_live_protocol.py backend/tests/contract/test_live_protocol_parity.py -q
ruff check backend/app/infrastructure/live/protocol.py backend/tests/unit/test_live_protocol.py backend/tests/contract/test_live_protocol_parity.py
mypy backend/app/infrastructure/live/protocol.py
```

Expected: all pass under native `-Werror`; existing Start/Assignment/Stop and
event golden fields remain unchanged except the two deliberate header fields.

- [x] **Step 7: Scope checkpoint**

Run `git diff --check`. Confirm no OpenTelemetry SDK/network client enters C++,
no trace value is a metric/Loki label, and current image/video protocol files
remain unchanged.

---

## Packet 3 - Native One-Camera Pipeline

### Task 7: Real RTSP Ingest and Existing Inference Chain

**Files:**
- Create: `backend/pipeline/include/mvision/live_pipeline.hpp`
- Create: `backend/pipeline/src/live_pipeline.cpp`
- Create: `backend/pipeline/tools/smoke_live_pipeline.cpp`
- Create: `backend/tests/fixtures/rtsp/README.md`
- Create: `backend/tests/fixtures/rtsp/server.py`
- Create only after A/B evidence: `configs/live_pgie_yolov8_face.txt`
- Create only after A/B evidence: `configs/live_preprocess_arcface.txt`
- Create only after A/B evidence: `configs/live_sgie_arcface_r50.txt`
- Create only after A/B evidence: `configs/live_tracker_nvdcf.yml`
- Modify: `backend/pipeline/CMakeLists.txt`

**Interfaces:**
- Produces: `LivePipeline::start(const LivePipelineOptions&)`.
- Produces: `LivePipeline::apply_assignment(const IdentityAssignment&)`.
- Produces: `LivePipeline::stop(StopReason)` and idempotent `close()`.
- Emits state, output, evidence, metrics, native-operation, failure and stopped
  callbacks into a bounded native queue.

- [x] **Step 1: Create deterministic RTSP fixture instructions**

Use an existing local test video and GStreamer RTSP server in an isolated test
profile. The fixture loops the file, publishes H.264 at
`rtsp://rtsp-fixture:8555/friends`, and never stores credentials. Generated
fixture media remains Git-ignored.

- [x] **Step 2: Write the RED smoke expectations**

`smoke_live_pipeline` receives URI via stdin, not argv. It exits non-zero unless
within the configured deadline it observes:

```text
STARTING -> ACTIVE
decoded_frames > 0
tracked_objects > 0
embedding_count > 0
embedding_count + missing_embedding_count == eligible_object_count
every embedding dimension == 512
every embedding finite and norm in [0.99, 1.01]
source_connect + first_frame + sampled inference_window operation records
```

It emits only sanitized counters to stdout/stderr.

- [x] **Step 3: Run RED**

Run:

```bash
cmake --build build/pipeline --target smoke_live_pipeline
```

Expected: target-not-found failure.

- [ ] **Step 4: Build the single-camera graph**

Construct and check every factory/link result for:

```text
nvurisrcbin -> queue -> nvvideoconvert -> nvstreammux
-> current YOLOv8-Face PGIE -> NvDCF
-> current nvdspreprocess GPU alignment -> current ArcFace SGIE
```

Use `batch-size=1`, `live-source=1`, configured dimensions and GPU ID. Preserve
the current parser, engine, landmark mapping and ArcFace preprocess contract.
Never construct source with `cv2.VideoCapture`, FFmpeg CLI or CPU decode.

- [ ] **Step 5: Prove SGIE config parity before copying configs**

Run current video config and each candidate change separately. Record:

```text
eligible objects
objects with embedding
missing embedding count
embedding norm min/max/mean
pipeline warnings/errors
tracker ID switches on the same fixture window
```

Only create `live_*.txt/yml` when a measured live-specific difference is
required. A candidate must not reduce embedding coverage or change embedding
cosine parity beyond tolerance. Specifically test `network-type`,
`operate-on-gie-id`, `secondary-reinfer-interval` and NvDCF visual mode one at
a time.

- [ ] **Step 6: Run real GPU smoke**

Run the fixture and native smoke in the DeepStream image. Expected: ACTIVE,
finite normalized embeddings, original-coordinate bbox/landmarks and exit `0`
after a bounded stop.

- [ ] **Step 7: Regression gate**

Run existing native tests:

```bash
./build/pipeline/test_video_protocol
./build/pipeline/test_video_aggregation
./build/pipeline/test_face_alignment
LD_LIBRARY_PATH=build/pipeline ./build/pipeline/test_yolo_face_parser
```

Expected: all pass unchanged.

- [ ] **Step 8: Scope checkpoint**

Record A/B raw summaries in the sprint evidence. Do not publish NVIDIA
performance comparisons without checking applicable NVIDIA license terms.

### Task 8: Watchdog, Reconnect and Idempotent Teardown

**Files:**
- Create: `backend/pipeline/tests/test_live_lifecycle.cpp`
- Modify: `backend/pipeline/include/mvision/live_pipeline.hpp`
- Modify: `backend/pipeline/src/live_pipeline.cpp`
- Modify: `backend/pipeline/tools/smoke_live_pipeline.cpp`

**Interfaces:**
- Produces lifecycle transitions `STARTING`, `ACTIVE`, `RECONNECTING`,
  `STOPPING`, `STOPPED`, `FAILED`.
- Produces frame watchdog using monotonic clock and interruptible backoff.
- Consumes installed `nvurisrcbin` reconnect properties proven in Task 1.

- [ ] **Step 1: Write RED state-machine tests**

Use a fake monotonic clock and transition sink. Assert:

```text
start + first frame             STARTING -> ACTIVE
stale frame                     ACTIVE -> RECONNECTING
new valid frame                 RECONNECTING -> ACTIVE
rebuild budget exhausted        RECONNECTING -> FAILED
stop from every non-terminal    state -> STOPPING -> STOPPED
double stop/close               no duplicate terminal callback/crash
```

Assert invalid transitions throw internally and emit one sanitized failure.

- [ ] **Step 2: Run RED**

Run `cmake --build build/pipeline --target test_live_lifecycle`.

Expected: target-not-found failure.

- [ ] **Step 3: Implement two-layer recovery**

Set verified `nvurisrcbin` reconnect properties. The watchdog checks
`now_monotonic - last_frame_monotonic`; after stale threshold it emits
RECONNECTING. If plugin recovery deadline expires, stop and rebuild the graph
with bounded exponential backoff and jitter. Stop must interrupt wait through
a condition variable.

Emit completed `reconnect` and `graph_rebuild` native operation records with
only attempt/reason/outcome allowlisted attributes. Never include source URI,
host, raw GStreamer error or a span per reconnect poll.

- [ ] **Step 4: Implement complete teardown ownership**

In this order:

```text
reject new evidence
signal queue shutdown
set pipeline GST_STATE_NULL with bounded wait
remove probes and bus watch
send flush_stop to mux sink pad
release requested mux pad
remove GstRtspServer mount when present
release UDP port/socket
join watchdog and writer threads
unref GStreamer objects once
clear track/assignment maps
```

Partial-construction failure follows the same idempotent close path.

- [ ] **Step 5: Run lifecycle GREEN**

Run `./build/pipeline/test_live_lifecycle`. Expected: all transition and double
close tests pass.

- [ ] **Step 6: Fault-inject the real RTSP source**

Start fixture, pause/stop it, restart it, then issue stop during reconnect.
Expected observed sequence contains RECONNECTING and returns ACTIVE after
source recovery; stop during backoff reaches STOPPED inside shutdown deadline.

- [ ] **Step 7: Repeat teardown**

Run 50 start/stop cycles and record process fd/thread count plus GPU memory
before/after. Any monotonic resource growth blocks the packet.

- [ ] **Step 8: Scope checkpoint**

Run `git diff --check` and record exact source removal/release behavior adapted
from NVIDIA/Osprey, including local differences.

### Task 9: Native Worker Process and Non-Blocking Writer

**Files:**
- Create: `backend/pipeline/src/live_worker_main.cpp`
- Create: `backend/pipeline/tests/test_live_worker_process.cpp`
- Modify: `backend/pipeline/CMakeLists.txt`

**Interfaces:**
- Produces executable `mvision_live_worker <gpu_id>`; no URI argument.
- Reads framed commands from stdin and writes framed events to stdout.
- Writes sanitized diagnostics only to stderr.
- Owns bounded queues with reserved control-event capacity.

- [ ] **Step 1: Write RED process tests**

Launch the worker with pipes. Assert:

- no Start command -> bounded idle waiting, no pipeline;
- valid Start -> Hello then STARTING;
- malformed frame -> stable failed event and non-zero exit;
- stale assignment -> rejected counter, worker remains alive;
- Stop -> STOPPING, STOPPED, exit `0`;
- SIGTERM follows same close path;
- stdout contains only framed bytes;
- provided RTSP URI is absent from `/proc/<pid>/cmdline` and captured stderr.

- [ ] **Step 2: Run RED**

Run `cmake --build build/pipeline --target test_live_worker_process`.

Expected: target-not-found failure.

- [ ] **Step 3: Implement queue policy**

Use fixed maximum capacities:

```text
control events: 32 reserved slots, never coalesced
track evidence: 256 track keys, latest highest-quality revision per key
metrics: one replaceable pending sample
native operations: 64 completed records, oldest telemetry record dropped first
assignments: latest revision per tracker key
```

The GStreamer probe calls `try_enqueue`; one writer thread encodes/writes. A
full evidence queue increments a drop/coalesce counter and returns immediately.
Native-operation saturation drops telemetry only and increments its metric; it
cannot consume the 32 reserved control slots.
Broken stdout pipe triggers controlled FAILED/close, not SIGPIPE termination.

- [ ] **Step 4: Implement command loop and generation checks**

Accept exactly one Start per process. Every later command must match
camera/run/generation. Stop is always honored when header is valid, including
during reconnect. Identity assignment is handed to `LivePipeline` without
touching GStreamer from the reader thread; apply it through the main context.

- [ ] **Step 5: Run GREEN and saturation test**

Run `./build/pipeline/test_live_worker_process`, then inject 10,000 synthetic
evidence updates with a stalled stdout consumer. Expected: queue remains
bounded, control stop is delivered, no probe thread blocks.

- [ ] **Step 6: Scope checkpoint**

Run `git diff --check`; inspect process arguments and every diagnostic line for
URI/credential exposure.

---

## Packet 4 - Python Supervisor and Identity

### Task 10: Python Native Runner, Lease and Recovery Supervisor

**Files:**
- Create: `backend/app/infrastructure/live/native_runner.py`
- Create: `backend/app/services/live_supervisor.py`
- Create: `backend/app/worker/live_worker_main.py`
- Create: `backend/tests/unit/test_live_native_runner.py`
- Create: `backend/tests/unit/test_live_supervisor.py`
- Modify: `backend/app/presentation/dependencies.py`

**Interfaces:**
- Produces: `NativeLiveRunner.run(start, on_event, commands) -> StoppedEvent`.
- Produces: `LiveSupervisor.process_one_camera(worker_id: str) -> bool`.
- Consumes: encrypted URI, fenced run lease, strict live protocol.

- [ ] **Step 1: Write RED runner tests**

Use a fake executable to prove:

- process argv is exactly executable plus GPU ID;
- URI is sent only in the framed Start command;
- stdout reader decodes events in sequence;
- stderr passes through `redact_live_text`;
- assignment queue coalesces by tracker/revision;
- Stop interrupts event wait;
- exit `0` without Stopped event is failure;
- non-zero exit maps to sanitized `LIVE_PIPELINE_ERROR`.

- [ ] **Step 2: Write RED supervisor tests**

Prove claim, lease renewal, desired-stop, stale lease, crash retry, generation
increment and API-independent behavior. A stale worker must terminate its child
and must not update the newer run.

- [ ] **Step 3: Run RED**

Run:

```bash
pytest backend/tests/unit/test_live_native_runner.py backend/tests/unit/test_live_supervisor.py -q
```

Expected: missing modules.

- [ ] **Step 4: Implement runner without secret argv/env**

Spawn:

```python
await asyncio.create_subprocess_exec(
    settings.live_native_executable,
    str(settings.live_worker_gpu_id),
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

Write Start after spawn. Use one reader task, one command writer task and one
redacted stderr drain task. Queue sizes come from settings and are bounded.

- [ ] **Step 5: Implement supervisor transaction boundaries**

Flow is exact:

```text
claim desired running camera + insert STARTING run + commit
decrypt URI in memory
start lease renewal task
run native child
persist each state/metrics event with lease fencing
desired stopped -> enqueue Stop
stale/lost lease -> terminate child and abandon mutations
terminal event -> finish run + commit
exception -> finish FAILED or release for bounded retry + commit
always cancel/join lease task and clear plaintext reference
```

- [ ] **Step 6: Add worker main**

One loop calls `process_one_camera`, sleeps only when no claim exists, handles
SIGTERM, and exits after stopping the current child. It does not run inside the
FastAPI process.

- [ ] **Step 7: Run GREEN**

Run:

```bash
pytest backend/tests/unit/test_live_native_runner.py backend/tests/unit/test_live_supervisor.py -q
ruff check backend/app/infrastructure/live backend/app/services/live_supervisor.py backend/app/worker/live_worker_main.py
mypy backend/app/infrastructure/live backend/app/services/live_supervisor.py backend/app/worker/live_worker_main.py
```

Expected: all pass.

- [ ] **Step 8: Scope checkpoint**

Inspect process command, environment, exception messages and logs with a test
URI. Confirm no plaintext survives outside the Start frame/in-memory secret.

### Task 11: Live Identity Voting, Cooldown and Durable Events

**Files:**
- Create: `backend/app/services/live_identity_service.py`
- Create: `backend/app/services/live_event_service.py`
- Create: `backend/tests/unit/test_live_identity_service.py`
- Create: `backend/tests/unit/test_live_event_service.py`
- Create: `backend/tests/integration/services/test_live_event_persistence.py`
- Modify: `backend/app/services/live_supervisor.py`
- Modify: `backend/app/infrastructure/object_storage/minio_adapter.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- Produces: `LiveIdentityService.resolve(event: TrackEvidenceEvent) -> LiveIdentityDecision`.
- Produces: `LiveEventService.accept_decision(camera_id: str, run_id: str, generation: int, evidence: TrackEvidenceEvent, decision: LiveIdentityDecision) -> IdentityAssignment`.
- Produces: `LiveEventService.expire_track(camera_id: str, run_id: str, generation: int, event: TrackExpiredEvent) -> IdentityAssignment | None`.
- Produces object-storage methods `upload_live_snapshot`, `get_live_snapshot`,
  `stat_live_snapshot`.
- Consumes: existing `VideoIdentityVotingService`, `FaceMatcher`, active
  PostgreSQL identity validation and strict event repository.

- [ ] **Step 1: Write RED identity tests using current Friends rules**

Cases:

```text
one strong named vote                     Known
two moderate consistent named votes       Known
winner below absolute threshold           Unknown/Pending
winner-runner margin below 0.05            Unknown/Pending
anonymous candidate higher than named      anonymous ignored
inactive named identity                    Unknown/Pending
Known(A) then evidence for B                remains Known(A)
```

Assert `nearest_known_score` is retained for audit even when assignment is
Unknown.

- [ ] **Step 2: Write RED event/cooldown tests**

Prove:

- Known decision persists one event and one snapshot;
- same `(run, track, known)` retry returns the existing event;
- same face/camera inside cooldown suppresses a fragment event and increments
  suppression count;
- Unknown is not persisted before minimum dwell and track expiry;
- expired stable Unknown persists with `face_id=None`;
- snapshot failure records `snapshot_status='failed'` and never fabricates an
  object key;
- DB failure sends no WebSocket notification and no success assignment;
- Qdrant failure produces Unknown/Pending, never guessed Known.

- [ ] **Step 3: Run RED**

Run:

```bash
pytest backend/tests/unit/test_live_identity_service.py backend/tests/unit/test_live_event_service.py backend/tests/integration/services/test_live_event_persistence.py -q
```

Expected: missing services/storage methods.

- [ ] **Step 4: Adapt evidence to the existing voter without duplicating policy**

Construct one `CanonicalVideoTrack` whose `source_templates` contains one
`SourceTrackTemplate` per accepted live observation:

```python
SourceTrackTemplate(
    embedding=observation.embedding,
    detection_count=1,
    best_confidence=observation.detector_confidence,
)
```

Pass it to `VideoIdentityVotingService.resolve`. Do not create a second
threshold/margin algorithm. Snapshot recognition threshold, candidate floor
and margin into the event quality JSON.

- [ ] **Step 5: Implement transactional event ordering**

Exact order:

```text
derive deterministic event_id/object key
upload and stat accepted aligned snapshot
insert event once in PostgreSQL
commit event
publish best-effort in-memory notification
return revisioned identity assignment
```

If upload succeeds and DB fails, write a reconciliation record/log with the
technical event ID and remove the object best-effort. If upload fails, persist
the event with explicit failed snapshot status only when policy allows a
snapshotless event; otherwise return a sanitized failure and no false key.

- [ ] **Step 6: Add strict live snapshot storage**

Object key regex is exact:

```text
^live/<uuid>/<uuid>/aligned$
```

Store in configured private `MINIO_BUCKET_LIVE`; media type is `image/jpeg`.
Validate maximum `512 KiB`, JPEG SOI/EOI and SOF dimensions `112x112` without
decoding the image in Python. Include SHA-256 and event ID metadata. Bucket
creation remains private and idempotent.

- [ ] **Step 7: Run GREEN**

Run unit tests, then isolated PostgreSQL/Qdrant/object-storage integration:

```bash
pytest backend/tests/unit/test_live_identity_service.py backend/tests/unit/test_live_event_service.py -q
pytest backend/tests/integration/services/test_live_event_persistence.py -q
```

Expected: all pass; object bytes/stat SHA match; no production store name is
accepted by integration safety checks.

- [ ] **Step 8: Connect supervisor event flow**

On `TrackEvidenceEvent`, resolve/persist and enqueue assignment. On
`TrackExpiredEvent`, finalize stable Unknown if eligible and clear cooldown
state. Every handler is outside the native stdout reader hot loop through a
bounded async work queue.

- [ ] **Step 9: Scope checkpoint**

Run existing video voting tests plus `git diff --check`. Confirm image/video
anonymous lifecycle was not changed and live Unknown does not create a global
anonymous identity.

---

## Packet 5 - Annotated RTSP Output

### Task 12: OSD Assignment and GstRtspServer Output

**Files:**
- Create: `backend/pipeline/tests/test_live_osd_state.cpp`
- Modify: `backend/pipeline/include/mvision/live_pipeline.hpp`
- Modify: `backend/pipeline/src/live_pipeline.cpp`
- Modify: `backend/pipeline/tools/smoke_live_pipeline.cpp`
- Modify: `backend/pipeline/CMakeLists.txt`

**Interfaces:**
- Consumes: revisioned `IdentityAssignment` keyed by `(generation, tracker_id)`.
- Produces: sanitized RTSP mount `/live/<cameraId>`, `OutputReadyEvent`, and
  bounded `output_start`/`output_stop` native operation records.
- Draws: name/Unknown, cosine score, detector score, bbox and five landmarks.

- [ ] **Step 1: Write RED OSD state tests**

Assert exact label forms:

```text
Known:   "Monica  cos=0.873 det=0.941"
Unknown: "Unknown cos=0.392 det=0.901"
Pending: "Pending det=0.901"
```

Assert stale generation/revision cannot replace a newer label, Known cannot
change identity, expired track removes label state, and all user-controlled
name text is stripped of control characters and capped at 80 characters.

- [ ] **Step 2: Run RED**

Run `cmake --build build/pipeline --target test_live_osd_state`.

Expected: target-not-found failure.

- [ ] **Step 3: Add non-blocking output branch**

After SGIE/result probe, link:

```text
queue(leaky=downstream,max-size-buffers=4)
-> OSD assignment/display-meta probe
-> nvdsosd
-> nvvideoconvert
-> nvv4l2h264enc
-> h264parse
-> rtph264pay(pt=96)
-> udpsink(host=127.0.0.1,sync=false,async=false)
```

Use `NvDsDisplayMeta` circles/lines for five landmarks. Do not map a full frame
into Python/CPU for drawing.

- [ ] **Step 4: Add official RTSP server skeleton**

Adapt only the RTP caps/media-factory pattern from NVIDIA commit
`8ad0349ed7a496fae35ebb21c350641727070b89`. Bind configured RTSP port, create
one UUID-derived mount, set shared factory behavior explicitly, and remove the
mount during close. Emit OutputReady only after server attach and first encoded
buffer. Emit completed output operation records without mount path, camera ID,
viewer address or other high-cardinality attributes.

- [ ] **Step 5: Run native GREEN**

Run `./build/pipeline/test_live_osd_state`. Expected: label, immutability,
sanitization and expiry tests pass.

- [ ] **Step 6: Verify real output**

Start the fixture pipeline and run:

```bash
ffprobe -v error -show_streams rtsp://127.0.0.1:8554/live/<cameraId>
```

Expected: H.264 video, source dimensions, advancing timestamps and decodable
frames. Capture a bounded frame only in the acceptance test and assert expected
OSD metadata through native counters plus visual fixture review.

- [ ] **Step 7: Backpressure acceptance**

Run with no viewer, a normal viewer and a deliberately stalled viewer.
Input/processed frame counters must continue; output queue depth remains
bounded and dropped output count increases rather than blocking inference.

- [ ] **Step 8: Scope checkpoint**

Run 50 output mount create/remove cycles. Any port conflict, stale mount,
thread/fd/GPU-memory growth blocks completion.

---

## Packet 6 - API Events and Observability

### Task 13: Event Query, WebSocket, Health and Prometheus Metrics

**Files:**
- Create: `backend/app/presentation/routers/live_events.py`
- Create: `backend/app/observability/__init__.py`
- Create: `backend/app/observability/live_metrics.py`
- Create: `backend/tests/contract/test_live_events_api.py`
- Create: `backend/tests/unit/test_live_metrics.py`
- Modify: `backend/app/presentation/routers/cameras.py`
- Modify: `backend/app/presentation/routers/health.py`
- Modify: `backend/app/main.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces cursor-paginated durable event query and snapshot stream.
- Produces best-effort `/api/v1/live/events` WebSocket.
- Produces `/metrics` Prometheus text response.
- Consumes committed event notifications only.

- [ ] **Step 1: Write RED API/metric tests**

Assert:

- event list order/cursor stability;
- event response contains geometry/quality but no embedding/object secret;
- snapshot returns private bytes and correct media type;
- subscriber receives only post-commit event IDs;
- subscriber queue over capacity drops oldest and increments counter;
- disconnect clears subscriber state;
- health returns desired/runtime state, frame age, reconnect and queue data;
- `/metrics` content type and required metric names;
- no metric sample label contains camera, track, face, name, URI or host.

- [ ] **Step 2: Run RED**

Run:

```bash
pytest backend/tests/contract/test_live_events_api.py backend/tests/unit/test_live_metrics.py -q
```

Expected: missing routes/metrics module.

- [ ] **Step 3: Add official Prometheus client**

Pin a Python-3.12-compatible `prometheus-client` range. Use
`generate_latest(registry)` and `CONTENT_TYPE_LATEST`; upstream behavior was
inspected at commit `d0b497ffe069865537e55af52cb00c329d58a6f0`.

Metric labels are enum-only:

```text
state, reason, outcome, event_type, queue_type
```

No dynamic identity/source label is permitted.

- [ ] **Step 4: Implement bounded in-process fanout**

Maintain max 100 subscriber queues, each capacity 100. Publish only
`eventId`, `cameraId`, event type and occurred time after DB commit. On full
queue, drop oldest then enqueue newest and increment
`mvision_live_websocket_dropped_total`. Durable query remains authoritative.

- [ ] **Step 5: Implement health/readiness semantics**

`/health` keeps existing service health. Camera health reports FAILED/stale
without making the whole API unavailable. Live worker readiness is true only
when lease renewals and native protocol are healthy; ACTIVE additionally
requires frame age below threshold.

- [ ] **Step 6: Run GREEN**

Run:

```bash
pytest backend/tests/contract/test_live_events_api.py backend/tests/unit/test_live_metrics.py -q
ruff check backend/app/observability backend/app/presentation backend/tests/contract/test_live_events_api.py
mypy backend/app/observability backend/app/presentation
```

Expected: all pass.

- [ ] **Step 7: Scope checkpoint**

Inspect `/metrics`, event JSON and WebSocket payload with a real named match.
Confirm no name/face ID/URI/embedding appears in metric labels or logs.

### Task 13A: OpenTelemetry Application Instrumentation and Correlation

**Files:**
- Create: `backend/app/observability/telemetry.py`
- Create: `backend/tests/unit/test_live_telemetry.py`
- Create: `backend/tests/contract/test_telemetry_privacy.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/live_supervisor.py`
- Modify: `backend/app/services/live_identity_service.py`
- Modify: `backend/app/services/live_event_service.py`
- Modify: `backend/app/infrastructure/live/native_runner.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/.env.example`

**Interfaces:**
- Produces `configure_telemetry(settings: Settings) -> TelemetryRuntime`.
- Produces `TelemetryRuntime.traceparent() -> tuple[str, str | None]`.
- Produces `TelemetryRuntime.native_operation(event: NativeOperationEvent) -> None`.
- Produces `TelemetryRuntime.sanitize_attributes(values: Mapping[str, object]) -> dict[str, AttributeValue]`.
- Consumes OTLP endpoint/config only in Python; native C++ remains network-free.

- [ ] **Step 1: Verify and freeze current upstream artifacts**

Before changing dependencies, record exact current release/version, source URL,
license and selected artifact for OpenTelemetry Python API/SDK, OTLP exporter,
FastAPI/ASGI instrumentation, SQLAlchemy instrumentation, Collector Contrib,
Prometheus, Loki, Tempo and Grafana in
`docs/implementation/live-source-attribution.md`. Reject `latest`, unsigned
plugins, hosted-only exporters and packages outside Python 3.12 support.

- [ ] **Step 2: Write RED in-memory telemetry tests**

Use OpenTelemetry in-memory span/log exporters, never a mocked `Tracer`. Prove:

```text
camera start span -> supervisor claim -> camera run
native operation -> child span with explicit start/end
Qdrant/snapshot/event commit -> children of the same run
error_code sets ERROR status without raw exception text
native stderr is redacted before logging
export exception/drop does not change camera/service result
shutdown flush is bounded and idempotent
```

Assert span names are exact low-cardinality constants from the observability
spec. No frame, detection, embedding or tracker loop creates a span.

- [ ] **Step 3: Write RED privacy/cardinality tests**

Feed a URI containing userinfo, camera host and query token plus a known person,
face ID, embedding, snapshot and signed object URL through HTTP, supervisor,
native stderr, Qdrant and event-error paths. Serialize every exported span/log
and `/metrics` sample. Fail if any forbidden plaintext occurs or if dynamic IDs
appear as Prometheus labels/Loki resource labels.

- [ ] **Step 4: Run RED**

Run:

```bash
pytest backend/tests/unit/test_live_telemetry.py backend/tests/contract/test_telemetry_privacy.py -q
```

Expected: missing telemetry module and package imports.

- [ ] **Step 5: Add bounded Python OpenTelemetry runtime**

Pin the source-verified compatible package versions from Step 1. Settings are
exact:

```text
OTEL_ENABLED=true
OTEL_SERVICE_NAME=mvision-api or mvision-live-worker
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORT_TIMEOUT_SECONDS=2
OTEL_BSP_MAX_QUEUE_SIZE=2048
OTEL_BSP_MAX_EXPORT_BATCH_SIZE=256
OTEL_BSP_SCHEDULE_DELAY_MILLIS=500
```

Use batch processors and bounded shutdown. Configuration/export errors increment
`mvision_telemetry_dropped_total` or
`mvision_telemetry_export_failures_total`; they never fail camera work.

- [ ] **Step 6: Instrument only semantic boundaries**

Create spans with these exact names:

```text
http.camera.register, http.camera.start, http.camera.stop
live.supervisor.claim, live.supervisor.lease_renew, live.camera.run
live.native.<operation-enum>
live.identity.resolve, live.qdrant.search, live.snapshot.upload
live.event.commit, live.notification.publish
```

The supervisor injects W3C context into Start, validates echoed context, and
converts `NativeOperationEvent` monotonic timestamps using the run's monotonic
to UTC anchor. Native stderr passes through `redact_live_text` before a
trace-correlated structured log is emitted.

- [ ] **Step 7: Run GREEN**

Run:

```bash
pytest backend/tests/unit/test_live_telemetry.py backend/tests/contract/test_telemetry_privacy.py -q
ruff check backend/app/observability backend/app/services/live_supervisor.py backend/app/infrastructure/live backend/tests/unit/test_live_telemetry.py backend/tests/contract/test_telemetry_privacy.py
mypy backend/app/observability backend/app/services/live_supervisor.py backend/app/infrastructure/live
```

Expected: all pass; in-memory exports preserve one trace tree and forbidden
value scan returns zero matches.

- [ ] **Step 8: Scope checkpoint**

Inspect dependency graph and process network calls. Confirm only Python connects
to the Collector, no pad probe/log path performs blocking export, and telemetry
disabled/enabled modes preserve identical product responses and state changes.

---

## Packet 7 - Deployment and Release Gates

### Task 14: Self-Hosted Compose, Storage Pinning and Secret Delivery

**Files:**
- Create: `docker-compose.live.yml`
- Create: `docker-compose.observability.yml`
- Create: `configs/observability/otel-collector.yml`
- Create: `configs/observability/prometheus.yml`
- Create: `configs/observability/loki.yml`
- Create: `configs/observability/tempo.yml`
- Create: `configs/observability/grafana/provisioning/datasources/mvision.yml`
- Create: `configs/observability/grafana/provisioning/dashboards/mvision.yml`
- Create: `configs/observability/grafana/provisioning/alerting/mvision-live.yml`
- Create: `configs/observability/grafana/dashboards/live-camera-operations.json`
- Create: `configs/observability/grafana/dashboards/recognition-quality.json`
- Create: `configs/observability/grafana/dashboards/protocol-backpressure.json`
- Create: `configs/observability/grafana/dashboards/dependencies.json`
- Create: `configs/observability/grafana/dashboards/telemetry-health.json`
- Create: `backend/tests/unit/test_live_compose_contract.py`
- Create: `backend/tests/unit/test_observability_config_contract.py`
- Modify: `docker-compose.sprint01.yml`
- Modify: `backend/pipeline/Dockerfile`
- Modify: `backend/Dockerfile`
- Modify: `backend/.env.example`
- Modify: `README.md`
- Modify: `docs/implementation/live-source-attribution.md`

**Interfaces:**
- Produces: `live-worker-0`, RTSP fixture test profile, port `8554`, healthcheck
  and live bucket configuration.
- Produces pinned Collector, Prometheus, Loki, Tempo and Grafana services with
  isolated volumes, health checks, provisioning, correlations and retention.
- Consumes: secrets from untracked env/secret mounts; no checked-in key.

- [ ] **Step 1: Write RED compose contract test**

Parse merged Compose config and assert:

- exactly one live worker;
- worker reserves GPU 0 and no other GPU by default;
- only RTSP output port `8554` is exposed by live worker;
- encryption/fingerprint settings have no literal/default secret;
- URI is absent from command/environment;
- live worker depends on healthy PostgreSQL, Qdrant and object storage;
- no `latest` image tag exists in release compose;
- no Redis, Celery, Kafka or hosted service exists;
- volumes are named/persistent and no destructive init command exists.
- only Grafana is optionally bound to the trusted host; OTLP, Prometheus, Loki
  and Tempo ports remain internal;
- observability services use exact immutable image references and dedicated
  telemetry volumes, never application PostgreSQL/Qdrant/MinIO volumes.

- [ ] **Step 2: Run RED**

Run `pytest backend/tests/unit/test_live_compose_contract.py -q`.

Expected: missing live compose and current `latest` violations.

- [ ] **Step 3: Write RED observability config contract tests**

Parse Collector, Prometheus, Loki, Tempo and Grafana YAML/JSON and assert:

```text
Collector OTLP gRPC/HTTP receivers + memory_limiter + batch + tail_sampling
Collector logs -> Loki native OTLP HTTP /otlp
Collector traces -> Tempo OTLP
Collector Prometheus receiver scrapes API, worker and Collector telemetry
tail sampling keeps errors/reconnect/slow traces and 10% ordinary success
Loki Compactor retention_enabled with 7d retention
Tempo 7d retention and Docker-accessible OTLP receiver
Prometheus 15d command retention
Grafana Prometheus/Loki/Tempo UIDs match every correlation
five dashboard UIDs/titles exist and every query uses provisioned datasource
alert rules cover all nine required alert categories
no trace/camera/run/track/face/name/URI/host label template exists
```

Run:

```bash
pytest backend/tests/unit/test_observability_config_contract.py -q
```

Expected: missing Compose/config/provisioning files.

- [ ] **Step 4: Pin current self-hosted images by digest**

Inspect the currently validated PostgreSQL, Qdrant and MinIO image IDs/digests,
record them in the attribution/release ledger, and replace `latest` with those
exact immutable references. Also pin the Step 1 source-verified Collector,
Prometheus, Loki, Tempo and Grafana images by digest. Do not pull/upgrade or
recreate application data volumes in this task.

- [ ] **Step 5: Add live worker service**

Command is:

```yaml
command: ["python3", "-m", "app.worker.live_worker_main"]
```

Mount configs/models read-only, pass GPU 0, use `restart: unless-stopped`, map
`8554:8554`, and set `LIVE_ENABLED=true`. Encryption/HMAC keys come from an
untracked secret file or deployment secret mechanism, not Compose defaults.

- [ ] **Step 6: Add isolated observability services and configuration**

Use an additive Compose file. Collector receives OTLP internally on 4317/4318;
Prometheus, Loki and Tempo have no host port; Grafana alone may bind its
configured trusted interface. Collector sending queues and memory limiter are
bounded. Loki uses native OTLP ingestion and Compactor retention, not the
deprecated Loki exporter. Provision fixed datasource UIDs `prometheus`, `loki`
and `tempo`, bidirectional trace/log links, trace-to-metrics, service graph and
node graph.

Grafana admin credentials come from deployment secrets and have no default.
Use dedicated volumes `otel_data`, `prometheus_data`, `loki_data`, `tempo_data`
and `grafana_data`. Never mount recognition data into telemetry services.

- [ ] **Step 7: Freeze object-storage release decision**

For MVP, retain existing data and pin the validated MinIO image. Record its
AGPL/community distribution review as a release gate. If distribution review
rejects it, stop release and execute a separate checksum-preserving
S3-compatibility/migration plan to Apache-2.0 SeaweedFS; do not silently swap
production storage in this packet.

- [ ] **Step 8: Build and config-check**

Run:

```bash
docker compose -f docker-compose.sprint01.yml -f docker-compose.live.yml config
docker compose -f docker-compose.sprint01.yml -f docker-compose.live.yml -f docker-compose.observability.yml config
docker compose -f docker-compose.sprint01.yml -f docker-compose.live.yml build api live-worker-0
pytest backend/tests/unit/test_live_compose_contract.py backend/tests/unit/test_observability_config_contract.py -q
```

Expected: config and builds pass; no secret in rendered config.

- [ ] **Step 9: Non-destructive startup**

Run Compose `up -d` without `down -v`, prune or volume recreation. Verify
existing faces/videos remain queryable before and after starting live and
observability services. Start once with empty telemetry volumes and verify all
five telemetry services become healthy and Grafana reports all three data
sources healthy from provisioned configuration.

- [ ] **Step 10: Scope checkpoint**

Run `git diff --check`, inspect image references/licenses and confirm no model,
engine, dataset, secret or generated media was added.

### Task 15: Fault Injection, Calibration and Single-Camera Acceptance

**Files:**
- Create: `backend/scripts/live_acceptance.py`
- Create: `backend/scripts/live_quality_report.py`
- Create: `backend/scripts/live_soak.py`
- Create: `backend/scripts/live_observability_acceptance.py`
- Create: `backend/tests/integration/live/test_live_end_to_end.py`
- Create: `backend/tests/integration/live/test_live_faults.py`
- Create: `backend/tests/integration/live/test_live_store_safety.py`
- Create: `backend/tests/integration/live/test_live_observability.py`
- Create: `backend/tests/integration/live/test_live_telemetry_faults.py`
- Modify: `docs/implementation/CURRENT_SPRINT.md`

**Interfaces:**
- Produces machine-readable JSON acceptance report with environment, commands,
  inputs, counters, checks and verdict per gate.
- Produces quality percentile/rejection report without PII or images.
- Produces bounded soak samples for RSS, GPU memory, fd/thread count, queue
  depth, frame age and reconnect count.
- Produces machine-readable trace/log/metric correlation, privacy, dashboard,
  retention, telemetry fault-isolation and overhead A/B evidence.

- [ ] **Step 1: Write RED end-to-end tests**

Scenarios:

```text
valid RTSP -> ACTIVE + playable output
known Friends identity -> immutable Known event/OSD
ambiguous candidate -> Unknown
no-face stream -> successful ACTIVE, zero identity events
source stall/restart -> RECONNECTING -> ACTIVE
wrong credentials -> FAILED, no secret disclosure
stop during STARTING/ACTIVE/RECONNECTING/FAILED -> STOPPED
native SIGKILL -> failed run + new fenced generation
API restart -> supervisor/run continues
PostgreSQL/Qdrant/object-store outage -> fail-safe behavior
slow WebSocket/output viewer -> bounded drop, inference continues
one camera run -> correlated trace + logs + metrics + five Grafana dashboards
Collector/Loki/Tempo/Prometheus outage -> media continues, export recovers
forbidden URI/identity/vector/snapshot telemetry scan -> zero matches
```

- [ ] **Step 2: Run RED against the isolated profile**

Run:

```bash
pytest backend/tests/integration/live/test_live_end_to_end.py backend/tests/integration/live/test_live_faults.py -q
```

Expected: failures identify missing runtime evidence or behavior; no production
store is used.

- [ ] **Step 3: Write and run RED observability integration tests**

`test_live_observability.py` queries real Collector, Prometheus, Loki, Tempo and
Grafana APIs. It must fail unless one fixture camera run provides:

```text
API start -> desired commit -> claim -> native ACTIVE -> evidence
-> Qdrant decision -> snapshot -> event commit -> notification
```

in one trace; correlated logs contain the same trace ID as structured metadata;
Prometheus contains application/native/span/Collector metrics; all five
provisioned dashboards return non-empty real queries; trace-to-log,
log-to-trace, trace-to-metrics and service-graph links resolve.

`test_live_telemetry_faults.py` initially fails until Collector/backend stop,
bounded drop, camera continuity, exporter recovery and no-secret scans work.

Run:

```bash
pytest backend/tests/integration/live/test_live_observability.py backend/tests/integration/live/test_live_telemetry_faults.py -q
```

Expected: missing services/data or failed correlations, never mock PASS.

- [ ] **Step 4: Complete minimum fixes only**

For each failure, modify only the owning task's files, rerun its targeted unit
test, then rerun the failing integration scenario. Do not relax expected state,
threshold, queue bound or secret assertion to obtain GREEN.

- [ ] **Step 5: Run quality shadow collection**

Collect distributions for detector score, face side, clipping, pose proxies,
brightness, sharpness, embedding norm, evidence count/time and decision margin.
Report p5/p25/p50/p75/p95 plus rejection counts by reason. Do not include names,
face IDs, embeddings or snapshots in the report.

- [ ] **Step 6: Freeze calibrated policy**

Compare Known true-match, known-impostor and Unknown distributions on approved
deployment footage. Record chosen quality thresholds, recognition threshold
and margin with model/preprocess versions and false-accept/false-reject evidence.
If labelled calibration evidence is insufficient, keep `shadow_mode=true` and
classify production calibration `NOT_PROVEN`.

- [ ] **Step 7: Run repeated lifecycle test**

Execute 50 start/stop cycles. Acceptance requires:

```text
zero crash/segfault
zero stale RTSP mount/port
zero stale run lease
bounded fd/thread delta
GPU memory returns within recorded tolerance
all runs reach terminal STOPPED/FAILED
```

- [ ] **Step 8: Run real observability acceptance and overhead A/B**

Run `backend/scripts/live_observability_acceptance.py` against empty dedicated
telemetry volumes, then the same fixed RTSP window with telemetry disabled and
enabled. Acceptance requires:

```text
Collector/Prometheus/Loki/Tempo/Grafana healthy
three provisioned data sources healthy
five dashboards return real data
all four correlation directions resolve
errors/reconnects/slow traces retained; ordinary success approximately 10%
zero forbidden telemetry value/label matches
processed FPS degradation <= 3%
zero telemetry-induced evidence or output drops
```

Record raw counters, durations, sample counts, image digests and config SHA-256
in JSON. Do not compare different fixture/model/config windows.

- [ ] **Step 9: Run observability fault and retention acceptance**

Stop Collector, Loki, Tempo and Prometheus separately. The camera must remain
ACTIVE unless a media fault occurs; telemetry queues remain bounded; drop/export
failure counters increase; data resumes after restart. Use time-controlled test
retention values on disposable telemetry volumes to prove Loki Compactor, Tempo
and Prometheus expiry, then restore 7d/7d/15d production values. Never shorten
or alter application-store retention.

- [ ] **Step 10: Run 24-hour soak**

Sample health/resources every 30 seconds. Acceptance requires no unhandled
crash, no monotonic RSS/GPU-memory/queue growth, frame age under active
threshold except injected faults, and successful recovery after every planned
source interruption.

- [ ] **Step 11: Run full regression**

Run:

```bash
pytest backend/tests/unit backend/tests/contract -q
pytest backend/tests/integration -q
ruff check backend/app backend/tests backend/scripts
mypy backend/app backend/tests backend/scripts
cmake --build build/pipeline -j"$(nproc)"
./build/pipeline/test_protocol
./build/pipeline/test_video_protocol
./build/pipeline/test_video_aggregation
./build/pipeline/test_live_protocol
./build/pipeline/test_live_track_state
./build/pipeline/test_live_lifecycle
./build/pipeline/test_live_worker_process
./build/pipeline/test_live_osd_state
pytest backend/tests/unit/test_observability_config_contract.py backend/tests/contract/test_telemetry_privacy.py -q
pytest backend/tests/integration/live/test_live_observability.py backend/tests/integration/live/test_live_telemetry_faults.py -q
git diff --check
```

Expected: all runnable checks pass. Existing invalid-JPEG contract fixtures must
be repaired as test fixtures rather than weakening validation if they still
fail.

- [ ] **Step 12: Issue evidence verdict**

Mark each gate `PASS`, `PARTIAL`, `BLOCKED` or `NOT_TESTED`. A 24-hour soak not
actually run remains `NOT_TESTED`; a mock result cannot promote it. Record exact
Git status and no destructive data operation. Observability receives separate
`PASS`, `PARTIAL`, `BLOCKED` or `NOT_TESTED` verdicts for trace continuity,
privacy/cardinality, dashboards/correlation, fault isolation, retention and
overhead A/B.

### Task 16: Documentation, Runbook and Execution Handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/implementation/CURRENT_SPRINT.md`
- Create: `docs/implementation/live-operations-runbook.md`

**Interfaces:**
- Produces one canonical design link, one execution plan link and one operator
  runbook.
- Consumes verified implementation/runtime evidence only.

- [ ] **Step 1: Write runbook with exact operator flows**

Include non-secret commands for camera registration, start, health, output
playback, stop, failed-run diagnosis, credential rotation preparation,
snapshot retrieval, worker restart and rollback. Include Grafana access,
trace-ID investigation, trace/log/metric navigation, telemetry backend health,
bounded export-drop diagnosis, retention verification and non-destructive
telemetry-only reset. Examples use
`rtsp://user:[REDACTED]@camera.invalid/stream` only.

- [ ] **Step 2: Update README status truthfully**

Change livestream status from target to implemented only for gates actually
proven. Keep dynamic multi-camera, browser transport and cross-camera ReID in
the roadmap. Include the source audit and free/self-hosted license matrix.

- [ ] **Step 3: Verify superseded Phase 3 note remains removed**

Confirm every useful verified finding from the legacy note is represented in
the new design, attribution ledger or plan and that no README/design link points
to the removed note. Do not delete historical Phase 1/2 specs; their non-goals
describe their completed phase boundaries.

- [ ] **Step 4: Final consistency checks**

Search README/design/plan/runbook for:

```text
Celery
Redis
paid
production-ready
GPU-only
rtsp://
latest
```

Every match must either be an explicit rejection, sanitized example, verified
claim, or removed. Verify all referenced files exist and all endpoint/state
names match source.

- [ ] **Step 5: Final scope/evidence checkpoint**

Run:

```bash
git diff --check
git status --short
```

Report changed files, storage/schema impact, GPU/runtime evidence, known
limitations, tool/source accountability and one next packet. Do not commit or
push unless the user explicitly requests it.

---

## Plan Self-Review Checklist

- [x] Every first-milestone design goal maps to at least one task.
- [x] Every task has exact files, interfaces, RED command, GREEN command and
  scope checkpoint.
- [x] C++ and Python protocol names/types match.
- [x] Camera/run/event state names match migration, schemas and protocol.
- [x] Existing `VideoIdentityVotingService` is reused rather than duplicated.
- [x] Unknown live event semantics do not alter image API anonymous semantics.
- [x] URI plaintext crosses only API input, in-memory decrypt and Start frame.
- [x] Pad probe and output branch cannot block on control-plane work.
- [x] Every queue has a capacity and full policy.
- [x] Snapshot is canonical aligned evidence, not an original full frame.
- [x] Real dependencies/GPU are required for corresponding PASS claims.
- [x] Six livestream source repositories retain exact commit/license
  classification and useful findings.
- [x] No paid/hosted dependency enters the required path.
- [x] W3C trace context and native operation event are strict Python/C++ parity
  contracts before native pipeline implementation.
- [x] C++ has no OpenTelemetry SDK, exporter or telemetry network call.
- [x] Collector, Prometheus, Loki, Tempo and Grafana are pinned, self-hosted,
  health-checked and isolated from recognition data volumes.
- [x] Logs/traces/metrics, five dashboards, alerts, correlations, retention,
  fault isolation and <=3% overhead A/B each map to an acceptance task.
- [x] Telemetry contains no URI/host/credential/name/face ID/embedding/snapshot
  and no dynamic ID is a metric or Loki stream label.
- [x] No existing volume/data reset or historical migration rewrite is planned.
- [x] Dynamic multi-camera, browser playback and cross-camera ReID remain future
  packets behind the single-camera acceptance gate.

## Execution Choice

This plan is designed for two execution modes after document approval:

1. **Subagent-Driven**: fresh implementation/review agent per task.
2. **Inline Execution**: execute tasks in this session with
   `superpowers:executing-plans` and packet checkpoints.

The user requested no subagents during research/planning. Unless that decision
changes, use Inline Execution and stop at each packet's real evidence gate.
