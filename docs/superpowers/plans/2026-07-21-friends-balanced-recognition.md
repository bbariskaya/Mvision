# Friends Balanced Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reprocess every frame of `Friends.mp4` with corrected landmark alignment and balanced Friends-only recognition, then replace the invalid annotation.

**Architecture:** Keep the landmark coordinate fix in the native video pipeline. Tune only the isolated Friends service so strong single-track matches require `0.78`, moderate evidence remains available from `0.70`, and complete-link track reconciliation requires `0.95` similarity.

**Tech Stack:** C++17, CUDA, NVIDIA DeepStream 9, Python 3.12, FastAPI, PostgreSQL, Qdrant, Docker Compose, FFmpeg

## Global Constraints

- Process every source frame with `everyNFrames=1`.
- Keep weak or conflicting faces `Unknown`; do not force every detection into the six-person gallery.
- Modify only Friends-specific thresholds; production configuration remains unchanged.
- Do not use subagents, worktrees, commits, or pushes.
- Defer k-best sample selection and image quality gates.

---

### Task 1: Apply Friends-only Recognition Policy

**Files:**
- Modify: `docker-compose.friends.yml:14-20`

**Interfaces:**
- Consumes: `Settings` environment parsing in `backend/app/config.py`
- Produces: Friends worker configuration with recognition `0.78`, candidate floor `0.70`, and reconciliation `0.95`

- [ ] **Step 1: Update isolated environment values**

Set:

```yaml
RECOGNITION_THRESHOLD: "0.78"
ANONYMOUS_THRESHOLD: "0.78"
VIDEO_TRACK_RECONCILIATION_THRESHOLD: "0.95"
VIDEO_TRACK_VOTE_CANDIDATE_FLOOR: "0.70"
```

- [ ] **Step 2: Recreate Friends API and video worker**

Run:

```bash
docker compose -f docker-compose.friends.yml up -d --force-recreate friends-api friends-video-worker-0
```

Expected: both Friends services start with the new values; production services are untouched.

- [ ] **Step 3: Verify effective environment**

Run `docker inspect` for both Friends containers and confirm the four exact values above.

### Task 2: Remove Superseded Anonymous Samples

**Files:**
- No source changes

**Interfaces:**
- Consumes: `DELETE /api/v1/faces/{faceId}` and the corrected job result
- Produces: exactly six active known Friends identities before rerun

- [ ] **Step 1: Delete active anonymous identities created by superseded Friends jobs through the API**

Select `faceId` values whose result status is `new_anonymous` and call the face deletion endpoint for each.

- [ ] **Step 2: Verify database state**

Query `face_identity` in `mergenvision_friends` and confirm the only active rows are Chandler, Joey, Monica, Phoebe, Rachel, and Ross.

### Task 3: Rerun Every-frame Recognition

**Files:**
- No source changes

**Interfaces:**
- Consumes: `POST /api/v1/videos/recognize`, `/home/user/Workspace/Mvision/test_videos/Friends.mp4`
- Produces: a completed replacement job with `everyNFrames=1`

- [ ] **Step 1: Submit source video**

Post multipart fields `video`, `samplingMode=every_n_frames`, and `everyNFrames=1` to the Friends API.

- [ ] **Step 2: Wait for completion and fetch result JSON**

Expected: status `completed`, source `totalFrames=6665`, and sampling `everyNFrames=1`.

- [ ] **Step 3: Validate recognition distribution**

Report known and unknown detection counts by label, confidence distribution, canonical track count, and source tracker count. Reject the run if labels collapse to one identity or landmarks fall outside face boxes.

### Task 4: Render and Verify Replacement Annotation

**Files:**
- Replace: `test_videos/friends_annotated.mp4`

**Interfaces:**
- Consumes: corrected job result and `backend/scripts/annotate_video.py`
- Produces: final annotated MP4 at the required path

- [ ] **Step 1: Render from the corrected job**

Run:

```bash
uv run python scripts/annotate_video.py \
  --input /home/user/Workspace/Mvision/test_videos/Friends.mp4 \
  --output /home/user/Workspace/Mvision/test_videos/friends_annotated.mp4 \
  --job-id "$JOB_ID" \
  --api-url http://localhost:8001
```

`JOB_ID` is the identifier returned by Task 3, Step 1.

- [ ] **Step 2: Probe media**

Use `ffprobe` and require 1920x1080 H.264 video, 6,665 frames, approximately 278.036 seconds, and AAC audio.

- [ ] **Step 3: Extract representative frames**

Extract frames near 30, 120, and 240 seconds. Confirm boxes, five landmarks, cast/Unknown label, cosine, and detector confidence are visibly rendered and spatially aligned.
