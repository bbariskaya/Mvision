# Phase 1 and Phase 2 Requirements Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the image-recognition and video-processing paths conform to `requirements/ProjectRequirements.md` and `requirements/videorequirements.md`, including identity lifecycle, validation, durable process details, configurable limits, and recoverable asynchronous jobs.

**Architecture:** Preserve the existing FastAPI/service/repository/native-worker boundaries. Apply narrow service and repository corrections, fence video finalization with the existing PostgreSQL lease, and keep process-event writes best-effort while making process/job/result state atomic. Existing PostgreSQL, MinIO, and Qdrant data remains valid and no destructive migration is introduced.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 16, MinIO, Qdrant, pytest, Docker Compose, DeepStream native video worker.

## Global Constraints

- `requirements/ProjectRequirements.md` is authoritative for Phase 1.
- `requirements/videorequirements.md` is authoritative for Phase 2, and all Phase 1 identity rules remain applicable.
- Use red-green-refactor: every behavior change starts with one focused failing test.
- Do not reset volumes, delete persisted identities, or rewrite existing migrations.
- Do not create commits; the user explicitly requested inline work without commits.
- Preserve camelCase HTTP responses and the public statuses `known`, `anonymous`, and `new_anonymous`.
- Logging failure must not turn an otherwise successful recognition or video job into a failure.

## Compliance Matrix

| Requirement | Current defect | Repair task |
| --- | --- | --- |
| Phase 1 lines 14-16 | A JPEG missing its EOI marker is silently repaired instead of rejected as corrupt. | Task 1 |
| Phase 1 lines 38, 42-46 | Enrollment without `faceId` does not preserve a matched anonymous ID and accepts multiple faces by choosing the largest. | Task 1 |
| Phase 1 lines 34-38 | Image recognition and enrollment fall back to storing the full submitted image when aligned face evidence is absent. | Task 1 |
| Phase 1 lines 55-57 | Completed image process records do not persist the required face IDs and statuses in `details`. | Task 2 |
| Phase 2 lines 26, 35-37 | Video voting discards anonymous candidates, so a repeated anonymous face receives a new ID. | Task 3 |
| Phase 2 lines 19, 21, 158 | `VIDEO_MINIO_PREFIX` builds keys that the hard-coded `videos/` validator rejects; the Compose services do not expose all video settings. | Task 4 |
| Phase 2 lines 43-46, 151-154 | No global configurable concurrency gate exists, an exhausted crashed attempt can remain processing forever, and lease loss does not stop the child. | Task 5 |
| Phase 2 lines 46-51 | Pending cancellation leaves its process started, stale transitions can mutate the process, and final process details omit processed counters and identities. | Task 6 |
| Phase 2 lines 18-20 | Cleanup only runs while the queue is idle and source retrieval can continue after retention expiry until cleanup happens. | Task 7 |

## Coverage Decisions

- The API service remains API-only: `backend/app/main.py` exposes no UI or static route. The separately deployed operator frontend is a later optional client and is not coupled to the API container.
- UUIDv7 process IDs remain allocated for recognition, enrollment, update, delete, and video-recognition operations. Read-only identity/history/process queries retrieve durable records and do not create recursive audit processes; this follows the approved Phase 1 backend contract's “when one has already been allocated” rule.
- Video source-frame fallback remains available only for legacy video outputs. Phase 1 image paths must persist native aligned face evidence and must never substitute the full uploaded image.

---

### Task 1: Correct Phase 1 Image Validation and Enrollment Identity Lifecycle

**Files:**
- Modify: `backend/tests/unit/test_image_validation.py`
- Modify: `backend/tests/unit/test_enrollment_service.py`
- Modify: `backend/app/services/image_validation.py`
- Modify: `backend/app/services/enrollment_service.py`
- Modify: `backend/app/services/recognition_service.py`

**Interfaces:**
- Consumes: `normalize_image(data: bytes, content_type: str, max_bytes: int) -> bytes` and `FaceMatch`.
- Produces: `_select_face(faces) -> FaceDetection`, which accepts exactly one detection, `_matching_identity_id(match: FaceMatch | None) -> str | None`, which preserves any matched active identity, and `require_aligned_face_evidence(data: bytes) -> bytes`.

- [ ] **Step 1: Replace the truncated-JPEG expectation with a rejection test**

```python
def test_normalize_image_rejects_jpeg_without_end_marker():
    source = BytesIO()
    Image.new("RGB", (8, 8), (0, 255, 0)).save(source, format="JPEG")

    with pytest.raises(ValidationError) as raised:
        normalize_image(source.getvalue()[:-2], "image/jpeg", 4096)

    assert raised.value.error_code == "INVALID_IMAGE"
```

- [ ] **Step 2: Run the image test and verify RED**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_image_validation.py::test_normalize_image_rejects_jpeg_without_end_marker -q -p no:cacheprovider`

Expected: FAIL because `normalize_image()` appends the missing EOI marker.

- [ ] **Step 3: Remove JPEG repair from `normalize_image()`**

Delete the `data.startswith(...)` / `data.endswith(...)` branch and let Pillow's full decode raise `INVALID_IMAGE`.

- [ ] **Step 4: Add enrollment lifecycle tests**

```python
def test_enrollment_reuses_matching_anonymous_identity():
    identity = SimpleNamespace(face_id="anonymous-id", lifecycle_status="anonymous", name=None)
    assert EnrollmentService._matching_identity_id(
        FaceMatch(identity, "sample-id", 0.91)
    ) == "anonymous-id"


def test_enrollment_reuses_matching_known_identity_when_name_changes():
    identity = SimpleNamespace(face_id="known-id", lifecycle_status="known", name="Old Name")
    assert EnrollmentService._matching_identity_id(
        FaceMatch(identity, "sample-id", 0.91)
    ) == "known-id"


def test_enrollment_rejects_multiple_faces():
    with pytest.raises(ValidationError) as raised:
        EnrollmentService._select_face((SimpleNamespace(), SimpleNamespace()))
    assert raised.value.error_code == "MULTIPLE_FACES"
```

- [ ] **Step 5: Run the enrollment tests and verify RED**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_enrollment_service.py -q -p no:cacheprovider`

Expected: the anonymous reuse, renamed-known reuse, and multiple-face tests fail against the current helper behavior.

- [ ] **Step 6: Implement exact-one enrollment and unconditional matched-ID reuse**

```python
@staticmethod
def _select_face(faces):
    if len(faces) != 1:
        raise ValidationError(
            "Enrollment image must contain exactly one face",
            "NO_FACE" if not faces else "MULTIPLE_FACES",
        )
    return faces[0]

@staticmethod
def _matching_identity_id(match: FaceMatch | None) -> str | None:
    return None if match is None else str(match.identity.face_id)
```

Call `_matching_identity_id(match)` from `enroll()` and fail the process with the original `ValidationError.error_code` rather than replacing it with `INVALID_ENROLLMENT`.

- [ ] **Step 7: Add a failing aligned-evidence boundary test**

```python
def test_require_aligned_face_evidence_rejects_missing_bytes():
    with pytest.raises(InferenceError) as raised:
        require_aligned_face_evidence(b"")
    assert raised.value.error_code == "INFERENCE_ERROR"
```

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_image_validation.py::test_require_aligned_face_evidence_rejects_missing_bytes -q -p no:cacheprovider`

Expected: FAIL because the boundary function does not exist.

- [ ] **Step 8: Require native aligned evidence in both image paths**

```python
def require_aligned_face_evidence(data: bytes) -> bytes:
    if not data:
        raise InferenceError("GPU worker did not return aligned face evidence")
    return data
```

Replace both `detection.aligned_jpeg or image` expressions with `require_aligned_face_evidence(detection.aligned_jpeg)`.

- [ ] **Step 9: Verify Task 1 GREEN**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_image_validation.py backend/tests/unit/test_enrollment_service.py backend/tests/contract/test_faces_api.py -q -p no:cacheprovider`

Expected: PASS.

### Task 2: Persist Complete Phase 1 Process Task Details

**Files:**
- Modify: `backend/tests/unit/test_enrollment_service.py`
- Modify: `backend/tests/unit/test_video_job_repository.py`
- Modify: `backend/app/infrastructure/database/repositories/process_repository.py`
- Modify: `backend/app/services/recognition_service.py`
- Modify: `backend/app/services/enrollment_service.py`
- Modify: `backend/app/services/identity_service.py`

**Interfaces:**
- Produces: `ProcessRecordRepository.complete(..., details: dict | None = None) -> ProcessRecord | None`.
- Details shape: `{"operation": str, "face_count": int, "faces": [{"face_id": str, "status": str}]}` plus video metadata in Task 6.

- [ ] **Step 1: Add a repository statement test for completion details**

Create a recording fake session and assert that `complete(..., details=payload)` writes `status`, `face_count`, `completed_at`, and `details` in one update.

- [ ] **Step 2: Run the test and verify RED**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_job_repository.py -q -p no:cacheprovider`

Expected: FAIL because `complete()` does not accept `details`.

- [ ] **Step 3: Extend the process completion interface**

```python
async def complete(
    self,
    session: AsyncSession,
    process_id: str,
    face_count: int,
    details: dict | None = None,
) -> ProcessRecord | None:
    values: dict = {
        "status": "completed",
        "face_count": face_count,
        "completed_at": func.now(),
    }
    if details is not None:
        values["details"] = details
    stmt = (
        update(ProcessRecord)
        .where(ProcessRecord.process_id == process_id)
        .values(**values)
        .returning(ProcessRecord)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
```

- [ ] **Step 4: Pass immutable task summaries from recognition and enrollment**

For recognition, persist operation, count, face IDs, and statuses from `faces`. For enrollment, persist one known face. For identity update/delete, include the selected face ID and operation in the existing process record.

- [ ] **Step 5: Verify Task 2 GREEN**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit backend/tests/contract/test_faces_api.py -q -p no:cacheprovider --ignore=backend/tests/unit/test_live_protocol.py`

Expected: PASS for Phase 1 and repository tests.

### Task 3: Restore Anonymous Identity Matching and Voting Semantics for Video

**Files:**
- Modify: `backend/tests/unit/test_video_identity_voting_service.py`
- Modify: `backend/app/services/video_identity_voting_service.py`

**Interfaces:**
- Consumes: active `FaceMatch` candidates from `FaceMatcher.candidates_batch()`.
- Produces: `VideoIdentityDecision` for known or anonymous identities using lifecycle-specific strong thresholds and configured consensus controls.

- [ ] **Step 1: Add failing lifecycle tests**

Add tests proving that a strong existing anonymous candidate returns the same `face_id`, that known and anonymous strong thresholds are distinct, that one weak vote is rejected, and that weak consensus needs `VIDEO_TRACK_VOTE_MIN_COUNT` plus `VIDEO_TRACK_VOTE_MIN_SUPPORT_RATIO`.

- [ ] **Step 2: Run the voting tests and verify RED**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_identity_voting_service.py -q -p no:cacheprovider`

Expected: anonymous reuse and consensus-rule tests fail because the current implementation filters to known identities and ignores two configured controls.

- [ ] **Step 3: Aggregate active known and anonymous candidates**

For each source template, collapse gallery samples to one best candidate per identity. Admit a candidate when it reaches either its lifecycle strong threshold or the consensus candidate floor. Compute weighted mean, vote count, support ratio, and runner-up margin per identity.

- [ ] **Step 4: Apply strong-single or consensus acceptance**

```python
threshold = (
    settings.recognition_threshold
    if winner.identity.lifecycle_status == "known"
    else settings.anonymous_threshold
)
strong = max(winner.scores) >= threshold
consensus = (
    winner.votes >= settings.video_track_vote_min_count
    and winner.weight / total_weight >= settings.video_track_vote_min_support_ratio
)
accepted = (strong or consensus) and (
    winner.mean_score - runner_score >= settings.video_track_vote_min_margin
)
```

Return the nearest rejected score when no identity is accepted so new-anonymous confidence remains meaningful.

- [ ] **Step 5: Verify Task 3 GREEN**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_identity_voting_service.py backend/tests/unit/test_video_result_service.py -q -p no:cacheprovider`

Expected: PASS.

### Task 4: Make Video Storage and Operational Limits Truly Configurable

**Files:**
- Modify: `backend/tests/unit/test_video_job_repository.py`
- Modify: `backend/tests/unit/test_video_storage.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/infrastructure/object_storage/minio_adapter.py`
- Modify: `backend/.env.example`
- Modify: `docker-compose.sprint01.yml`

**Interfaces:**
- Produces: `Settings.video_max_concurrent_jobs: int` with a positive value.
- Preserves: persisted safe object keys from any configured prefix, including the existing `videos/<uuid>/source` shape.

- [ ] **Step 1: Add failing settings and custom-prefix storage tests**

```python
def test_video_max_concurrent_jobs_is_environment_configurable(monkeypatch):
    monkeypatch.setenv("VIDEO_MAX_CONCURRENT_JOBS", "7")
    assert Settings(_env_file=None).video_max_concurrent_jobs == 7


@pytest.mark.asyncio
async def test_video_key_accepts_safe_configured_prefix():
    adapter = _adapter()
    key = "archive/input/019f8000-0000-7000-8000-000000000001/source"
    await adapter.read_video_range(key, offset=0, length=5)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_job_repository.py backend/tests/unit/test_video_storage.py -q -p no:cacheprovider`

Expected: missing setting and hard-coded prefix failures.

- [ ] **Step 3: Add bounded settings and safe persisted-key validation**

Add `video_max_concurrent_jobs = Field(default=3, gt=0)` and positive bounds to upload, duration, retention, timeout, lease, attempt, progress, and polling values. Validate object keys by safe POSIX components, UUID job directory, and final `source` component instead of one hard-coded prefix.

- [ ] **Step 4: Expose every operational setting to API and video workers**

Add `VIDEO_MINIO_PREFIX`, `VIDEO_MAX_CONCURRENT_JOBS`, timeout, lease, attempts, progress interval, appearance gap, polling, and native/config path variables to `.env.example` and the relevant Compose service environments.

- [ ] **Step 5: Verify Task 4 GREEN**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_storage.py backend/tests/unit/test_video_job_repository.py -q -p no:cacheprovider`

Run: `docker compose -f docker-compose.sprint01.yml config --quiet`

Expected: both commands pass.

### Task 5: Enforce Global Concurrency and Recover Exhausted Leases

**Files:**
- Modify: `backend/tests/unit/test_video_job_repository.py`
- Modify: `backend/tests/unit/test_video_worker.py`
- Modify: `backend/app/infrastructure/database/repositories/video_job_repository.py`
- Modify: `backend/app/services/video_processor.py`

**Interfaces:**
- Changes: `claim_next(..., max_concurrent_jobs: int) -> VideoJob | None`.
- Produces: `settle_exhausted(session, now) -> list[tuple[str, str]]`, returning process ID and terminal status.
- Produces: `lock_owned(session, job_id, worker_id, lease_token, now) -> VideoJob | None` for finalization fencing.

- [ ] **Step 1: Add failing repository tests**

Test that `claim_next` takes the configured limit, serializes claim admission with a PostgreSQL transaction advisory lock, and refuses a claim when active non-expired processing/cancelling jobs reach the limit. Test that expired final attempts become `failed` and expired cancelling attempts become `cancelled`.

- [ ] **Step 2: Run repository tests and verify RED**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_job_repository.py -q -p no:cacheprovider`

Expected: FAIL because concurrency admission and exhausted settlement do not exist.

- [ ] **Step 3: Implement serialized admission and terminal recovery**

Use `pg_advisory_xact_lock` before counting active leases and selecting with `FOR UPDATE SKIP LOCKED`. Keep the existing FIFO queue order. Settle expired exhausted jobs before each claim and update each associated process to the same terminal state in the processor transaction.

- [ ] **Step 4: Add failing lease-loss processor tests**

Test that a false progress update or false lease renewal sets a lease-loss event, causes native cancellation, and never calls job/process complete, cancel, fail, or retry through the stale token.

- [ ] **Step 5: Implement lease-loss propagation**

Use one `asyncio.Event` shared by renewal, progress, and cancellation checks. Raise a private `VideoLeaseLostError` from stale progress. If native cancellation occurs with the event set, return without mutating durable state; a valid owner will recover the expired lease.

- [ ] **Step 6: Verify Task 5 GREEN**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_job_repository.py backend/tests/unit/test_video_worker.py backend/tests/unit/test_native_video_runner.py -q -p no:cacheprovider`

Expected: PASS.

### Task 6: Fence Finalization and Keep Job, Process, and Cancellation State Consistent

**Files:**
- Modify: `backend/tests/unit/test_video_result_service.py`
- Modify: `backend/tests/unit/test_video_worker.py`
- Modify: `backend/tests/unit/test_video_services.py`
- Modify: `backend/app/infrastructure/database/repositories/video_track_repository.py`
- Modify: `backend/app/infrastructure/video/native_runner.py`
- Modify: `backend/app/services/video_result_service.py`
- Modify: `backend/app/services/video_processor.py`
- Modify: `backend/app/services/video_job_service.py`
- Modify: `backend/app/presentation/dependencies.py`

**Interfaces:**
- Produces: `VideoFinalizationResult(person_count: int, faces: tuple[dict[str, str], ...])`.
- Changes: `VideoResultService.finalize(job, raw_tracks, source_path, worker_id, lease_token, processed_frames)` performs fenced result/job/process completion.
- Produces: `VideoTrackRepository.delete_for_job(session, job_id) -> None`.
- Produces: `NativeVideoTimeoutError` and `NativeVideoFailedError(error_code, message)`.

- [ ] **Step 1: Add failing finalization fencing tests**

Test that finalization refuses a missing/expired lease before persisting results, uses deterministic IDs for a job/track retry, and commits tracks, completed job state, process details, processed frame count, face IDs, and statuses together.

- [ ] **Step 2: Run result tests and verify RED**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_result_service.py -q -p no:cacheprovider`

Expected: FAIL because finalization has no lease inputs and job/process completion happens later in a separate transaction.

- [ ] **Step 3: Move completion into the fenced finalization transaction**

Lock the owned non-expired job row before any result writes. Derive deterministic UUIDs from `job_id`, canonical track source IDs, and ordinal for video track, recognition result, and newly anonymous face/sample IDs. Persist process details with video metadata, processed frame count, person count, and face snapshots. Complete the job and process before committing the same session.

- [ ] **Step 4: Add cancellation consistency tests**

Test that pending cancellation cancels the process immediately and removes partial tracks, processing cancellation waits for the owner, stale `mark_cancelled` does not cancel the process, repeated terminal cancellation is idempotent, and completion refuses `cancellation_requested=True`.

- [ ] **Step 5: Implement cancellation transitions**

Inject `ProcessRecordRepository` into `VideoJobService`. Delete partial tracks and cancel the process only when the repository transition succeeds. In the processor, gate process mutation on a successful job transition.

- [ ] **Step 6: Preserve timeout and native failure codes**

Raise `NativeVideoTimeoutError` for deadline expiry and `NativeVideoFailedError` for native failed events. Retry with their stable code and persist `VIDEO_PROCESSING_TIMEOUT` on final timeout instead of collapsing every failure to `VIDEO_PIPELINE_ERROR`.

- [ ] **Step 7: Write completion/cancellation events best-effort**

After the core transaction commits, write `video_job_completed`, `video_job_cancelled`, or `video_job_failed` in a separate guarded transaction so event failure cannot alter the durable outcome.

- [ ] **Step 8: Verify Task 6 GREEN**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_result_service.py backend/tests/unit/test_video_worker.py backend/tests/unit/test_native_video_runner.py backend/tests/contract/test_videos_api.py -q -p no:cacheprovider`

Expected: PASS.

### Task 7: Enforce Retention During Continuous Work and Complete Appearance References

**Files:**
- Modify: `backend/tests/unit/test_video_retention.py`
- Modify: `backend/tests/contract/test_videos_api.py`
- Modify: `backend/app/services/video_job_service.py`
- Modify: `backend/app/worker/video_worker_main.py`
- Modify: `backend/app/presentation/schemas/videos.py`

**Interfaces:**
- Source access returns `410 VIDEO_EXPIRED` as soon as `source_retention_until` has passed, independently of cleanup scheduling.
- Appearance rows include `process_id` and `video_url` as durable references.

- [ ] **Step 1: Add failing retention tests**

Test immediate `410` after the retention timestamp, per-object cleanup failure isolation, and cleanup invocation after a processed job rather than only when the queue is idle.

- [ ] **Step 2: Run retention tests and verify RED**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_retention.py -q -p no:cacheprovider`

Expected: FAIL for timestamp enforcement, failure isolation, and continuous-load cleanup.

- [ ] **Step 3: Implement retention enforcement**

Check `source_retention_until <= datetime.now(UTC)` in `source()`. Catch and log each MinIO deletion failure while committing successful deletions. Call bounded cleanup every worker loop iteration, sleeping only when no job was processed.

- [ ] **Step 4: Add and implement complete appearance references**

Extend `FaceVideoAppearanceResponse` and `appearances()` with `processId` and `/api/v1/videos/jobs/{jobId}/video`, retaining `sourceAvailable` so callers can distinguish an expired reference.

- [ ] **Step 5: Verify Task 7 GREEN**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit/test_video_retention.py backend/tests/contract/test_videos_api.py -q -p no:cacheprovider`

Expected: PASS.

### Task 8: Full Regression, Static, Compose, and Native Verification

**Files:**
- Modify only files required by failures caused by Tasks 1-7.

**Interfaces:**
- No new interfaces; this task verifies the repaired baseline.

- [ ] **Step 1: Run all Python unit and contract tests except the separately built native parity executable**

Run: `backend/.venv/bin/python -m pytest backend/tests/unit backend/tests/contract -q -p no:cacheprovider --ignore=backend/tests/contract/test_live_protocol_parity.py`

Expected: PASS with no Phase 1/2 failures.

- [ ] **Step 2: Run lint without the unwritable repository cache**

Run: `RUFF_NO_CACHE=1 backend/.venv/bin/python -m ruff check backend/app backend/tests`

Expected: PASS.

- [ ] **Step 3: Run type checking**

Run: `backend/.venv/bin/python -m mypy backend/app`

Expected: PASS, including a concrete annotation for `EnrollmentService._select_face`.

- [ ] **Step 4: Run Compose and migration validation**

Run: `docker compose -f docker-compose.sprint01.yml config --quiet`

Run: `backend/.venv/bin/alembic -c backend/alembic.ini heads`

Expected: valid Compose configuration and one Alembic head.

- [ ] **Step 5: Run native non-GPU tests when the build artifacts are present**

Run: `make native-test`

Expected: the pinned native test image builds, all 13 CTest targets pass, and Python/native live protocol parity passes.

- [ ] **Step 6: Inspect the final worktree**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors and only intended files changed; unrelated pre-existing user changes remain untouched.
