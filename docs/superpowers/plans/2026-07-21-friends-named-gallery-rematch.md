# Friends Named-Gallery Rematch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the isolated Friends gallery and produce a correct 100-frame annotation using the highest named-cast cosine match at or above 0.60.

**Architecture:** Keep native per-object embedding extraction and canonical video tracks unchanged. Restrict video identity voting to active known identities, return an explicit decision carrying either the accepted match or rejected nearest-known score, and keep Friends storage isolated. Validate deployment and recognition through a clean Friends-only rebuild and deterministic 100-frame run.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/PostgreSQL, Qdrant, MinIO, pytest, Docker Compose, FFmpeg/ASS, DeepStream C++ worker.

## Global Constraints

- Only active identities with `lifecycle_status=known` compete for labels.
- Known match threshold and vote candidate floor are exactly `0.60`.
- Select the highest-scoring eligible known identity per template and the strongest weighted track winner; anonymous identities cannot suppress it.
- Return `Unknown` only when no named candidate reaches 0.60; do not apply margin or minimum-consensus rejection.
- Every annotation includes bounding box, name or `Unknown`, detector score, cosine score, and five landmarks.
- Require `totalFrames=100` and `processedFrames=100` before accepting the run.
- Never modify non-Friends PostgreSQL, Qdrant, MinIO, API, or worker state.
- Do not run the 6665-frame source until the 100-frame fixture passes.
- Do not commit unless the user explicitly asks.

---

### Task 1: Named-Only Video Decisions

**Files:**
- Modify: `backend/app/services/video_identity_voting_service.py`
- Modify: `backend/app/services/video_result_service.py`
- Modify: `backend/tests/unit/test_video_identity_voting_service.py`
- Modify: `backend/tests/unit/test_video_result_service.py`

**Interfaces:**
- Produces: `VideoIdentityDecision(match: FaceMatch | None, score: float | None)`.
- Produces: `VideoIdentityVotingService.resolve(track) -> VideoIdentityDecision`.
- Consumes: `FaceMatcher.candidates(embedding, minimum_score=0.0)` so rejected nearest-known scores remain observable.

- [ ] **Step 1: Add failing decision tests**

Add tests proving that an anonymous `1.0` candidate cannot beat a known `0.72` candidate, two known candidates select the higher score, a single known `0.60` candidate is accepted without consensus, a known `0.59` candidate is rejected, and rejection preserves `0.59` rather than manufacturing zero.

```python
decision = await voter.resolve(_track([1.0]))
assert decision.match.identity.face_id == "known-face"
assert decision.score == pytest.approx(0.72)

decision = await voter.resolve(_track([2.0]))
assert decision.match is None
assert decision.score == pytest.approx(0.59)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_video_identity_voting_service.py tests/unit/test_video_result_service.py -q`

Expected: failures because `resolve()` still returns `FaceMatch | None` and anonymous candidates are not filtered.

- [ ] **Step 3: Implement the explicit decision**

Add an immutable decision type, filter every candidate set to `identity.lifecycle_status == "known"`, preserve the nearest-known score, and return the strongest weighted winner whenever at least one named candidate reaches 0.60. Remove margin and minimum-consensus rejection from this Friends matching path.

```python
@dataclass(frozen=True)
class VideoIdentityDecision:
    match: FaceMatch | None
    score: float | None
```

Change `VideoResultService.finalize()` and `_identity_outcome()` to consume the decision. Persist the decision score for accepted and rejected tracks; use `None` when Qdrant has no known candidate.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/unit/test_video_identity_voting_service.py tests/unit/test_video_result_service.py scripts/test_annotate_video.py -q`

Expected: all tests pass.

### Task 2: Confidence Contract and Annotation Overlay

**Files:**
- Modify: `backend/app/infrastructure/database/models.py`
- Create: `backend/alembic/versions/<revision>_nullable_video_match_confidence.py`
- Modify: `backend/app/presentation/schemas/videos.py`
- Modify: `backend/scripts/annotate_video.py`
- Modify: `backend/scripts/test_annotate_video.py`
- Modify: `backend/tests/unit/test_video_result_service.py`

**Interfaces:**
- Produces: nullable video result/track confidence for the no-known-candidate case.
- Produces: annotation text `Name | cos 0.720 | det 0.850` or `Unknown | cos n/a | det 0.850`.

- [ ] **Step 1: Add failing nullable-confidence and overlay tests**

Assert that a rejected nearest-known score renders numerically, no candidate renders `cos n/a`, each detection emits one box event plus one label event plus five landmark events, and malformed landmark counts fail validation rather than silently presenting incomplete alignment evidence.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/test_video_result_service.py scripts/test_annotate_video.py -q`

Expected: failures on nullable confidence and `cos n/a`.

- [ ] **Step 3: Implement the contract**

Make video-only `match_confidence` columns and response confidence nullable, add the Alembic migration, and render `n/a` only when confidence is absent. Keep detector confidence and all five transformed landmark coordinates from each detection.

- [ ] **Step 4: Run migration and focused tests**

Run: `uv run alembic upgrade head`

Run: `uv run pytest tests/unit/test_video_result_service.py scripts/test_annotate_video.py -q`

Expected: migration succeeds and tests pass.

### Task 3: Friends Runtime Deployment

**Files:**
- Modify: `docker-compose.friends.yml`
- Test: `backend/tests/unit/test_video_worker.py`

**Interfaces:**
- Consumes: current `backend/app` mounted at `/workspace/backend/app:ro` in the Friends video worker.
- Produces: final native `processed_frames` persisted by `VideoJobRepository.complete(..., processed_frames=...)`.

- [ ] **Step 1: Set Friends thresholds to 0.60**

Set both values exactly:

```yaml
RECOGNITION_THRESHOLD: "0.60"
VIDEO_TRACK_VOTE_CANDIDATE_FLOOR: "0.60"
```

- [ ] **Step 2: Verify the worker mount and frame-count regression test**

Run: `uv run pytest tests/unit/test_video_worker.py -q`

Expected: tests prove native completion count is passed to repository completion.

- [ ] **Step 3: Recreate Friends services**

Run: `docker compose -f docker-compose.friends.yml up -d --force-recreate friends-api friends-video-worker-0`

- [ ] **Step 4: Inspect live deployment**

Verify worker source contains `processed_frames=native_completed.processed_frames`; verify both containers report threshold `0.60`; verify `/health` on port 8001.

### Task 4: Clean and Re-Enroll Friends Gallery

**Files:**
- Create: `backend/scripts/import_friends_dataset.py`
- Create: `backend/scripts/test_import_friends_dataset.py`

**Interfaces:**
- Consumes: `friends_chars/Friends/Train/{Chandler,Joey,Monica,Phoebe,Rachel,Ross}`.
- Produces: exactly six active known identities and 297 active face samples in Friends stores.

- [ ] **Step 1: Add importer traversal tests**

Test deterministic actor directory traversal, supported image filtering, reuse of the first returned `faceId` for later samples, and per-actor accepted/rejected counts.

- [ ] **Step 2: Implement the minimal importer**

POST the first accepted image for each actor to `/api/v1/faces/enroll` with `name=<actor>`, then pass its returned `faceId` for subsequent images. Stop with nonzero status when any expected actor has zero accepted images.

- [ ] **Step 3: Reset only Friends stores**

Record pre-reset counts, stop Friends API/worker, recreate only database `mergenvision_friends`, delete only Qdrant collection `friends_arcface_r50_v1`, and clear only MinIO buckets `mergenvision-friends-faces` and `mergenvision-friends-videos`. Restart Friends API so migrations and collection initialization run.

- [ ] **Step 4: Re-enroll with real-image holdout validation**

Hold out one deterministic image per actor and enroll all remaining dataset images against `http://localhost:8001`. Recognize the six unseen holdouts through `/api/v1/faces/recognize`; require the correct actor and cosine at or above 0.60 for each. Then enroll each holdout into its existing actor identity. Query Friends PostgreSQL and Qdrant and require six active known identities, zero active anonymous identities, 297 active samples, and 297 vectors.

### Task 5: Deterministic 100-Frame Acceptance Run

**Files:**
- Consume: `test_videos/Friends_100f.mp4`
- Produce: `test_videos/Friends_100f.annotated.mp4`
- Reuse: `backend/scripts/annotate_video.py`

**Interfaces:**
- Consumes: clean named gallery and every-frame sampling.
- Produces: annotated 100-frame H.264 video and API result JSON.

- [ ] **Step 1: Submit every frame**

POST `Friends_100f.mp4` to `/api/v1/videos/recognize` with `samplingMode=every_n_frames` and `everyNFrames=1`.

- [ ] **Step 2: Verify completed metadata**

Require status `completed`, `totalFrames=100`, `processedFrames=100`, no pipeline error, and nonempty detections.

- [ ] **Step 3: Render the annotation**

Run `uv run python scripts/annotate_video.py --input ../test_videos/Friends_100f.mp4 --output ../test_videos/Friends_100f.annotated.mp4 --job-id <job> --api-url http://localhost:8001`.

- [ ] **Step 4: Verify media and overlays**

Use `ffprobe` to require 1920x1080, 100 frames, approximately 4.17 seconds, and H.264. Verify each API detection has one bounding box, detector confidence, track confidence, and exactly five landmarks.

- [ ] **Step 5: Inspect representative frames**

Extract a contact sheet spanning frames 0, 20, 40, 60, 80, and 99. Confirm visible faces have correctly attached boxes/landmarks and cast labels. Do not approve based only on aggregate counts.

### Task 6: Root-Cause Gate for Remaining Wrong Labels

**Files:**
- Diagnose: `backend/pipeline/src/video_pipeline.cpp`
- Diagnose: `backend/app/services/video_identity_voting_service.py`
- Diagnose: `backend/app/services/video_tracking_service.py`
- Diagnose: Friends PostgreSQL/Qdrant/sample objects

**Interfaces:**
- Consumes: any visually incorrect track ID from Task 5.
- Produces: evidence identifying the failing layer before another code or threshold change.

- [ ] **Step 1: Trace an incorrect detection end-to-end**

For each wrong label, record frame, object box, five landmarks, tracker ID, embedding row, canonical track, nearest named sample IDs/scores, and final vote support.

- [ ] **Step 2: Inspect enrollment provenance**

Fetch the winning and expected gallery samples and verify folder label, source hash, detected crop, alignment landmarks, and embedding norm. Detect mislabeled folders, multi-face enrollment images, or corrupt sample/object associations.

- [ ] **Step 3: Classify and fix the actual layer**

Fix only the proven cause: detector-to-row association, alignment transform, tracker reconciliation, gallery contamination/mislabeling, or voting. Add a regression test reproducing the exact failure before implementation.

- [ ] **Step 4: Repeat clean 100-frame acceptance**

Repeat Tasks 4 and 5 until labels, boxes, five landmarks, detector scores, cosine scores, and processed frame count all pass. Do not change the 0.60 rule to hide an unresolved defect.
