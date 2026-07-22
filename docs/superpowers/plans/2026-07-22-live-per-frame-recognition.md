# Live Per-Frame Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cached decision-time cosine with a true current-frame ArcFace cosine and permit safe identity changes through hysteresis and sustained gallery confirmation.

**Architecture:** Python resolves gallery identities and sends a validated 512-float reference embedding only on identity transitions. Native C++ runs ArcFace on every eligible frame, computes cosine locally against that reference, and applies three-frame display hysteresis. Gallery switching remains threshold-and-margin gated every five eligible frames and requires three consecutive wins.

**Tech Stack:** Python 3.12, C++17, MessagePack, NVIDIA DeepStream 9, TensorRT ArcFace, Qdrant, pytest, CTest.

## Global Constraints

- Remove `LiveEventService._assignments` as an OSD score source; do not replace it with another score cache.
- Keep the active normalized reference embedding in native memory; recompute cosine from each new ArcFace output.
- Never put reference embeddings in argv, stdout events, logs, metrics, PostgreSQL, or error text.
- Never call Qdrant, PostgreSQL, object storage, or blocking IPC from a pad probe.
- Known decisions require absolute threshold and top-2 margin.
- Visible labels use three-frame hysteresis; gallery identity switches use three consecutive five-frame evaluations.
- Track expiry clears reference vectors, scores, streaks, and candidate state.
- Do not commit unless the user explicitly requests a commit.

---

### Task 1: Extend The Framed Identity Assignment Contract

**Files:**
- Modify: `backend/app/infrastructure/live/protocol.py`
- Modify: `backend/pipeline/include/mvision/live_protocol.hpp`
- Modify: `backend/pipeline/src/live_protocol.cpp`
- Modify: `backend/tests/unit/test_live_protocol.py`
- Modify: `backend/pipeline/tests/test_live_protocol.cpp`

**Interfaces:**
- Produces: Python `IdentityAssignment.reference_embedding: tuple[float, ...] | None`.
- Produces: C++ `IdentityAssignment::reference_embedding: std::optional<std::array<float, 512>>`.
- Known payloads require 512 finite floats; Unknown payloads require `null`.

- [ ] **Step 1: Write Python RED contract tests**

Add tests that round-trip a normalized 512-float reference and reject a 511-float vector, NaN, infinity, Known-with-null, and Unknown-with-vector.

```python
reference = tuple([1.0] + [0.0] * 511)
assignment = IdentityAssignment(
    _header("identity_assignment", 2), 42, 1, 1, "known",
    "Baris", FACE_ID, 0.83, reference, 7,
)
assert decode(encode(assignment)) == assignment
```

- [ ] **Step 2: Run Python RED test**

Run: `docker exec mvision-live-api pytest -q /app/tests/unit/test_live_protocol.py`

Expected: FAIL because `IdentityAssignment` has no `reference_embedding` and the codec accepts no such field.

- [ ] **Step 3: Write C++ RED parity tests**

Construct the same 512-float assignment in `test_live_protocol.cpp`, assert exact vector length/value parity, and add malformed payload fixtures for dimension and finite-value rejection.

- [ ] **Step 4: Run C++ RED test**

Run: `cmake --build build/pipeline --target test_live_protocol -j2 && ./build/pipeline/test_live_protocol`

Expected: compile failure because the C++ assignment has no reference vector.

- [ ] **Step 5: Implement strict codecs**

Add the field immediately before `decision_sequence` in both structs/codecs. Reuse the existing embedding validators. Enforce this invariant after decoding:

```python
if identity_state == "known":
    if display_name is None or face_id is None or match_score is None:
        raise ValueError("INVALID_IDENTITY_ASSIGNMENT")
    reference_embedding = _embedding(payload["reference_embedding"])
else:
    if any(value is not None for value in (
        display_name, face_id, match_score, payload["reference_embedding"]
    )):
        raise ValueError("INVALID_IDENTITY_ASSIGNMENT")
    reference_embedding = None
```

Use equivalent C++ validation with `std::array<float, 512>` and `std::isfinite`.

- [ ] **Step 6: Run GREEN protocol gates**

Run both commands from Steps 2 and 4.

Expected: all Python protocol tests pass; C++ parity executable exits 0.

---

### Task 2: Retrieve Reference Embeddings And Remove Assignment Score Caching

**Files:**
- Modify: `backend/app/services/live_identity_service.py`
- Modify: `backend/app/services/live_event_service.py`
- Modify: `backend/app/presentation/dependencies.py`
- Modify: `backend/tests/unit/test_live_identity_service.py`
- Modify: `backend/tests/unit/test_live_event_service.py`

**Interfaces:**
- `LiveIdentityService(settings, voter, vector_store)` consumes `vector_store.get(sample_id)`.
- `LiveIdentityDecision` gains `reference_embedding: tuple[float, ...] | None`, `transition: Literal["none", "known", "unknown"]`, and `evaluation_sequence: int`.
- `LiveEventService.accept_decision(...) -> tuple[IdentityAssignment, ...]` returns no command for score-only evaluations and reset-plus-known commands for a confirmed replacement.

- [ ] **Step 1: Write RED vector retrieval tests**

Use a fake vector store returning `{"vector": [1.0] + [0.0] * 511}`. Assert a confirmed Known decision carries the normalized tuple. Reject missing, malformed, zero-norm, NaN, and infinity vectors without emitting a Known transition.

- [ ] **Step 2: Write RED cache-removal tests**

Replace the old assertion that retries return the same assignment revision. Require no `_assignments` member and no duplicate command/event for a non-transition evaluation:

```python
first = await service.accept_decision(CAMERA_ID, RUN_ID, 1, evidence, known_transition)
steady = await service.accept_decision(CAMERA_ID, RUN_ID, 1, newer, known_steady)
assert len(first) == 1
assert steady == ()
assert len(events.rows) == 1
```

- [ ] **Step 3: Run RED service tests**

Run: `docker exec mvision-live-api pytest -q /app/tests/unit/test_live_identity_service.py /app/tests/unit/test_live_event_service.py`

Expected: FAIL on missing vector dependency/decision fields and cached assignment behavior.

- [ ] **Step 4: Implement validated reference retrieval**

Retrieve only after a named candidate has satisfied voting. Validate and normalize before constructing the transition:

```python
point = await self._vector_store.get(vote.match.sample_id)
reference = self._validated_reference(point)
if reference is None:
    return self._pending_decision(state, quality)
```

Do not log `point`, `reference`, or protocol payloads.

- [ ] **Step 5: Remove `_assignments` and separate events from commands**

Delete the assignment cache from `LiveEventService`. Persist only `known` and sustained `unknown` transitions. Build commands from transition decisions; return `()` for steady state. Preserve database unique-key deduplication and known cooldown.

- [ ] **Step 6: Inject Qdrant and run GREEN tests**

Change `dependencies.py` to `LiveIdentityService(settings, video_voter, qdrant)` and run the Step 3 command.

Expected: all selected tests pass and no test/log representation contains a reference embedding.

---

### Task 3: Add Five-Frame Gallery Evaluation And Sustained Switching

**Files:**
- Modify: `backend/pipeline/include/mvision/live_track_state.hpp`
- Modify: `backend/pipeline/src/live_pipeline.cpp`
- Modify: `backend/app/services/live_identity_service.py`
- Modify: `backend/app/services/live_supervisor.py`
- Modify: `backend/tests/unit/test_live_identity_service.py`
- Modify: `backend/tests/unit/test_live_supervisor.py`
- Modify: `backend/pipeline/tests/test_live_track_state.cpp`

**Interfaces:**
- Native emits a quality-gated `TrackEvidenceEvent` every fifth eligible frame per tracker.
- `_TrackIdentity` tracks `candidate_face_id`, `candidate_wins`, `rejected_windows`, and `evaluation_sequence`.
- Supervisor enqueues every command returned by `accept_decision` in order.

- [ ] **Step 1: Write RED switching tests**

Cover these exact sequences:

```text
A, A, A       -> Known A
B, B          -> remains A
B              -> Unknown reset at epoch+1, then Known B at epoch+1
none, none     -> remains B
none           -> Unknown at epoch+2
A, none, A     -> no three-win transition
```

Every candidate must already pass threshold and top-2 margin through `VideoIdentityVotingService`.

- [ ] **Step 2: Write RED native cadence test**

Feed 15 eligible observations for one tracker and assert gallery evidence revisions occur at frames 5, 10, and 15 while per-frame ArcFace output remains available separately.

- [ ] **Step 3: Run RED tests**

Run:

```bash
docker exec mvision-live-api pytest -q /app/tests/unit/test_live_identity_service.py /app/tests/unit/test_live_supervisor.py
cmake --build build/pipeline --target test_live_track_state -j2 && ./build/pipeline/test_live_track_state
```

Expected: switching and cadence assertions fail.

- [ ] **Step 4: Implement bounded candidate state**

Increment a candidate streak only when the same face wins the next evaluation. Reset the streak on a different face or rejected window. At three wins, increment epoch, request Unknown reset, then assign the new Known identity. At three rejected windows, increment epoch and transition to Unknown.

- [ ] **Step 5: Implement ordered command emission**

Change supervisor handling to preserve reset-before-known order:

```python
commands_to_send = await event_service.accept_decision(...)
for command in commands_to_send:
    commands.put_nowait(command)
```

- [ ] **Step 6: Run GREEN switching gates**

Run the Step 3 commands.

Expected: all selected Python and C++ tests pass.

---

### Task 4: Compute Current-Frame Cosine And Three-Frame Hysteresis In Native OSD

**Files:**
- Modify: `backend/pipeline/include/mvision/live_osd_state.hpp`
- Modify: `backend/pipeline/src/live_osd_state.cpp`
- Modify: `backend/pipeline/src/live_pipeline.cpp`
- Modify: `backend/pipeline/tests/test_live_osd_state.cpp`

**Interfaces:**
- Add `LiveOsdState::observe(tracker_id, current_embedding, threshold)`.
- `label()` renders only the score produced by the most recent `observe()` call.
- `apply()` installs/replaces identity reference data; it does not install a persistent OSD cosine.

- [ ] **Step 1: Write RED current-frame score tests**

Use a unit reference vector and observations with cosine `0.90`, `0.70`, and `0.20`. Assert the label changes after every `observe()` call while detector confidence is independent.

- [ ] **Step 2: Write RED hysteresis tests**

Assert one/two low frames preserve Known, the third shows Unknown, one/two high frames preserve Unknown, and the third restores the assigned name. Assert expiry returns `Pending` and removes score/reference state.

- [ ] **Step 3: Run RED OSD test**

Run: `cmake --build build/pipeline --target test_live_osd_state -j2 && ./build/pipeline/test_live_osd_state`

Expected: compile failure because `observe()` does not exist.

- [ ] **Step 4: Implement allocation-free cosine and hysteresis**

Store the reference as `std::array<float, 512>`. Compute:

```cpp
float cosine = std::inner_product(current.begin(), current.end(),
                                  reference.begin(), 0.0F);
cosine = std::clamp(cosine, -1.0F, 1.0F);
```

Maintain separate consecutive-high and consecutive-low counters capped at 3. Do not mutate the assigned face ID because of a single frame.

- [ ] **Step 5: Call `observe()` from `on_result_buffer`**

After validating the 512-float ArcFace row and before OSD metadata rendering, pass the current embedding to the track's OSD state. Missing embeddings do not advance either streak.

- [ ] **Step 6: Run GREEN OSD tests**

Run the Step 3 command.

Expected: executable exits 0 with exact changing labels.

---

### Task 5: Eliminate DeepStream Secondary Classifier Cache And Prove Coverage

**Files:**
- Modify: `backend/pipeline/src/live_pipeline.cpp`
- Modify: `backend/pipeline/include/mvision/live_pipeline.hpp`
- Modify: `backend/pipeline/tools/smoke_live_pipeline.cpp`

**Interfaces:**
- SGIE uses preprocessed tensor-input mode in primary processing mode so tracker-keyed secondary classifier caching cannot reuse the first embedding.
- Counters expose `embedding_count`, `embedding_cosine_samples`, and distinct embedding movement in worker metrics.

- [ ] **Step 1: Add RED smoke assertions**

For a moving face fixture, require more than one ArcFace output after the first frame and require `embedding_cosine_samples > 1`. The test must fail if only the first tracker embedding is reused.

- [ ] **Step 2: Run RED fixture smoke**

Run:

```bash
cmake --build build/pipeline --target smoke_live_pipeline -j2
./build/pipeline/smoke_live_pipeline 0 configs/video_pgie_yolov8_face.txt configs/video_tracker_nvdcf.yml configs/video_preprocess_arcface.txt configs/video_sgie_arcface_r50.txt 30 120 <<< 'rtsp://rtsp-fixture:8555/friends'
```

Expected: fail until reinference mode and exported counters are explicit.

- [ ] **Step 3: Override SGIE processing mode**

Because `nvdspreprocess` already supplies per-object ROI tensors through `input-tensor-meta`, set the downstream SGIE GObject `process-mode` to primary (`1`) and `interval` to `0`. This bypasses tracker-ID classifier result caching while retaining ROI tensor batches. Do not rely on an unavailable `secondary-reinfer-interval` GObject property in DeepStream 9.

- [ ] **Step 4: Export complete inference counters**

Include embedding count/coverage and cosine sample counters in native metrics without exposing embedding values.

- [ ] **Step 5: Run GREEN fixture smoke**

Run the 120-frame fixture smoke again.

Expected: decoded frames advance, embedding outputs continue after frame one, distinct movement is observed, output is ready, and pipeline errors remain zero.

---

### Task 6: Full Regression And Live Camera Acceptance

**Files:**
- Modify: `docs/superpowers/plans/2026-07-21-single-camera-livestream.md`
- Modify: `docs/implementation/CURRENT_SPRINT.md`

**Interfaces:**
- No new production interfaces.

- [ ] **Step 1: Run Python regression gates**

Run the live protocol, identity, event, supervisor, camera, and integration persistence test suites in the isolated test stores.

Expected: zero failures.

- [ ] **Step 2: Run native regression gates**

Build and run live protocol, track state, OSD state, worker process, and fixture smoke tests.

Expected: zero failures and zero protocol output contamination.

- [ ] **Step 3: Run static gates**

Run Ruff and mypy on changed Python files, `git diff --check`, and the native warning-clean build.

Expected: zero changed-file errors.

- [ ] **Step 4: Run live Baris acceptance**

Keep the laptop publisher active. Capture sequential annotated frames while Baris looks forward, closes an eye, turns, and returns. Assert at least three distinct cosine labels, three low frames produce Unknown, and three high frames restore Baris.

- [ ] **Step 5: Run replacement-person acceptance**

Have an unregistered person enter the same tracker region. Assert Unknown within three below-threshold frames and no Baris carryover. If a second registered identity is available, assert it requires three five-frame gallery wins before switching.

- [ ] **Step 6: Verify output isolation and document evidence**

Decode five RTSP frames with FFmpeg, attach a stalled viewer, and verify inference counters continue. Record exact commands, scores, event rows, and limitations in the canonical plan and sprint status.
