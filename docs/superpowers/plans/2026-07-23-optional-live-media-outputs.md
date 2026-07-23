# Optional Live Media Outputs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independently optional raw fMP4 recording and annotated RTSP/WebRTC output to a live session while preserving frame JSON and inference when either media output fails.

**Architecture:** MediaMTX records the canonical unannotated generation ingress and notifies an idempotent Python segment-ingestion service after each closed file; a periodic filesystem reconciliation scan repairs missed notifications. Annotation remains a downstream-leaky native branch, but publishes to an opaque MediaMTX path through `rtspclientsink` instead of exposing worker UDP/RTSP ports. The Session Controller owns path provisioning and returns public URLs only after both MediaMTX online state and a bounded decode probe pass.

**Tech Stack:** Python 3.12, C++17, GStreamer/DeepStream 9, FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL 16, MediaMTX v1.19.2, MinIO, FFprobe, pytest, native CTest executables.

## Documentation Locks

- MediaMTX `/bluenviron/mediamtx`, pinned to official v1.19.2 `mediamtx.yml` and OpenAPI: per-path recording fields are `record`, `recordPath`, `recordFormat`, `recordPartDuration`, `recordMaxPartSize`, `recordSegmentDuration`, and `recordDeleteAfter`.
- MediaMTX v1.19.2 adds the recording filename extension automatically. `recordPath` supports `%path`, `%Y`, `%m`, `%d`, `%H`, `%M`, `%S`, `%f`, `%z`, and `%s` variables.
- `runOnRecordSegmentComplete` receives `MTX_PATH`, `MTX_SEGMENT_PATH`, and `MTX_SEGMENT_DURATION`. The hook is a hint; PostgreSQL/filesystem reconciliation remains authoritative.
- Current MediaMTX path readiness is `online=true`; deprecated `ready`/`readyTime` fields are not used.
- MediaMTX publisher paths use `source: publisher`. The native process publishes H.264 to an internal RTSP URL; the same MediaMTX path exposes public RTSP and WebRTC playback.
- SQLAlchemy 2 `/websites/sqlalchemy_en_20`: segment claims and retention claims use transactions, `FOR UPDATE SKIP LOCKED`, idempotent upserts, and fenced state transitions.
- Pydantic `/pydantic/pydantic`: recording and annotated overrides are strict nested models; unsupported formats, visual fields, and unknown keys fail before media/GPU work.

## Global Constraints

- Do not use subagents.
- Do not create commits unless the user explicitly asks.
- Deliveries 1 and 2 are complete and their immutable generation, MediaMTX controller, frame JSON, identity snapshot, and bounded queue interfaces are reused.
- `recording.enabled` and `annotatedStream.enabled` default to false and are independent.
- Recording captures canonical unannotated MediaMTX ingress, never the OSD branch.
- Production recording uses nominal 15-minute fMP4 segments; tests may use 15-second segments.
- A segment is not `READY` until it is closed, probed, checksummed, and present in its selected durable storage target.
- No exact sample-to-frame sidecar or nominal-FPS frame inference is added.
- A JSON-only session creates no recorder, annotated path, tee, OSD, encoder, payloader, publisher, or viewer URL.
- Annotation failure, viewer stall, or publisher reconnect never blocks or fails frame JSON, identity, appearance, or recording.
- Public responses contain configured public RTSP/WebRTC origins only; no Control API URL, container hostname, internal RTSP URL, publisher target, local file path, or credential is returned.
- Recording roots/object keys and annotated paths contain opaque generation/segment IDs only, never person names, locations, camera display names, source URIs, or face IDs.

---

## File Structure

- Modify `backend/app/presentation/schemas/live_sessions.py`: exact recording/annotation request and response models.
- Modify `backend/app/services/live_session_compiler.py`: dependency validation and resolved output specs.
- Modify `backend/app/services/mediamtx_reconciliation_service.py`: recording fields and annotated publisher paths.
- Modify `backend/app/infrastructure/media/mediamtx_client.py`: path-state track parsing used by output readiness.
- Create `backend/app/infrastructure/media/live_stream_probe.py`: bounded H.264 decode/readiness probe.
- Create `backend/app/infrastructure/database/repositories/live_recording_repository.py`: segment inventory, ingestion claims, list, and retention claims.
- Create `backend/app/services/live_recording_service.py`: hook validation, probe/checksum/upload/finalize, scan, and retention.
- Create `backend/app/presentation/schemas/live_recordings.py`: segment list/detail models.
- Create `backend/app/presentation/routers/live_recording_hooks.py`: hidden authenticated internal completion endpoint.
- Create `backend/app/presentation/routers/live_recordings.py`: protected list/detail/content endpoints.
- Create `backend/app/worker/live_recording_worker_main.py`: ingestion/reconciliation/retention loop.
- Create `backend/alembic/versions/f42e9b6a5c31_optional_live_media.py`: segment table and generation output state.
- Modify `backend/app/infrastructure/database/models.py`: `LiveRecordingSegment` and output state columns.
- Modify `backend/app/infrastructure/object_storage/minio_adapter.py`: live recording object operations.
- Modify `backend/app/config.py`, `backend/.env.example`: recording root, storage target, hook token, bounds, and probe settings.
- Create `infra/mediamtx/Dockerfile`: MediaMTX v1.19.2 image with a hook-capable shell/curl runtime.
- Create `configs/mediamtx.yml`: deployment-level MediaMTX config with Control API and no static camera paths.
- Modify `docker-compose.live.yml`: MediaMTX, shared recording volume, ingestion worker, and removal of public worker ports.
- Create `backend/pipeline/include/mvision/live_annotated_branch.hpp`: isolated optional output branch contract.
- Create `backend/pipeline/src/live_annotated_branch.cpp`: tee request pad, OSD/encoder/RTSP publisher, retry, and teardown.
- Modify `backend/pipeline/include/mvision/live_osd_state.hpp`, `backend/pipeline/src/live_osd_state.cpp`: typed visual state and selected labels.
- Modify `backend/pipeline/include/mvision/live_protocol.hpp`, `backend/pipeline/src/live_protocol.cpp`, `backend/app/infrastructure/live/protocol.py`: protocol v3 annotated options and output state.
- Modify `backend/pipeline/include/mvision/live_pipeline.hpp`, `backend/pipeline/src/live_pipeline.cpp`, `backend/pipeline/src/live_worker_main.cpp`: conditional branch construction and nonfatal output callbacks.
- Modify `backend/app/services/live_supervisor.py`: internal publish target and independent annotated state handling.
- Create `backend/app/services/live_annotated_output_service.py`: MediaMTX/decode readiness and safe URL projection.

---

### Task 1: Strict Output Configuration And Capability Compilation

**Files:**
- Modify: `backend/app/presentation/schemas/live_sessions.py`
- Modify: `backend/app/services/live_session_compiler.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/contract/test_live_sessions_schema.py`
- Modify: `backend/tests/unit/test_live_session_compiler.py`
- Modify: `backend/tests/unit/test_live_settings.py`

**Interfaces:**
- Produces: `ResolvedRecordingOutput` and `ResolvedAnnotatedOutput`.
- Produces capability limits for recording duration/retention, OSD colors/width/radius, encoder availability, and output dimensions.
- Consumes the Delivery 1 strict live base model and profile capability registry.

- [ ] **Step 1: Write failing strict-schema tests**

Assert defaults disable both outputs. Assert only `fmp4` is accepted; production
default is `15m`; test profile can request `15s`; retention is bounded. Assert
unknown keys, invalid hex colors, line widths outside the capability range,
unsupported labels, recognition labels in detection-only mode, and annotation on
a profile without an encoder all fail with stable codes.

- [ ] **Step 2: Run schema/compiler tests and verify failure**

Run: `cd backend && pytest tests/contract/test_live_sessions_schema.py tests/unit/test_live_session_compiler.py tests/unit/test_live_settings.py -q`

Expected: FAIL on incomplete recording/annotation models and capabilities.

- [ ] **Step 3: Add exact request models**

```python
class RecordingOptions(StrictLiveApiModel):
    enabled: bool = False
    format: Literal["fmp4"] = "fmp4"
    segment_duration: str = "15m"
    retention: str = "7d"


class BoundingBoxOptions(StrictLiveApiModel):
    enabled: bool = True
    color_mode: Literal["fixed", "identityState"] = "identityState"
    fixed_color: HexColor = "#00FF00"
    known_color: HexColor = "#00FF00"
    anonymous_color: HexColor = "#FFA500"
    pending_color: HexColor = "#FFFF00"
    unknown_color: HexColor = "#FF0000"
    line_width: int = Field(default=3, ge=1, le=8)


class LandmarkOptions(StrictLiveApiModel):
    enabled: bool = True
    color: HexColor = "#FFFF00"
    radius: int = Field(default=2, ge=1, le=8)


class LabelOptions(StrictLiveApiModel):
    enabled: bool = True
    fields: list[Literal[
        "name", "status", "trackId", "recognitionConfidence", "detectorConfidence"
    ]] = Field(default_factory=lambda: ["name", "status"])


class AnnotatedStreamOptions(StrictLiveApiModel):
    enabled: bool = False
    bounding_box: BoundingBoxOptions = Field(default_factory=BoundingBoxOptions)
    landmarks: LandmarkOptions = Field(default_factory=LandmarkOptions)
    labels: LabelOptions = Field(default_factory=LabelOptions)
```

Normalize six/eight-digit hex into immutable RGBA floats in the compiler; do not
send caller strings into native rendering.

- [ ] **Step 4: Compile dependency-safe resolved outputs**

Reject `identityState`, `name`, `status`, or `recognitionConfidence` when
recognition is disabled; reject `trackId` when tracking is disabled; reject
landmarks when the detector profile does not produce them. Keep encoder codec,
bitrate, GOP, latency, and hardware selection profile-owned.

- [ ] **Step 5: Add bounded deployment settings**

```python
live_recording_root: Path = Path("/recordings")
live_recording_storage_target: Literal["local", "minio"] = "local"
live_recording_segment_duration: str = "15m"
live_recording_part_duration: str = "1s"
live_recording_max_part_size: str = "50M"
live_recording_min_free_bytes: int = Field(default=10 * 1024**3, ge=1024**3)
live_recording_hook_token: SecretStr | None = None
live_recording_scan_seconds: float = Field(default=30.0, gt=0, le=300)
live_recording_probe_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
live_annotated_probe_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
live_annotated_viewer_grace_seconds: int = Field(default=15, ge=0, le=300)
```

When live recording can be enabled, require a non-empty hook token without
logging its value.

- [ ] **Step 6: Run schema/compiler/settings tests**

Run: `cd backend && pytest tests/contract/test_live_sessions_schema.py tests/unit/test_live_session_compiler.py tests/unit/test_live_settings.py -q`

Expected: PASS.

---

### Task 2: Exact MediaMTX Recording Configuration And Completion Hook

**Files:**
- Modify: `backend/app/services/mediamtx_reconciliation_service.py`
- Modify: `backend/app/infrastructure/media/mediamtx_client.py`
- Create: `backend/app/presentation/routers/live_recording_hooks.py`
- Create: `configs/mediamtx.yml`
- Create: `infra/mediamtx/Dockerfile`
- Modify: `docker-compose.live.yml`
- Test: `backend/tests/unit/test_mediamtx_reconciliation_service.py`
- Test: `backend/tests/contract/test_live_recording_hook.py`
- Create: `backend/tests/integration/media/test_mediamtx_recording_config.py`

**Interfaces:**
- Produces: `recording_path_fields(generation) -> dict[str, object]`.
- Produces hidden endpoint: `POST /internal/live/recordings/complete`.
- Consumes MediaMTX v1.19.2 hook environment and Delivery 1 path reconciliation.

- [ ] **Step 1: Write failing exact-config tests**

```python
def test_recording_fields_are_v1192_exact() -> None:
    fields = recording_path_fields(_generation(recording_enabled=True))
    assert fields == {
        "record": True,
        "recordPath": "/recordings/ingress/019f.../%Y-%m-%d_%H-%M-%S-%f",
        "recordFormat": "fmp4",
        "recordPartDuration": "1s",
        "recordMaxPartSize": "50M",
        "recordSegmentDuration": "15m",
        "recordDeleteAfter": "0s",
        "runOnRecordSegmentComplete": RECORDING_HOOK_COMMAND,
    }
```

Assert disabled generations set `record: false` and do not carry the hook or
recording path. Assert the command references the token environment variable but
does not contain the token value.

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend && pytest tests/unit/test_mediamtx_reconciliation_service.py tests/contract/test_live_recording_hook.py -q`

Expected: FAIL because recording path fields and hook route are absent.

- [ ] **Step 3: Build a hook-capable pinned MediaMTX image**

Use an Alpine runtime with the official v1.19.2 binary and `curl`; do not use a
floating MediaMTX tag. The hook command sends only controlled opaque path and
segment fields:

```text
/usr/bin/curl --fail --silent --show-error --max-time 3 \
  -H "X-Recording-Hook-Token: ${MVISION_RECORDING_HOOK_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-binary "{\"path\":\"${MTX_PATH}\",\"segmentPath\":\"${MTX_SEGMENT_PATH}\",\"duration\":\"${MTX_SEGMENT_DURATION}\"}" \
  http://api:8000/internal/live/recordings/complete
```

Set `TZ=UTC`. Mount `/recordings` into MediaMTX and the ingestion worker. Keep
Control API internal; MediaMTX owns public `8554`, `8889`, and ICE `8189/udp`.

- [ ] **Step 4: Add hidden hook authentication and validation**

Use a separate `APIKeyHeader(name="X-Recording-Hook-Token", auto_error=False)`
with `include_in_schema=False`. Accept exactly `path`, `segmentPath`, and
`duration`; path must match a desired recording generation before enqueue. Return
`202` for new or duplicate valid hints, `401` for auth failure, and `404` for an
unknown opaque path. Never echo a local path.

- [ ] **Step 5: Run a real short-segment config test**

Provision a deterministic H.264 ingress with `recordSegmentDuration: 15s`, wait
for a completed segment hook, and inspect Control API config. Assert the file is
under the opaque recording root and has an automatically added `.mp4` extension.

- [ ] **Step 6: Run recording config/hook tests**

Run: `cd backend && pytest tests/unit/test_mediamtx_reconciliation_service.py tests/contract/test_live_recording_hook.py tests/integration/media/test_mediamtx_recording_config.py -q`

Expected: PASS.

---

### Task 3: Idempotent Segment Inventory, Probe, Storage, And Retention

**Files:**
- Modify: `backend/app/infrastructure/database/models.py`
- Create: `backend/app/infrastructure/database/repositories/live_recording_repository.py`
- Create: `backend/app/services/live_recording_service.py`
- Modify: `backend/app/infrastructure/object_storage/minio_adapter.py`
- Create: `backend/alembic/versions/f42e9b6a5c31_optional_live_media.py`
- Test: `backend/tests/integration/persistence/test_live_recording_repository.py`
- Test: `backend/tests/unit/test_live_recording_service.py`
- Test: `backend/tests/integration/services/test_live_recording_ingestion.py`

**Interfaces:**
- Produces model/table: `LiveRecordingSegment` / `live_recording_segment`.
- Produces: `LiveRecordingService.accept_hint/ingest/reconcile/expire`.
- Produces MinIO methods: `upload_live_recording`, `stat_live_recording`, `read_live_recording_range`, `delete_live_recording`.
- Consumes existing `probe_video()` parsing with a recording-specific fMP4 wrapper.

- [ ] **Step 1: Write failing repository and ingestion tests**

Assert duplicate hook hints produce one segment row, path traversal/symlink escape
is rejected, an open/changing file is not ingested, corrupt fMP4 becomes `FAILED`,
valid fMP4 becomes `READY`, MinIO failure keeps recoverable local staging, and
retention deletes only expired ready segments.

- [ ] **Step 2: Add the segment table and generation output states**

```text
live_recording_segment:
  segment_id UUID primary key
  generation_id UUID FK live_session_generation
  session_id UUID not null
  generation INTEGER not null
  ingress_path VARCHAR(255) not null
  relative_path VARCHAR(512) unique not null
  state DISCOVERED|INGESTING|READY|FAILED|DELETING|DELETED
  actual_start_at/actual_end_at TIMESTAMPTZ null
  actual_start_unix_ns/actual_end_unix_ns NUMERIC(20,0) null
  duration_ns NUMERIC(20,0) null
  container VARCHAR(16) null
  codec VARCHAR(32) null
  width/height INTEGER null
  local_relative_path VARCHAR(512) null
  object_bucket VARCHAR(128) null
  object_key VARCHAR(512) null
  size_bytes BIGINT null
  sha256 CHAR(64) null
  error_code VARCHAR(64) null
  created_at/completed_at/finalized_at/retention_at TIMESTAMPTZ
```

Add independent `recording_state` and `annotated_state` columns to
`live_session_generation`. The migration `down_revision` is `e31c8a7d4f20`.

- [ ] **Step 3: Resolve and validate recording paths safely**

```python
def resolve_segment(root: Path, supplied: str) -> Path:
    root_value = root.resolve(strict=True)
    candidate = Path(supplied).resolve(strict=True)
    if not candidate.is_relative_to(root_value) or candidate.suffix != ".mp4":
        raise LiveRecordingError("LIVE_RECORDING_SEGMENT_INVALID")
    if not candidate.is_file():
        raise LiveRecordingError("LIVE_RECORDING_SEGMENT_INVALID")
    return candidate
```

Require two equal size/mtime observations for scan-discovered files. Hook files
are still probed after MediaMTX reports completion. Never invoke a shell for
probing or checksumming.

- [ ] **Step 4: Implement the fenced ingestion sequence**

Claim `DISCOVERED` rows with `FOR UPDATE SKIP LOCKED`, mark `INGESTING`, then:

```text
validate opaque generation and path containment
ffprobe fMP4 codec/dimensions/duration and decode one video interval
parse UTC start from controlled filename; calculate actual end from probe duration
stream SHA-256 and byte count from the closed file
upload to recordings/{generation_id}/{segment_id}.mp4 when target=minio
stat selected durable target and compare size/checksum
mark READY with actual metadata and retention_at
```

If target is local, keep the persistent-volume file. If MinIO is temporarily
unavailable, retain local staging and return the row to a retryable discovered
state with a stable error. Corrupt content is terminal `FAILED`.

- [ ] **Step 5: Add recording-specific MinIO operations**

Validate object keys with:

```python
RECORDING_OBJECT_KEY_PATTERN = re.compile(
    r"^recordings/[0-9a-f-]{36}/[0-9a-f-]{36}\.mp4$"
)
```

Use `fput_object` with `video/mp4`, metadata segment ID/SHA-256, `stat_object`
verification, bounded range reads, and idempotent delete in the existing live
bucket.

- [ ] **Step 6: Implement manifest-driven retention**

Claim expired `READY` rows, mark `DELETING`, delete the selected durable target,
verify absence, remove eligible staging, and mark `DELETED` while retaining
business metadata. Set MediaMTX `recordDeleteAfter: 0s` so it does not race the
manifest.

- [ ] **Step 7: Run persistence and ingestion tests**

Run: `cd backend && alembic upgrade head && pytest tests/integration/persistence/test_live_recording_repository.py tests/unit/test_live_recording_service.py tests/integration/services/test_live_recording_ingestion.py -q`

Expected: PASS.

---

### Task 4: Recording API And Reconciliation Worker

**Files:**
- Create: `backend/app/presentation/schemas/live_recordings.py`
- Create: `backend/app/presentation/routers/live_recordings.py`
- Create: `backend/app/worker/live_recording_worker_main.py`
- Modify: `backend/app/presentation/dependencies.py`
- Modify: `backend/app/main.py`
- Modify: `docker-compose.live.yml`
- Test: `backend/tests/contract/test_live_recordings_api.py`
- Test: `backend/tests/integration/live/test_live_recording_reconciliation.py`

**Interfaces:**
- Produces endpoints: list, detail, and content.
- Produces one deployment recording worker with bounded ingestion and periodic scan/retention cycles.
- Consumes Task 3 service/repository.

- [ ] **Step 1: Write failing API tests**

Assert only `READY` rows have `contentUrl`; `DISCOVERED`/`INGESTING` return no
partially written content; unknown is 404; not-ready is
`LIVE_RECORDING_NOT_READY`; deleted is `LIVE_RECORDING_EXPIRED`; list uses cursor
pagination and actual times.

- [ ] **Step 2: Add protected APIs**

```text
GET /api/v1/live/sessions/{session_id}/recordings
GET /api/v1/live/recordings/{segment_id}
GET /api/v1/live/recordings/{segment_id}/content
```

Use Delivery 1 API-key auth. Local content supports byte ranges from the safe
resolved path; MinIO content uses bounded `read_live_recording_range`. Return
`video/mp4`, `Accept-Ranges`, correct `Content-Range`, and no storage location.

- [ ] **Step 3: Add the recording worker loop**

Drain hook hints first, then claim discovered rows. On a bounded interval, scan
only desired generation directories for stable `.mp4` files, upsert missing
manifests, repair retryable ingestion rows, and process expired retention rows.
Shutdown stops accepting hints, finishes the current file with a deadline, and
leaves unfinished state retryable.

- [ ] **Step 4: Test missed and duplicate hooks**

Suppress the hook for one segment and deliver another hook twice. Assert periodic
scan discovers the missed segment, both produce exactly one `READY` row, and
checksums/decode pass.

- [ ] **Step 5: Run API and reconciliation tests**

Run: `cd backend && pytest tests/contract/test_live_recordings_api.py tests/integration/live/test_live_recording_reconciliation.py -q`

Expected: PASS.

---

### Task 5: Protocol V3 And Conditional Native Annotation Branch

**Files:**
- Modify: `backend/app/infrastructure/live/protocol.py`
- Modify: `backend/pipeline/include/mvision/live_protocol.hpp`
- Modify: `backend/pipeline/src/live_protocol.cpp`
- Create: `backend/pipeline/include/mvision/live_annotated_branch.hpp`
- Create: `backend/pipeline/src/live_annotated_branch.cpp`
- Modify: `backend/pipeline/include/mvision/live_pipeline.hpp`
- Modify: `backend/pipeline/src/live_pipeline.cpp`
- Modify: `backend/pipeline/include/mvision/live_osd_state.hpp`
- Modify: `backend/pipeline/src/live_osd_state.cpp`
- Modify: `backend/pipeline/src/live_worker_main.cpp`
- Modify: `backend/pipeline/CMakeLists.txt`
- Modify: `backend/pipeline/tests/test_live_osd_state.cpp`
- Modify: `backend/pipeline/tests/test_live_runtime_contract.cpp`
- Modify: `backend/tests/contract/test_live_protocol_parity.py`

**Interfaces:**
- Produces protocol v3 `AnnotatedOptions` in `StartCommand` and `AnnotatedOutputEvent`.
- Produces: `LiveAnnotatedBranch::attach/start/handle_bus_message/stop/close`.
- Consumes internal generation-scoped `publish_uri`; it is never a caller field.

- [ ] **Step 1: Write failing protocol and graph tests**

Assert disabled start commands contain `enabled=false` and no publish URI. Assert
enabled commands round-trip exact RGBA/width/radius/label bitmask/profile encoder
fields. In runtime construction tests, assert JSON-only element factories never
request `tee`, `nvdsosd`, `nvv4l2h264enc`, `h264parse`, or `rtspclientsink`.

- [ ] **Step 2: Bump private protocol atomically to v3**

```cpp
struct RgbaColor { float red{}, green{}, blue{}, alpha{1.0F}; };

struct AnnotatedOptions {
  bool enabled{};
  std::optional<std::string> publish_uri;
  bool boxes_enabled{};
  std::string box_color_mode;
  RgbaColor fixed_color;
  RgbaColor known_color;
  RgbaColor anonymous_color;
  RgbaColor pending_color;
  RgbaColor unknown_color;
  std::uint32_t line_width{};
  bool landmarks_enabled{};
  RgbaColor landmark_color;
  std::uint32_t landmark_radius{};
  bool labels_enabled{};
  std::uint32_t label_field_mask{};
};
```

Require `publish_uri` only when enabled and only an internal `rtsp://` target.
Reject non-finite/out-of-range colors and unknown label bits. No credentials,
public origins, Control API URL, or arbitrary GStreamer property enters the
command.

- [ ] **Step 3: Build no annotation elements when disabled**

For disabled output, link `sgie -> fakesink` and keep the Delivery 2 result probe
on `sgie:src`. Do not create a tee or output elements. Remove the embedded
`GstRTSPServer`, RTP UDP sink, mount path, and worker output port options.

- [ ] **Step 4: Encapsulate the enabled branch**

For enabled output, link:

```text
sgie -> tee
  -> queue -> fakesink
  -> queue(leaky=downstream,max-size-buffers=4)
       -> nvdsosd -> nvvideoconvert -> nvv4l2h264enc
       -> h264parse -> rtspclientsink(location=internal publish URI)
```

Own the tee request pad and every element in `LiveAnnotatedBranch`. Configure
codec/bitrate/GOP only from the compiled profile. Emit output-ready after the
first encoded/published buffer, not at graph construction.

- [ ] **Step 5: Render only typed selected layers**

Extend `LiveOsdState` to return a safe snapshot with identity state, selected
label fields, detector/recognition confidence, and color. Sanitize names to
printable text capped at 80 bytes. Apply configured box colors/line width,
landmark color/radius, and labels. Disabled layers add no display metadata.

- [ ] **Step 6: Isolate output errors from the analytics pipeline**

`handle_bus_message()` identifies messages originating inside the output branch.
On output error: mark output failed/degraded, flush/unlink the branch, release the
tee request pad, set/remove only branch elements, and schedule bounded publisher
rebuild. Do not call the main pipeline failure callback. A later successful first
buffer emits ready again. Source/inference bus errors retain existing behavior.

- [ ] **Step 7: Run native output tests**

Run: `cd backend && pytest tests/contract/test_live_protocol_parity.py -q`

Run: `cmake --build build/pipeline -j"$(nproc)" && ./build/pipeline/test_live_osd_state && ./build/pipeline/test_live_runtime_contract && ./build/pipeline/test_live_worker_process`

Expected: PASS; JSON-only graph has no output factories, and simulated publisher
failure leaves frame-result callbacks active.

---

### Task 6: Annotated MediaMTX Lifecycle, Decode Readiness, And Safe URLs

**Files:**
- Create: `backend/app/infrastructure/media/live_stream_probe.py`
- Create: `backend/app/services/live_annotated_output_service.py`
- Modify: `backend/app/services/mediamtx_reconciliation_service.py`
- Modify: `backend/app/services/live_session_service.py`
- Modify: `backend/app/services/live_supervisor.py`
- Modify: `backend/app/presentation/schemas/live_sessions.py`
- Test: `backend/tests/unit/test_live_stream_probe.py`
- Test: `backend/tests/unit/test_live_annotated_output_service.py`
- Modify: `backend/tests/unit/test_live_supervisor.py`
- Modify: `backend/tests/contract/test_live_sessions_api.py`

**Interfaces:**
- Produces annotated state machine: `DISABLED|PROVISIONING|WAITING_FOR_PUBLISHER|READY|FAILED`.
- Produces safe URLs only in `READY`.
- Consumes MediaMTX path state `online`, `tracks2`, native output events, and configured public origins.

- [ ] **Step 1: Write failing readiness tests**

Assert native `output_ready` alone returns no URLs; MediaMTX `online` alone returns
no URLs; wrong codec/caps fails; both plus successful decode probe returns exact
public RTSP/WebRTC URLs. Assert stale generation output cannot change current
state.

- [ ] **Step 2: Provision an opaque publisher path before worker start**

For enabled generations create `annotated/{opaque_generation_id}` with
`{"source": "publisher"}`. Persist only the opaque path. Pass
`rtsp://mediamtx:8554/{path}` to the claimed native process. Disabled generations
have no annotated path row or Control API config.

- [ ] **Step 3: Implement a bounded live decode probe**

Run FFprobe with an argument list, TCP RTSP, one selected video stream, and a
bounded read interval. Require H.264 plus positive width/height and process exit
inside `live_annotated_probe_timeout_seconds`. Kill on timeout and return stable
`LIVE_ANNOTATED_NOT_READY`; do not include URI/stderr in public errors.

- [ ] **Step 4: Gate URL projection on complete readiness**

```python
if not native_ready or path is None or not path.online:
    return AnnotatedStatus(state="WAITING_FOR_PUBLISHER", urls=None)
if "H264" not in {track["codec"] for track in path.tracks2}:
    return AnnotatedStatus(state="FAILED", error_code="LIVE_ANNOTATED_ENCODER_FAILED")
await self._probe.decode(internal_read_uri)
return AnnotatedStatus(
    state="READY",
    urls={
        "rtsp": join_origin(self._public_rtsp_origin, path_name),
        "webrtc": join_origin(self._public_webrtc_origin, path_name),
    },
)
```

- [ ] **Step 5: Reconcile restart and teardown**

MediaMTX restart clears stale ready state, recreates desired publisher paths, and
waits for native republish/probe. On reconfigure/stop, tear down worker branch
first, wait bounded viewer grace, then delete only the stale generation path.
Output `FAILED` may coexist with session `ACTIVE`.

- [ ] **Step 6: Run readiness/service tests**

Run: `cd backend && pytest tests/unit/test_live_stream_probe.py tests/unit/test_live_annotated_output_service.py tests/unit/test_live_supervisor.py tests/contract/test_live_sessions_api.py -q`

Expected: PASS.

---

### Task 7: Delivery 3 End-To-End Gates

**Files:**
- Create: `backend/tests/integration/live/test_optional_media_outputs.py`
- Create: `backend/scripts/live_media_outputs_smoke.py`
- Modify: `docs/implementation/CURRENT_SPRINT.md`

**Interfaces:**
- Proves independent recording and annotation against real MediaMTX v1.19.2.
- Consumes all prior task interfaces.

- [ ] **Step 1: Prove the JSON-only absence contract**

Create a session with both outputs disabled. Assert no recording fields/path,
files, segment rows, annotated MediaMTX path, native output elements, or viewer
URLs exist. Frame JSON count/content must match the Delivery 2 fixture baseline.

- [ ] **Step 2: Prove short recording behavior**

Use 15-second segments with deterministic H.264. Verify natural completion,
duplicate hook, missed-hook scan, source reconnect, and session stop produce valid
early/normal segments. Decode and hash every `READY` segment. Force MinIO/storage
failure and prove JSON/annotation continue.

- [ ] **Step 3: Prove annotation behavior and isolation**

Verify requested boxes, landmarks, states, colors, and labels through RTSP and
WebRTC. Stall a viewer and restart the publisher; frame JSON/inference counters
must continue. Disable each visual layer and verify absence. Force encoder/path
failure and prove recording plus JSON continue.

- [ ] **Step 4: Prove restart and repeated teardown**

Restart MediaMTX and the recording worker. Verify desired ingress/recording/
annotated state recovers and URLs remain absent until online/decode readiness.
Run 50 annotated start/stop cycles and assert bounded file descriptors, threads,
request pads, sockets, and GPU memory.

- [ ] **Step 5: Run one production-duration recording gate**

Run a real session for at least 16 minutes with `recordSegmentDuration: 15m`.
Observe a natural rollover and at least two decodable segment files. Verify actual
times, duration, checksum, list/detail/content APIs, and retention behavior.

- [ ] **Step 6: Run the complete Delivery 3 gate**

Run: `cd backend && pytest tests/unit/test_mediamtx_reconciliation_service.py tests/unit/test_live_recording_service.py tests/unit/test_live_stream_probe.py tests/unit/test_live_annotated_output_service.py tests/contract/test_live_recording_hook.py tests/contract/test_live_recordings_api.py tests/contract/test_live_sessions_api.py tests/integration/persistence/test_live_recording_repository.py tests/integration/services/test_live_recording_ingestion.py tests/integration/media/test_mediamtx_recording_config.py tests/integration/live/test_live_recording_reconciliation.py tests/integration/live/test_optional_media_outputs.py -q`

Run: `cmake --build build/pipeline -j"$(nproc)" && ./build/pipeline/test_live_protocol && ./build/pipeline/test_live_osd_state && ./build/pipeline/test_live_runtime_contract && ./build/pipeline/test_live_worker_process`

Run: `git diff --check`

Expected: all fast tests PASS; the separately scheduled 16-minute gate records a
natural rollover; no secret, person identity, face ID, raw source URI, internal
path, or local recording path appears in public output or metric labels.

---

## Self-Review Checklist

- [ ] Recording and annotation are independently optional and independently failed.
- [ ] Recording is raw ingress fMP4 with exact MediaMTX v1.19.2 property names.
- [ ] Completion hook is authenticated, idempotent, and repairable by scan.
- [ ] `READY` means closed, probed, checksummed, and durable.
- [ ] Retention is manifest-driven and does not race MediaMTX automatic deletion.
- [ ] JSON-only native construction creates no annotation branch elements.
- [ ] Worker public UDP/RTSP ports and embedded RTSP server are removed.
- [ ] Annotated output publishes only to an opaque MediaMTX path.
- [ ] Viewer URLs require native, MediaMTX online, codec, and decode readiness.
- [ ] Viewer/publisher/encoder failures cannot fail frame JSON or source inference.
- [ ] Recording failure cannot alter identity, appearance, or frame JSON.
- [ ] No exact recording-frame join, annotated recording, arbitrary encoder property, or viewer authentication system entered Delivery 3.
