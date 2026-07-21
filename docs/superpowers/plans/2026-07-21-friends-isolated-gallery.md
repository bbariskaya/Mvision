# Friends Isolated Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision isolated Friends stores, import only the six cast classes, process `Friends.mp4`, and render a verified Friends-only annotated video.

**Architecture:** A Compose override runs a dedicated API and video worker against a new PostgreSQL database, two new MinIO buckets, and a new Qdrant collection inside the existing infrastructure containers. Idempotent scripts provision stores and import labeled samples through the real API. The existing annotation tool renders only verified Friends-only results.

**Tech Stack:** Docker Compose, PostgreSQL 16, Alembic, MinIO, Qdrant, FastAPI, DeepStream, Python 3.12, pytest, FFmpeg.

## Global Constraints

- Never delete, reset, rename, or write to production stores.
- Friends PostgreSQL database: `mergenvision_friends`.
- Friends MinIO buckets: `mergenvision-friends-faces`, `mergenvision-friends-videos`.
- Friends Qdrant collection: `friends_arcface_r50_v1`.
- Friends API port: `8001`.
- Search only the Friends Qdrant collection.
- Do not commit or push changes.

---

### Task 1: Provision Isolated Logical Stores

**Files:**
- Create: `backend/scripts/provision_friends_stack.py`
- Create: `backend/scripts/test_provision_friends_stack.py`

**Interfaces:**
- Produces: idempotent database, migration, bucket, and collection provisioning with production-name guards.

- [ ] Write tests for exact store names, production-name rejection, and idempotent command construction.
- [ ] Run tests and verify they fail because the provisioner does not exist.
- [ ] Implement the provisioner using PostgreSQL administrative SQL, Alembic configuration, MinIO `bucket_exists`/`make_bucket`, and `QdrantAdapter.setup` under Friends settings.
- [ ] Run provisioning tests and `--dry-run` validation.
- [ ] Execute provisioning and verify all four logical stores exist without changing production counts.

### Task 2: Add Friends API and Video Worker Services

**Files:**
- Create: `docker-compose.friends.yml`
- Modify: `backend/.env.example`

**Interfaces:**
- Produces: `friends-api` on port 8001 and `friends-video-worker-0`, both configured exclusively for Friends stores.

- [ ] Add a Compose override that reuses built application images, the existing network, GPU socket volume, model artifacts, and Friends environment variables.
- [ ] Validate the merged Compose configuration with `docker compose config`.
- [ ] Start both Friends services and verify database, bucket, and collection environment values from container inspection.
- [ ] Verify `GET http://localhost:8001/health` succeeds.

### Task 3: Import the Friends Dataset Deterministically

**Files:**
- Create: `backend/scripts/import_friends_dataset.py`
- Create: `backend/scripts/test_import_friends_dataset.py`

**Interfaces:**
- Consumes: dataset root and Friends API URL.
- Produces: one identity per actor, accepted/rejected counts, and idempotent SHA-based sample imports.

- [ ] Write tests for class-to-actor mapping, JPEG filtering, stable traversal, rejection accounting, and duplicate SHA filtering.
- [ ] Run tests and verify RED.
- [ ] Implement the importer using HTTP enrollment plus Friends PostgreSQL lookup for existing actor identities and sample hashes.
- [ ] Run importer tests.
- [ ] Import `/home/user/Workspace/Mvision/friends_chars/Friends/Train` through port 8001.
- [ ] Verify exactly six active known identities and Friends-only active sample/Qdrant counts.

### Task 4: Process, Inspect, and Annotate Friends.mp4

**Files:**
- Reuse: `backend/scripts/annotate_video.py`
- Output: `test_videos/Friends.friends-only.annotated.mp4`

**Interfaces:**
- Consumes: Friends API job result and source video.
- Produces: final H.264/AAC annotated video with verified actor or `Unknown` labels.

- [ ] Record production store counts before the run.
- [ ] Submit `Friends.mp4` to port 8001 at 2 FPS and wait for completion.
- [ ] Inspect track labels, confidence, source tracklet support, and detections at representative timestamps.
- [ ] Reject incorrect known labels; retain `Unknown` for unresolved tracks.
- [ ] Render the Friends-only annotated output.
- [ ] Extract representative preview frames and visually inspect box/label placement.
- [ ] Verify output resolution, duration, codec, frame count, and audio with `ffprobe`.
- [ ] Verify production counts are unchanged, Friends Qdrant equals active Friends samples, tests pass, services are healthy, and `git diff --check` is clean.
