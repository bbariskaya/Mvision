# Live Frame JSON And Optional Appearance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit one safe `frame.result` JSON envelope for every frame selected by a live session, add durable optional appearance summaries, and deliver events through bounded Webhook/Kafka connectors without blocking native inference.

**Architecture:** Upgrade the private Python/C++ protocol as one atomic v2 change so native identity evidence and public frame results are separate message types with explicit observed-UTC and stream-PTS fields. The native worker writes bounded frame traffic and reserved lifecycle traffic to independent queue classes; Python immediately projects safe envelopes into per-connector queues and an independent persistence queue. Identity evidence continues through the existing temporal resolver, extended with persistent anonymous creation and a generation-fenced identity snapshot registry used by frame projection and appearance aggregation.

**Tech Stack:** Python 3.12, C++17, GStreamer/DeepStream 9, MessagePack, FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL 16, HTTPX, AIOKafka, Qdrant, MinIO, pytest, native CTest executables.

## Documentation Locks

- HTTPX `/encode/httpx`: create one scoped `httpx.AsyncClient`, configure explicit connect/read/write/pool timeouts, use `await client.post(..., json=...)`, call `raise_for_status()`, and close with `await client.aclose()`.
- AIOKafka `/aio-libs/aiokafka`: construct `AIOKafkaProducer` from registered connector configuration, `await producer.start()` before use, use `await producer.send_and_wait(topic, value, key=...)` for acknowledged delivery, bound calls with `asyncio.timeout`, and always `await producer.stop()`.
- SQLAlchemy 2 `/websites/sqlalchemy_en_20`: batch persistence uses `AsyncSession`, PostgreSQL conflict handling, typed integer nanoseconds, and cursor predicates rather than offset pagination.
- Pydantic `/pydantic/pydantic`: all public live result models inherit the strict camel-case live base introduced in Delivery 1; external envelopes never serialize embeddings, image bytes, internal paths, or connector secrets.

## Global Constraints

- Do not use subagents.
- Do not create commits unless the user explicitly asks.
- Delivery 1 (`2026-07-23-live-session-mediamtx-ingress.md`) is complete and its session, generation, connector, API-key, and MediaMTX interfaces are the starting point.
- Every selected frame emits exactly one `frame.result`, including `faces: []`.
- Stream PTS is never converted to Unix time. Public time is Mvision-observed UTC in integer nanoseconds.
- Public bbox and five landmarks are in original source-frame pixels.
- Embeddings and aligned JPEG bytes remain restricted to `track_evidence`; they never enter frame events, connector payloads, frame persistence, logs, traces, or metrics.
- Direct Webhook delivery is low latency and may duplicate during in-process retry; it is not crash-safe at-least-once.
- Connector, frame-persistence, identity, and appearance work never performs network or database I/O in a GStreamer probe or native callback.
- Frame queues are bounded and droppable. Track expiry, stop, failure, and lease-loss control events are not silently dropped.
- Appearance rows are durable whenever appearance summaries are enabled. Frame persistence remains optional.
- Recognition uses five-point alignment and existing ArcFace model/preprocess versions.

---

## File Structure

- Create `backend/pipeline/include/mvision/live_frame_state.hpp`: pure sampling, timing-epoch, source-coordinate, and track-expiry helpers.
- Create `backend/pipeline/src/live_frame_state.cpp`: helper implementations independent of GStreamer.
- Create `backend/pipeline/tests/test_live_frame_state.cpp`: deterministic selector, geometry, clock, and expiry tests.
- Modify `backend/pipeline/include/mvision/live_protocol.hpp`: v2 frame-result and corrected evidence time types.
- Modify `backend/pipeline/src/live_protocol.cpp`: exact v2 MessagePack encode/decode validation.
- Modify `backend/pipeline/include/mvision/live_track_state.hpp`: anonymous identity state and safe assignment snapshot accessors.
- Modify `backend/pipeline/src/live_track_state.cpp`: fenced known/anonymous/unknown assignment application.
- Modify `backend/app/infrastructure/live/protocol.py`: Python parity types and validation.
- Modify `backend/pipeline/include/mvision/live_worker_queue.hpp`: separate bounded frame and reserved control queues.
- Modify `backend/pipeline/src/live_worker_queue.cpp`: priority and drop behavior.
- Modify `backend/pipeline/src/live_pipeline.cpp`: pre-inference sampling, original-pixel projection, frame-result emission, and actual track expiry.
- Modify `backend/pipeline/include/mvision/live_pipeline.hpp`: callbacks, options, and counters.
- Modify `backend/pipeline/src/live_worker_main.cpp`: route frame and critical events through the right queue.
- Create `backend/app/services/live_frame_projection_service.py`: safe stable public envelope projection and identity snapshot enrichment.
- Create `backend/app/services/live_anonymous_identity_service.py`: quality-gated serialized final gallery recheck and anonymous persistence.
- Create `backend/app/services/live_appearance_service.py`: optional started/ended lifecycle aggregation.
- Create `backend/app/services/live_delivery_service.py`: per-session connector workers and independent persistence worker.
- Create `backend/app/infrastructure/live/connectors.py`: HTTPX Webhook and AIOKafka adapters.
- Create `backend/app/infrastructure/database/repositories/live_result_repository.py`: batch frame and durable appearance persistence plus cursor queries.
- Create `backend/app/presentation/schemas/live_results.py`: public frame, appearance, and page models.
- Create `backend/app/presentation/routers/live_results.py`: session/face pull APIs.
- Create `backend/alembic/versions/e31c8a7d4f20_live_frame_results.py`: Delivery 2 tables and indexes, down-revisioned from Delivery 1.
- Modify `backend/app/infrastructure/database/models.py`: frame and appearance models.
- Modify `backend/app/services/live_identity_service.py`: correct time semantics and known/anonymous state handling.
- Modify `backend/app/services/live_event_service.py`: identity registry updates and removal of PTS-to-UTC conversion.
- Modify `backend/app/services/live_supervisor.py`: nonblocking routing, generation fencing, and lifecycle flush.
- Modify `backend/app/presentation/dependencies.py`, `backend/app/main.py`, `backend/pyproject.toml`: runtime construction, lifecycle close, router, and Kafka dependency.

---

### Task 1: Protocol V2 Separates Frame Results From Identity Evidence

**Files:**
- Modify: `backend/pipeline/include/mvision/live_protocol.hpp`
- Modify: `backend/pipeline/src/live_protocol.cpp`
- Modify: `backend/pipeline/include/mvision/live_track_state.hpp`
- Modify: `backend/pipeline/src/live_track_state.cpp`
- Modify: `backend/app/infrastructure/live/protocol.py`
- Modify: `backend/pipeline/tests/test_live_protocol.cpp`
- Modify: `backend/tests/unit/test_live_protocol.py`
- Modify: `backend/tests/contract/test_live_protocol_parity.py`

**Interfaces:**
- Produces: `FrameFaceResult`, `FrameResultEvent`, and protocol message type `frame_result`.
- Changes: `LiveObservation.timestamp_ns` to `observed_at_unix_ns` plus optional `pts_ns` in both languages.
- Changes: protocol version from `1` to `2`; Python and C++ are deployed together, so no dual decoder is added.
- Consumes: Delivery 1 header fields `session_id`, `run_id`, and `generation`.

- [ ] **Step 1: Write failing Python contract tests**

Add exact assertions for an empty frame and a face frame:

```python
def test_frame_result_round_trip_preserves_empty_selected_frame() -> None:
    event = FrameResultEvent(
        header=_header("frame_result", sequence=101),
        frame_sequence=7,
        pts_ns=4_200_000_000,
        observed_at_unix_ns=1_753_264_912_420_000_000,
        time_basis="mvision_observed_utc",
        timing_epoch=1,
        source_width=1280,
        source_height=720,
        faces=(),
    )
    assert decode_message(encode_message(event)) == event


def test_public_frame_protocol_contains_no_restricted_evidence() -> None:
    fields = _MESSAGE_FIELDS["frame_result"]
    assert "embedding" not in fields
    assert "aligned_jpeg" not in fields
    assert "representative_aligned_jpeg" not in fields
```

Also test a five-landmark face, null tracker/identity values, invalid dimensions,
more than 256 faces, non-finite geometry, confidence outside `[0, 1]`, and a v1
message rejected as `UNSUPPORTED_PROTOCOL_VERSION`.

- [ ] **Step 2: Run Python protocol tests and verify failure**

Run: `cd backend && pytest tests/unit/test_live_protocol.py tests/contract/test_live_protocol_parity.py -q`

Expected: FAIL because `FrameResultEvent` and protocol v2 do not exist.

- [ ] **Step 3: Add exact Python v2 dataclasses**

```python
PROTOCOL_VERSION = 2
MAX_FRAME_FACES = 256


@dataclass(frozen=True)
class FrameFaceResult:
    detection_ordinal: int
    tracker_id: int | None
    identity_epoch: int
    assignment_revision: int
    identity_state: Literal["pending", "known", "anonymous", "unknown"]
    face_id: str | None
    display_name: str | None
    bbox: tuple[float, float, float, float]
    landmarks: tuple[float, ...]
    landmark_confidences: tuple[float, ...]
    detector_confidence: float
    recognition_confidence: float | None
    quality_score: float
    reject_mask: int
    accepted_for_identity: bool


@dataclass(frozen=True)
class FrameResultEvent:
    header: ProtocolHeader
    frame_sequence: int
    pts_ns: int | None
    observed_at_unix_ns: int
    time_basis: Literal["mvision_observed_utc"]
    timing_epoch: int
    source_width: int
    source_height: int
    faces: tuple[FrameFaceResult, ...]
```

Require positive dimensions and timestamps, exactly ten landmark coordinates and
five confidences, finite geometry, bounded confidence, and identity invariants:
`known`/`anonymous` require `face_id`; `pending`/`unknown` forbid it.

- [ ] **Step 4: Add matching C++ v2 structs and variant member**

```cpp
inline constexpr std::uint32_t kLiveProtocolVersion = 2;
inline constexpr std::size_t kMaxFrameFaces = 256U;

struct FrameFaceResult {
  std::uint64_t detection_ordinal{};
  std::optional<std::uint64_t> tracker_id;
  std::uint64_t identity_epoch{1};
  std::uint64_t assignment_revision{};
  std::string identity_state{"pending"};
  std::optional<std::string> face_id;
  std::optional<std::string> display_name;
  std::array<float, 4> bbox{};
  std::array<float, 10> landmarks{};
  std::array<float, 5> landmark_confidences{};
  float detector_confidence{};
  std::optional<float> recognition_confidence;
  float quality_score{};
  std::uint64_t reject_mask{};
  bool accepted_for_identity{};
};

struct FrameResultEvent {
  ProtocolHeader header;
  std::uint64_t frame_sequence{};
  std::optional<std::uint64_t> pts_ns;
  std::uint64_t observed_at_unix_ns{};
  std::string time_basis{"mvision_observed_utc"};
  std::uint64_t timing_epoch{1};
  std::uint32_t source_width{};
  std::uint32_t source_height{};
  std::vector<FrameFaceResult> faces;
};
```

Insert `FrameResultEvent` into `LiveMessage`. Rename evidence time fields in both
languages to `observed_at_unix_ns`/`first_seen_unix_ns`/`last_seen_unix_ns`, and
add optional PTS only where diagnostic ordering needs it.

- [ ] **Step 5: Implement symmetric MessagePack validation**

Use exact field sets and reject unknown keys. Encode optional integers as nil,
booleans as booleans, and uint64 tracker IDs without narrowing. Never reuse the
evidence observation packer for `FrameFaceResult` because it contains an embedding.

Extend `TrackIdentityState` to `Pending|Known|Anonymous|Unknown`. Store and expose
an immutable safe assignment snapshot containing epoch, revision, state, face ID,
display name, and match score. The state object may retain the reference embedding
privately for OSD hysteresis, but `FrameFaceResult` construction can access only
the safe snapshot.

- [ ] **Step 6: Run protocol parity gates**

Run: `cd backend && pytest tests/unit/test_live_protocol.py tests/contract/test_live_protocol_parity.py -q`

Run: `cmake --build build/pipeline -j"$(nproc)" && ./build/pipeline/test_live_protocol`

Expected: PASS in Python, C++, and cross-language fixtures.

---

### Task 2: Native Sampling, Timing, Original-Pixel Geometry, And Track Expiry

**Files:**
- Create: `backend/pipeline/include/mvision/live_frame_state.hpp`
- Create: `backend/pipeline/src/live_frame_state.cpp`
- Create: `backend/pipeline/tests/test_live_frame_state.cpp`
- Modify: `backend/pipeline/CMakeLists.txt`
- Modify: `backend/pipeline/include/mvision/live_pipeline.hpp`
- Modify: `backend/pipeline/src/live_pipeline.cpp`
- Modify: `backend/pipeline/tests/test_live_runtime_contract.cpp`

**Interfaces:**
- Produces: `LiveFrameSelector::select(pts_ns, monotonic_ns) -> bool`.
- Produces: `SourceTransform::from_dimensions(source_width, source_height, pipeline_width, pipeline_height)` and `to_source(...)`.
- Produces: `LiveTimingEpoch::observe(optional_pts) -> uint64_t`.
- Produces callback: `LivePipelineCallbacks.on_frame(const FrameResultEvent&)`.
- Produces callback: `LivePipelineCallbacks.on_track_expired(const TrackExpiredEvent&)`.
- Consumes resolved start fields `sampling_mode`, `sampling_value`, and `track_gap_ns`.

- [ ] **Step 1: Write failing pure native tests**

```cpp
void test_every_n_selector() {
  mvision::LiveFrameSelector selector({"every_n_frames", 3.0});
  assert(selector.select(0, 1));
  assert(!selector.select(1, 2));
  assert(!selector.select(2, 3));
  assert(selector.select(3, 4));
}

void test_target_fps_uses_pts_deadlines() {
  mvision::LiveFrameSelector selector({"target_fps", 2.0});
  assert(selector.select(0, 1));
  assert(!selector.select(100'000'000, 2));
  assert(selector.select(500'000'000, 3));
  assert(selector.select(1'000'000'000, 4));
}

void test_letterbox_coordinates_return_to_source_pixels() {
  const auto transform = mvision::SourceTransform::from_dimensions(
      1280, 960, 1920, 1080);
  const auto box = transform.to_source({240.0F, 0.0F, 1440.0F, 1080.0F});
  assert(box == std::array<float, 4>{0.0F, 0.0F, 1280.0F, 960.0F});
}
```

Also prove PTS rollback increments `timing_epoch`, invalid PTS uses monotonic only
for selection, an absent track expires after `track_gap_ns`, and `expire_all()`
returns every open track exactly once.

- [ ] **Step 2: Run native helper test and verify failure**

Run: `cmake --build build/pipeline -j"$(nproc)"`

Expected: compile failure because `live_frame_state.hpp` is absent.

- [ ] **Step 3: Implement pure state helpers**

Use this exact public shape:

```cpp
struct SamplingSpec {
  std::string mode;
  double value{};
};

class LiveFrameSelector {
 public:
  explicit LiveFrameSelector(SamplingSpec spec);
  bool select(std::optional<std::uint64_t> pts_ns,
              std::uint64_t monotonic_ns);
  void reset();
};

class LiveTimingEpoch {
 public:
  std::uint64_t observe(std::optional<std::uint64_t> pts_ns);
  std::uint64_t discontinuity();
};
```

For `target_fps`, keep an integer nanosecond deadline and advance by
`round(1e9 / value)` without floating-point timestamps. A backward PTS or a jump
larger than the configured discontinuity threshold starts a new epoch.

- [ ] **Step 4: Drop unselected buffers before inference**

Install a buffer probe on the source conversion chain before `nvstreammux`.
Return `GST_PAD_PROBE_DROP` for unselected buffers. Set PGIE `interval=0`; the
selector, not metadata deletion after inference, owns sampling. Remove the
current `frame_num % sample_every_n` object-removal block from
`on_tracker_buffer`.

- [ ] **Step 5: Emit one frame result for each selected buffer**

In `on_result_buffer`, create the frame event before quality filtering and call
`on_frame` even when `frame->obj_meta_list` is empty. Use:

```cpp
FrameResultEvent result;
result.header = header("frame_result");
result.frame_sequence = next_frame_sequence++;
result.pts_ns = GST_CLOCK_TIME_IS_VALID(frame->buf_pts)
                    ? std::optional<std::uint64_t>(frame->buf_pts)
                    : std::nullopt;
result.observed_at_unix_ns = unix_time_ns();
result.time_basis = "mvision_observed_utc";
result.timing_epoch = timing_epoch.observe(result.pts_ns);
result.source_width = frame->source_frame_width;
result.source_height = frame->source_frame_height;
```

Map `NvDsObjectMeta::rect_params` and all five mask landmarks through
`SourceTransform`; clamp only after unletterboxing. Snapshot the current
`IdentityAssignmentState` under `track_mutex`, but copy no reference embedding or
aligned JPEG into the frame result.

- [ ] **Step 6: Emit real expiry events on a reserved lifecycle callback**

Track `last_seen_unix_ns`, last valid media PTS, and last monotonic receive time
for every tracker ID, not only quality-accepted evidence. At the end of each
selected frame, expire missing tracks after `track_gap_ns`. Call `expire_all()` on
timing discontinuity, graph rebuild, session stop, and close. Each expiry uses a
stable reason from:

```text
track_gap
tracker_removed
identity_epoch_changed
timing_discontinuity
graph_rebuild
session_stopped
```

- [ ] **Step 7: Run pure and pipeline contract tests**

Run: `cmake --build build/pipeline -j"$(nproc)" && ./build/pipeline/test_live_frame_state && ./build/pipeline/test_live_runtime_contract`

Expected: PASS; fixture counts include selected no-face frames and original-pixel
geometry.

---

### Task 3: Native Queue Isolation And Worker Routing

**Files:**
- Modify: `backend/pipeline/include/mvision/live_worker_queue.hpp`
- Modify: `backend/pipeline/src/live_worker_queue.cpp`
- Modify: `backend/pipeline/src/live_worker_main.cpp`
- Modify: `backend/pipeline/tests/test_live_worker_process.cpp`
- Modify: `backend/pipeline/tests/test_live_protocol.cpp`

**Interfaces:**
- Produces: `LiveWorkerEventQueue(frame_capacity, evidence_capacity, operation_capacity)`.
- Guarantees: frame events drop oldest under saturation and increment `dropped_frames`; expiry/control enqueue failure stops the child with `LIVE_CONTROL_QUEUE_EXHAUSTED`.
- Consumes: callbacks from Task 2.

- [ ] **Step 1: Write failing queue-priority tests**

Create a queue with frame capacity two, push frame sequences 1, 2, and 3, then a
`TrackExpiredEvent`. Assert the expiry pops first, frame 1 was dropped, frames 2
and 3 remain ordered, and `dropped_frames == 1`. Fill the reserved control queue
and assert the next critical push returns false instead of pretending success.

- [ ] **Step 2: Run queue tests and verify failure**

Run: `cmake --build build/pipeline -j"$(nproc)" && ./build/pipeline/test_live_protocol`

Expected: FAIL because frame traffic has no independent bounded queue.

- [ ] **Step 3: Add explicit queue classes and stats**

```cpp
struct LiveWorkerQueueStats {
  std::size_t control{};
  std::size_t frames{};
  std::size_t evidence{};
  std::size_t metrics{};
  std::size_t operations{};
  std::uint64_t dropped_frames{};
  std::uint64_t dropped_evidence{};
};
```

Priority is control, evidence, frame, metrics, operation. Coalesce evidence by
tracker. Do not coalesce expiry. Bound frames with oldest-drop so sequence gaps
are visible to consumers.

- [ ] **Step 4: Wire worker callbacks without probe I/O**

```cpp
callbacks.on_frame = [&](const mvision::FrameResultEvent& event) {
  auto outbound = event;
  outbound.header = event_header("frame_result");
  events.push(std::move(outbound));
};
callbacks.on_track_expired = [&](const mvision::TrackExpiredEvent& event) {
  auto outbound = event;
  outbound.header = event_header("track_expired");
  if (!events.push(std::move(outbound))) {
    writer_failed.store(true);
    signal_requested.store(true);
  }
};
```

Expose frame/evidence drop counts in `MetricsEvent`; no dynamic ID becomes a
metric label.

- [ ] **Step 5: Run worker process tests**

Run: `cmake --build build/pipeline -j"$(nproc)" && ./build/pipeline/test_live_worker_process && ./build/pipeline/test_live_protocol`

Expected: PASS; forced frame saturation preserves expiry and bounded memory.

---

### Task 4: Safe Frame Projection And Generation-Fenced Identity Snapshots

**Files:**
- Create: `backend/app/services/live_frame_projection_service.py`
- Modify: `backend/app/services/live_event_service.py`
- Modify: `backend/app/services/live_identity_service.py`
- Test: `backend/tests/unit/test_live_frame_projection_service.py`
- Modify: `backend/tests/unit/test_live_event_service.py`
- Modify: `backend/tests/unit/test_live_identity_service.py`

**Interfaces:**
- Produces: `LivePublicEvent(event_id, event_type, payload, ordering_key)`.
- Produces: `IdentitySnapshotRegistry.accept(assignment, identity_metadata, newly_created) -> None`.
- Produces: `LiveFrameProjectionService.project(generation, native_event) -> LivePublicEvent`.
- Consumes: generation camera/location snapshot from Delivery 1 and `FrameResultEvent` from Task 1.

- [ ] **Step 1: Write failing projection tests**

Assert the exact approved envelope, stable event/detection IDs across two calls,
RFC 3339 UTC from `observed_at_unix_ns`, `ptsNs` retained only as stream-relative,
and no-face output as `faces: []`. Assert stale assignment revision, run, or
generation cannot enrich a new frame.

- [ ] **Step 2: Run projection tests and verify failure**

Run: `cd backend && pytest tests/unit/test_live_frame_projection_service.py tests/unit/test_live_event_service.py tests/unit/test_live_identity_service.py -q`

Expected: import failure for the projection service.

- [ ] **Step 3: Implement stable IDs and nanosecond formatting**

```python
def frame_event_id(session_id: str, generation: int, sequence: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"mvision:frame:{session_id}:{generation}:{sequence}"))


def detection_id(event_id: str, ordinal: int) -> str:
    return str(uuid5(UUID(event_id), f"detection:{ordinal}"))


def rfc3339_from_unix_ns(value: int) -> str:
    seconds, nanoseconds = divmod(value, 1_000_000_000)
    base = datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{nanoseconds:09d}Z"
```

- [ ] **Step 4: Implement the strict safe projection**

The public face status mapping is:

```python
status = {
    "pending": "pending",
    "known": "known",
    "anonymous": "newAnonymous" if snapshot.newly_created_and_unreported else "anonymous",
    "unknown": "unknown",
}[face.identity_state]
```

Include metadata only from the accepted identity snapshot registry. Validate the
exact session, run, generation, tracker, identity epoch, decision sequence, and
assignment revision before use. Mark `newAnonymous` reported only after creating
the first projected frame; retrying the same frame returns the same cached status.

- [ ] **Step 5: Correct existing evidence time semantics**

Remove `datetime.fromtimestamp(frame->buf_pts / 1e9)` behavior from
`LiveEventService`. Persist evidence UTC from `observed_at_unix_ns`; keep PTS in a
separate diagnostic field where needed. Update cooldown and dwell comparisons to
observed UTC or monotonic durations, never a mixture.

- [ ] **Step 6: Run projection and identity tests**

Run: `cd backend && pytest tests/unit/test_live_frame_projection_service.py tests/unit/test_live_event_service.py tests/unit/test_live_identity_service.py -q`

Expected: PASS, including pending-to-known and retry stability.

---

### Task 5: Persistent Anonymous Identity Creation And Reuse

**Files:**
- Create: `backend/app/services/live_anonymous_identity_service.py`
- Modify: `backend/app/services/live_identity_service.py`
- Modify: `backend/app/services/face_sample_persistence_service.py`
- Modify: `backend/app/infrastructure/database/repositories/identity_repository.py`
- Test: `backend/tests/unit/test_live_anonymous_identity_service.py`
- Test: `backend/tests/integration/services/test_live_anonymous_identity.py`

**Interfaces:**
- Produces: `LiveAnonymousIdentityService.resolve_or_create(evidence) -> AnonymousResolution | None`.
- Produces: `AnonymousResolution(face_id, sample_id, score, newly_created, reference_embedding)`.
- Consumes: existing `VideoIdentityVotingService`, `FaceSamplePersistenceService`, Qdrant, MinIO, and model version settings.

- [ ] **Step 1: Write failing quality and concurrency tests**

Assert no creation below minimum accepted evidence count, dwell, or temporal
separation. Assert a final gallery match reuses its `face_id`. Launch two
concurrent creation attempts for the same evidence fixture and assert exactly one
active identity/sample pair and one shared returned `face_id`.

- [ ] **Step 2: Run anonymous identity tests and verify failure**

Run: `cd backend && pytest tests/unit/test_live_anonymous_identity_service.py tests/integration/services/test_live_anonymous_identity.py -q`

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Add a serialized final-recheck repository boundary**

```python
LIVE_ANONYMOUS_CREATION_LOCK = 0x4D564C495645414E


async def lock_anonymous_creation(self, session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_lock(:lock_key)"),
        {"lock_key": LIVE_ANONYMOUS_CREATION_LOCK},
    )


async def unlock_anonymous_creation(self, session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": LIVE_ANONYMOUS_CREATION_LOCK},
    )
```

The initial release intentionally serializes the rare anonymous-creation critical
section on one dedicated database connection. Hold the session-level advisory
lock across final Qdrant recheck, pending PostgreSQL reservation, MinIO upload,
inactive Qdrant upsert, PostgreSQL activation, and final Qdrant activation. Release
it in `finally`; connection close also releases it after a crash. Do not keep one
database transaction open during external I/O. All ordinary matching remains
concurrent.

- [ ] **Step 4: Implement the creation saga with compensation**

Inside the lock: first resume or fail any pending anonymous reservation, then
final-search known and anonymous active samples; return a match when accepted;
otherwise allocate UUIDv7 face/sample IDs and commit a pending anonymous
identity/sample. Add an idempotent
`FaceSamplePersistenceService.persist_reserved_anonymous(...)` path that reuses
those IDs, uploads the 112x112 JPEG, upserts Qdrant with `active=false`, finalizes
the PostgreSQL sample, then activates Qdrant. If external persistence fails, keep
the same pending reservation retryable or mark it failed/inactive and do not
return a global ID. A later request under the same lock must reconcile that
reservation before allocating another identity.

- [ ] **Step 5: Extend live identity decisions and assignments**

Recognized identities retain their database lifecycle:

```text
known identity match      -> known
anonymous identity match  -> anonymous
new successful creation   -> anonymous + newly_created=true
insufficient evidence     -> pending
identity disabled         -> unknown
```

Assignment fencing remains revision/epoch/decision-sequence based. Enrollment of
an anonymous identity updates lifecycle to known without changing `face_id`.

- [ ] **Step 6: Run identity persistence gates**

Run: `cd backend && pytest tests/unit/test_live_anonymous_identity_service.py tests/unit/test_live_identity_service.py tests/integration/services/test_live_anonymous_identity.py -q`

Expected: PASS; repeated and concurrent appearances reuse one global identity.

---

### Task 6: Bounded Webhook And Kafka Delivery

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/infrastructure/live/connectors.py`
- Create: `backend/app/services/live_delivery_service.py`
- Test: `backend/tests/unit/test_live_connectors.py`
- Test: `backend/tests/unit/test_live_delivery_service.py`
- Test: `backend/tests/integration/live/test_live_connector_isolation.py`

**Interfaces:**
- Produces: `WebhookConnector.send(event) -> None`.
- Produces: `KafkaConnector.start/send/close`.
- Produces: `LiveDeliveryService.open_generation/register_event/close_generation`.
- Consumes: encrypted registered connector specs from Delivery 1 and safe public events from Task 4.

- [ ] **Step 1: Add the Kafka runtime dependency**

Add `"aiokafka>=0.12.0,<1.0.0"` to project dependencies and rebuild the backend
image/lock environment used by CI.

- [ ] **Step 2: Write failing adapter tests**

Use `httpx.MockTransport` to assert JSON body, event ID header, timeout, retryable
status policy, and no URL/body in error logs. Use a fake AIOKafka producer to
assert `start`, `send_and_wait`, stable event bytes/key, timeout, and `stop`.

- [ ] **Step 3: Implement narrow documented adapters**

```python
class WebhookConnector:
    async def send(self, event: LivePublicEvent) -> None:
        response = await self._client.post(
            self._url,
            json=event.payload,
            headers={**self._headers, "X-Mvision-Event-Id": event.event_id},
        )
        response.raise_for_status()


class KafkaConnector:
    async def start(self) -> None:
        await self._producer.start()

    async def send(self, event: LivePublicEvent) -> None:
        async with asyncio.timeout(self._timeout_seconds):
            await self._producer.send_and_wait(
                self._topic,
                json.dumps(event.payload, separators=(",", ":")).encode(),
                key=event.ordering_key.encode(),
            )

    async def close(self) -> None:
        await self._producer.stop()
```

TLS/SASL values come only from decrypted registered connector configuration and
are never retained in public events.

- [ ] **Step 4: Implement per-connector bounded workers**

Each selected connector gets its own `asyncio.Queue(maxsize=capacity)`. Enqueue is
`put_nowait`; saturation applies its configured oldest/newest frame drop policy
and increments a low-cardinality counter. Retry only retryable Webhook failures
and Kafka errors with bounded exponential delay and jitter. Reuse the same event
object/event ID. Connector failure never raises into the supervisor event reader.

- [ ] **Step 5: Keep persistence independent**

Create a distinct persistence queue and batch worker. Enqueuing connector work
must not condition persistence, and persistence failure must not stop connector
delivery. Reject a session before GPU work if it has neither connector refs nor
frame persistence.

- [ ] **Step 6: Run connector isolation tests**

Run: `cd backend && pytest tests/unit/test_live_connectors.py tests/unit/test_live_delivery_service.py tests/integration/live/test_live_connector_isolation.py -q`

Expected: PASS; slow Webhook and unavailable Kafka fixtures do not reduce native
frame progress, and saturation creates visible sequence gaps.

---

### Task 7: Frame Persistence, Appearance Aggregation, And Pull APIs

**Files:**
- Modify: `backend/app/infrastructure/database/models.py`
- Create: `backend/app/infrastructure/database/repositories/live_result_repository.py`
- Create: `backend/app/services/live_appearance_service.py`
- Create: `backend/app/presentation/schemas/live_results.py`
- Create: `backend/app/presentation/routers/live_results.py`
- Create: `backend/alembic/versions/e31c8a7d4f20_live_frame_results.py`
- Modify: `backend/app/presentation/dependencies.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/persistence/test_live_result_repository.py`
- Test: `backend/tests/unit/test_live_appearance_service.py`
- Test: `backend/tests/contract/test_live_results_api.py`

**Interfaces:**
- Produces tables: `live_frame_result`, `live_appearance`.
- Produces: `LiveResultRepository.insert_frame_batch/list_frames/upsert_appearance/list_appearances`.
- Produces endpoints: session frames, session appearances, and face appearances.
- Consumes: safe envelopes only; restricted native evidence is not accepted by the repository.

- [ ] **Step 1: Write failing migration/repository tests**

Insert no-face and face frames, retry the same event IDs, and assert idempotent
rows. Query by generation and half-open UTC range with a `(observed_at_unix_ns,
event_id)` cursor. Assert embeddings/JPEG keys are absent from stored `faces`.

- [ ] **Step 2: Add additive result tables**

```text
live_frame_result:
  event_id UUID primary key
  generation_id UUID FK live_session_generation
  session_id UUID not null
  generation INTEGER not null
  frame_sequence BIGINT not null
  observed_at TIMESTAMPTZ not null
  observed_at_unix_ns NUMERIC(20,0) not null
  pts_ns NUMERIC(20,0) null
  time_basis VARCHAR(32) = mvision_observed_utc
  timing_epoch INTEGER not null
  source_width/source_height INTEGER not null
  faces JSONB not null
  created_at TIMESTAMPTZ not null
  UNIQUE(generation_id, frame_sequence)

live_appearance:
  event_id UUID primary key
  generation_id UUID FK live_session_generation
  session_id UUID not null
  generation INTEGER not null
  native_track_id NUMERIC(20,0) not null
  identity_epoch INTEGER not null
  face_id UUID FK face_identity not null
  status_snapshot VARCHAR(16) not null
  name_snapshot VARCHAR(255) null
  metadata_snapshot JSONB not null
  first_seen_unix_ns/last_seen_unix_ns NUMERIC(20,0) not null
  total_duration_ns NUMERIC(20,0) not null
  intervals JSONB not null
  confidence FLOAT not null
  state VARCHAR(16) not null
  created_at/updated_at TIMESTAMPTZ not null
  UNIQUE(generation_id, native_track_id, identity_epoch)
```

The migration `down_revision` is `d92a7f4c1b30` from Delivery 1.

- [ ] **Step 3: Implement idempotent batch persistence and cursor queries**

Use PostgreSQL `insert(...).on_conflict_do_nothing(index_elements=["event_id"])`
for frames. Order ascending for ingestion and descending for API pages. Page
limits are `1..100`; time filters are `[from, to)`; generation is explicit or
defaults to the current generation.

- [ ] **Step 4: Implement optional appearance lifecycle**

Key state by `(session_id, generation, tracker_id, identity_epoch, face_id)`.
When the first accepted global identity arrives, emit `appearance.started` and
backdate to the earliest retained observation. Extend the current interval while
observations remain within `appearanceGapMs`; otherwise close it and open another.
On `TrackExpiredEvent`, session stop, timing discontinuity, or identity epoch
change, calculate `total_duration_ns = sum(end_ns - start_ns)`, persist the final
row, and emit `appearance.ended`. Pending/non-persistent unknown tracks create no
appearance.

- [ ] **Step 5: Add strict API schemas and routes**

```text
GET /api/v1/live/sessions/{session_id}/frames
GET /api/v1/live/sessions/{session_id}/appearances
GET /api/v1/live/faces/{face_id}/appearances
```

Protect all routes with Delivery 1 API-key auth. Return frame and appearance pages
separately; never expand frame pages into appearances. Return `nextCursor` only
when another page can exist.

- [ ] **Step 6: Run persistence and API tests**

Run: `cd backend && alembic upgrade head && pytest tests/integration/persistence/test_live_result_repository.py tests/unit/test_live_appearance_service.py tests/contract/test_live_results_api.py -q`

Expected: PASS.

---

### Task 8: Supervisor Integration And Delivery 2 Acceptance

**Files:**
- Modify: `backend/app/services/live_supervisor.py`
- Modify: `backend/app/presentation/dependencies.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/unit/test_live_supervisor.py`
- Create: `backend/tests/integration/live/test_live_frame_delivery.py`
- Create: `backend/scripts/live_frame_smoke.py`

**Interfaces:**
- Consumes all prior task interfaces.
- Produces one generation-scoped runtime whose event reader does only validation and nonblocking enqueue.
- Closes appearance and connector/persistence workers deterministically before releasing the lease.

- [ ] **Step 1: Write failing supervisor routing tests**

Assert a `FrameResultEvent` calls projection then delivery without awaiting a
connector. Assert `TrackExpiredEvent` reaches identity and appearance control
paths even when the frame queue is full. Assert wrong session/run/generation or a
lost lease rejects all late work.

- [ ] **Step 2: Refactor supervisor event routing**

Open generation delivery workers before starting the child. Native `on_event`
validates fencing and uses `put_nowait` into frame/control services. Identity
evidence is coalesced per tracker; expiry uses a separate reserved control queue.
On shutdown: stop native input, process critical expiry, finalize appearance,
close delivery workers with bounded drain policy, then fence/finish the run.

- [ ] **Step 3: Wire application lifecycle**

Construct connector factories, projection, anonymous identity, appearance, and
result repositories in `ServiceContainer`. Close shared HTTPX/Kafka resources in
FastAPI lifespan and worker shutdown. Image/video APIs remain operational when a
live connector cannot start.

- [ ] **Step 4: Run deterministic end-to-end fixtures**

Use a fixture containing no-face frames, one known identity, one new anonymous
identity, disappearance/reappearance gap, and a forced PTS rollback. Assert exact
selected frame count/order, original geometry, status transitions, timing epoch,
appearance duration, persistent anonymous reuse, and no restricted fields.

- [ ] **Step 5: Force downstream failures**

Run a slow Webhook, unavailable Kafka broker, saturated frame queue, and failed
PostgreSQL batch. Assert inference continues, critical expiry closes appearance,
event IDs remain stable on retry, and counters expose drops/failures without IDs
as labels.

- [ ] **Step 6: Run the complete Delivery 2 gate**

Run: `cd backend && pytest tests/unit/test_live_protocol.py tests/unit/test_live_frame_projection_service.py tests/unit/test_live_identity_service.py tests/unit/test_live_anonymous_identity_service.py tests/unit/test_live_connectors.py tests/unit/test_live_delivery_service.py tests/unit/test_live_appearance_service.py tests/unit/test_live_supervisor.py tests/contract/test_live_protocol_parity.py tests/contract/test_live_results_api.py tests/integration/persistence/test_live_result_repository.py tests/integration/services/test_live_anonymous_identity.py tests/integration/live/test_live_connector_isolation.py tests/integration/live/test_live_frame_delivery.py -q`

Run: `cmake --build build/pipeline -j"$(nproc)" && ./build/pipeline/test_live_protocol && ./build/pipeline/test_live_frame_state && ./build/pipeline/test_live_runtime_contract && ./build/pipeline/test_live_worker_process`

Run: `git diff --check`

Expected: all tests PASS; frame count equals selected fixture count, no-face frames
are present, and embedding/JPEG sentinel bytes are absent from responses,
persistence, connector captures, and logs.

---

## Self-Review Checklist

- [ ] Native evidence and public frame schemas are distinct.
- [ ] Every selected frame creates one result, including no-face frames.
- [ ] Observed UTC, PTS, and timing epoch cannot be confused.
- [ ] Geometry is transformed back to original source dimensions.
- [ ] Assignment enrichment is fenced by session, run, generation, tracker, epoch, decision sequence, and revision.
- [ ] Persistent anonymous creation uses quality gates, final gallery recheck, serialized reservation, and stable global IDs.
- [ ] Frame, connector, and persistence queues are bounded and independent.
- [ ] Critical expiry is never silently sacrificed to frame throughput.
- [ ] Appearance output is optional, global-ID-only, gap-aware, and durable when enabled.
- [ ] Pull APIs use bounded cursor pages and generation/time filters.
- [ ] Webhook semantics are documented as direct best-effort with in-process retry, not crash-safe at-least-once.
- [ ] No exact recording-frame join, outbox, OIDC, scheduler, or shared pipeline work entered Delivery 2.
