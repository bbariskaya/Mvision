# Video Tracklet Identity Voting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve canonical video tracks from conservative agreement among their source tracklet embeddings instead of one diluted centroid.

**Architecture:** `VideoTrackingService` retains immutable source templates while reconciling raw tracks. A focused `VideoIdentityVotingService` queries unfiltered active gallery candidates per template, collapses samples by identity, and applies strong-single or consensus acceptance. `VideoResultService` keeps ownership of overlap blocking and persistence.

**Tech Stack:** Python 3.12, FastAPI dependency wiring, PostgreSQL/SQLAlchemy, Qdrant, pytest, Docker Compose.

## Global Constraints

- Preserve existing API and database schemas.
- No native protocol change and no database migration.
- `VIDEO_TRACK_VOTE_CANDIDATE_FLOOR=0.70`.
- `VIDEO_TRACK_VOTE_MIN_COUNT=2`.
- `VIDEO_TRACK_VOTE_MIN_MARGIN=0.05`.
- `VIDEO_TRACK_VOTE_MIN_SUPPORT_RATIO=0.60`.
- Existing known and anonymous thresholds remain strong-single thresholds.
- Do not commit or push changes.

---

### Task 1: Retain Source Tracklet Templates

**Files:**
- Modify: `backend/app/services/video_tracking_service.py`
- Test: `backend/tests/unit/test_video_tracking_service.py`

**Interfaces:**
- Consumes: `VideoTrackOutput` raw tracks.
- Produces: `SourceTrackTemplate(embedding, detection_count, best_confidence)` and `CanonicalVideoTrack.source_templates`.

- [ ] **Step 1: Write the failing retention test**

Add a test that merges two non-overlapping raw tracks and asserts both normalized embeddings, detection counts, and best confidences remain available in source order.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `docker exec mvision-api-1 pytest tests/unit/test_video_tracking_service.py::test_merged_track_retains_source_templates -q`

Expected: failure because `source_templates` does not exist.

- [ ] **Step 3: Implement immutable source templates**

Add:

```python
@dataclass(frozen=True)
class SourceTrackTemplate:
    embedding: tuple[float, ...]
    detection_count: int
    best_confidence: float
```

Store templates in `_WorkingTrack` and expose them as a tuple from `_finalize` without changing centroid behavior.

- [ ] **Step 4: Run the complete tracking test module**

Run: `docker exec mvision-api-1 pytest tests/unit/test_video_tracking_service.py -q`

Expected: all tracking tests pass.

### Task 2: Expose Candidate Search Without Premature Thresholding

**Files:**
- Modify: `backend/app/services/face_matcher.py`
- Create: `backend/tests/unit/test_face_matcher.py`

**Interfaces:**
- Produces: `FaceMatcher.candidates(embedding: list[float], *, minimum_score: float) -> list[FaceMatch]`.
- Preserves: `FaceMatcher.match(embedding)` behavior for image recognition.

- [ ] **Step 1: Write failing candidate tests**

Cover active identity resolution, inactive/missing identity filtering, minimum-score filtering, score clamping, and multiple samples for one identity remaining available to the voter.

- [ ] **Step 2: Verify RED**

Run: `docker exec mvision-api-1 pytest tests/unit/test_face_matcher.py -q`

Expected: failure because `candidates` does not exist.

- [ ] **Step 3: Extract candidate lookup from `match`**

Implement `candidates` using the existing Qdrant model/preprocess filters and repository lookup. Refactor `match` to iterate those candidates and apply lifecycle-specific thresholds exactly as before.

- [ ] **Step 4: Verify matcher tests**

Run: `docker exec mvision-api-1 pytest tests/unit/test_face_matcher.py -q`

Expected: all matcher tests pass.

### Task 3: Implement Conservative Identity Voting

**Files:**
- Create: `backend/app/services/video_identity_voting_service.py`
- Create: `backend/tests/unit/test_video_identity_voting_service.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Modify: `docker-compose.sprint01.yml`

**Interfaces:**
- Consumes: `CanonicalVideoTrack.source_templates`, `FaceMatcher.candidates`.
- Produces: `VideoIdentityVotingService.resolve(track: CanonicalVideoTrack) -> FaceMatch | None`.

- [ ] **Step 1: Write failing voter tests**

Use real `CanonicalVideoTrack` and deterministic fake candidate responses to cover:

```text
two agreeing moderate tracklets -> winner
one score at strong threshold -> winner
one moderate score -> no match
winner/runner margin below 0.05 -> no match
support ratio below 0.60 -> no match
two samples of one identity from one template -> one vote
one long template cannot replace two independent votes
```

- [ ] **Step 2: Verify RED**

Run: `docker exec mvision-api-1 pytest tests/unit/test_video_identity_voting_service.py -q`

Expected: import failure because the voter does not exist.

- [ ] **Step 3: Add typed settings**

Add bounded Pydantic settings for candidate floor, minimum count, minimum margin, and support ratio with the approved defaults. Mirror them in `.env.example` and all Python video-worker Compose environments.

- [ ] **Step 4: Implement voting**

For each source template:

1. Query candidates at the candidate floor.
2. Collapse samples to the best score per identity.
3. Let each template vote only for its highest-scoring identity.
4. Weight the vote with `1 + log1p(detection_count)`.
5. Accept a strong single at the identity lifecycle threshold, subject to runner-up margin.
6. Otherwise require minimum independent votes, support ratio, and margin.
7. Return the highest-scoring supporting sample ID and weighted-mean confidence.

- [ ] **Step 5: Verify voter tests**

Run: `docker exec mvision-api-1 pytest tests/unit/test_video_identity_voting_service.py -q`

Expected: all voter tests pass.

### Task 4: Integrate Voting and Validate Friends Video

**Files:**
- Modify: `backend/app/services/video_result_service.py`
- Modify: `backend/app/presentation/dependencies.py`
- Modify: `backend/tests/unit/test_video_result_service.py`

**Interfaces:**
- Replaces canonical-centroid `FaceMatcher.match` call with `VideoIdentityVotingService.resolve`.
- Preserves overlap blocking, snapshots, and anonymous persistence.

- [ ] **Step 1: Write failing integration-unit tests**

Assert that finalization calls the voter, accepts its winner, still blocks temporally overlapping duplicate identities, and creates one anonymous identity when the voter returns `None`.

- [ ] **Step 2: Verify RED**

Run: `docker exec mvision-api-1 pytest tests/unit/test_video_result_service.py -q`

Expected: failure because `VideoResultService` does not accept/use the voter.

- [ ] **Step 3: Wire the voter**

Construct one voter in FastAPI/video-worker dependency creation and inject it into `VideoResultService`. Remove the direct centroid match while retaining `FaceMatcher` behind the voter.

- [ ] **Step 4: Run focused Python verification**

Run: `docker exec mvision-api-1 pytest tests/unit/test_video_tracking_service.py tests/unit/test_face_matcher.py tests/unit/test_video_identity_voting_service.py tests/unit/test_video_result_service.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Rebuild and recreate video workers**

Build the current native artifact and Python application into `mvision-gpu-worker:local`, then recreate `video-worker-0`, `video-worker-1`, and `video-worker-2` with the voting environment.

- [ ] **Step 6: Run the real Friends acceptance job**

Submit `/home/user/Workspace/Mvision/test_videos/Friends.mp4` at 2 FPS, wait for completion, inspect each track's label/confidence/support, and verify representative frames against the source video.

- [ ] **Step 7: Render only verified labels**

Regenerate `/home/user/Workspace/Mvision/test_videos/Friends.annotated.mp4` only after representative-frame inspection confirms labels. Remove verified test-generated anonymous identities after the run.

- [ ] **Step 8: Run final verification**

Run focused/full isolated tests, native aggregation test, `git diff --check`, service health checks, persisted count checks, and annotated media probing. Report any unresolved recognition ambiguity instead of lowering safeguards silently.
