# Project Requirements Backend API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver every backend behavior in `requirements/ProjectRequirements.md` using the existing native GPU pipeline and persistent stores.

**Architecture:** Complete the existing FastAPI presentation/service/infrastructure layering. A persistent Unix-socket GPU client supplies detections and embeddings; services perform Qdrant matching and PostgreSQL/MinIO/Qdrant lifecycle operations while preserving immutable process history.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 16, Qdrant, MinIO, MessagePack Unix sockets, pytest, Docker Compose, native DeepStream workers.

## Global Constraints

- Never delete or reset existing PostgreSQL, Qdrant, or MinIO volumes/data.
- Keep `/api/v1` contracts camelCase and statuses exactly `known`, `anonymous`, `new_anonymous`.
- Every API operation allocates and returns or records a UUIDv7 process ID.
- Enrollment accepts multipart image, name, optional metadata JSON, and optional existing face ID.
- No commits or pushes unless explicitly requested.

---

### Task 1: GPU Result Contract And Worker Pool

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/infrastructure/gpu/contracts.py`
- Modify: `backend/app/infrastructure/gpu/protocol.py`
- Create: `backend/app/infrastructure/gpu/worker_pool.py`
- Test: `backend/tests/contract/test_worker_protocol.py`
- Create: `backend/tests/unit/test_worker_pool.py`

**Interfaces:**
- Produces `FaceDetection`, `ImageResult`, `decode_result(frame: bytes) -> ImageResult`.
- Produces `GpuWorkerPool.process(encoded_jpeg: bytes, request_id: str) -> ImageResult`.

- [ ] Add failing tests for result MessagePack decoding, framed socket reads, worker selection, closed sockets, and timeouts.
- [ ] Run `pytest backend/tests/contract/test_worker_protocol.py backend/tests/unit/test_worker_pool.py -q` and confirm failures are caused by missing result/client behavior.
- [ ] Add configurable worker socket paths/timeouts and implement strict result decoding matching the native protocol fields.
- [ ] Implement a thread-safe round-robin worker pool using one request per Unix socket connection and `asyncio.to_thread` for blocking I/O.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Image Validation And API Contracts

**Files:**
- Create: `backend/app/services/image_validation.py`
- Create: `backend/app/presentation/schemas/faces.py`
- Create: `backend/app/presentation/schemas/processes.py`
- Modify: `backend/app/services/exceptions.py`
- Create: `backend/tests/unit/test_image_validation.py`
- Create: `backend/tests/contract/test_error_contract.py`

**Interfaces:**
- Produces `validate_jpeg(data: bytes, max_bytes: int) -> None`.
- Produces response models `FaceResultResponse`, `RecognitionResponse`, `FaceIdentityResponse`, `FaceHistoryResponse`, and `ProcessResponse` with camelCase aliases.
- Service errors carry `status_code`, stable `code`, public `message`, and optional `process_id`.

- [ ] Write failing tests for empty, oversized, non-JPEG, truncated JPEG, standardized errors, and response aliases.
- [ ] Run focused tests and verify expected failures.
- [ ] Implement JPEG marker/decoder validation, schemas, and sanitized exception handlers.
- [ ] Re-run focused tests and confirm pass.

### Task 3: Recognition Workflow

**Files:**
- Create: `backend/app/services/recognition_service.py`
- Modify: `backend/app/services/face_sample_persistence_service.py`
- Modify: `backend/app/infrastructure/database/repositories/identity_repository.py`
- Modify: `backend/app/infrastructure/database/repositories/process_repository.py`
- Modify: `backend/app/infrastructure/database/repositories/result_repository.py`
- Create: `backend/tests/unit/test_recognition_service.py`
- Create: `backend/tests/integration/services/test_recognition_workflow.py`

**Interfaces:**
- Produces `RecognitionService.recognize(image: bytes) -> RecognitionOutcome`.
- Matching chooses an active sample whose identity passes the status-specific threshold; otherwise it creates a persistent anonymous identity and a `new_anonymous` snapshot.

- [ ] Write failing tests for no-face success, known, anonymous, new anonymous, multiple faces, threshold boundaries, process completion, and best-effort events.
- [ ] Run focused tests and verify failures.
- [ ] Implement process creation before GPU work, per-face Qdrant search and SQL identity resolution, new identity/sample persistence, immutable result snapshots, and process completion/failure.
- [ ] Ensure observation persistence uses idempotent UUIDs and never rewrites historical snapshots.
- [ ] Re-run focused tests and confirm pass.

### Task 4: Image Enrollment And Identity Lifecycle

**Files:**
- Create: `backend/app/services/enrollment_service.py`
- Create: `backend/app/services/identity_service.py`
- Modify: `backend/app/infrastructure/database/repositories/identity_repository.py`
- Modify: `backend/app/infrastructure/database/repositories/sample_repository.py`
- Create: `backend/tests/unit/test_enrollment_service.py`
- Create: `backend/tests/unit/test_identity_service.py`
- Create: `backend/tests/integration/services/test_identity_lifecycle.py`

**Interfaces:**
- Produces `EnrollmentService.enroll(image, name, metadata, face_id=None) -> EnrollmentOutcome`.
- Produces identity get/update/delete/history operations.

- [ ] Write failing tests for exact-one-face enrollment, new known identity, automatic anonymous promotion, explicit face-ID promotion, known identity sample append, invalid names, metadata, missing/inactive identities, and soft delete.
- [ ] Run focused tests and verify failures.
- [ ] Implement enrollment matching while preserving existing face IDs and adding each enrollment image as a sample.
- [ ] Implement patch and delete transactions; delete deactivates every sample and Qdrant point while retaining relational history.
- [ ] Re-run focused tests and confirm pass.

### Task 5: Face And Process HTTP Endpoints

**Files:**
- Create: `backend/app/presentation/routers/faces.py`
- Create: `backend/app/presentation/routers/processes.py`
- Create: `backend/app/presentation/dependencies.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/contract/test_faces_api.py`
- Create: `backend/tests/contract/test_processes_api.py`

**Interfaces:**
- Exposes all required routes under `/api/v1`.
- Multipart enroll fields are `image`, `name`, optional `metadata`, optional `faceId`.

- [ ] Write failing API contract tests for recognize, enroll, get, patch, delete, history, process detail, no-face, and error envelopes.
- [ ] Run focused tests and verify route-not-found/contract failures.
- [ ] Implement dependency construction, multipart parsing, router/controller mapping, HTTP statuses, and OpenAPI response models.
- [ ] Re-run focused tests and confirm pass.

### Task 6: Non-Destructive Docker Deployment

**Files:**
- Modify: `backend/Dockerfile`
- Modify: `docker-compose.sprint01.yml`
- Modify: `backend/.env.example`
- Create: `backend/tests/contract/test_deployment_contract.py`

**Interfaces:**
- Compose provides three GPU worker services, shared socket volume, API worker configuration, health checks, and existing named data volumes unchanged.

- [ ] Write a failing deployment contract test asserting worker services, GPU pinning, nofile limit, shared sockets, API dependencies, and environment configuration.
- [ ] Run the focused test and verify failure.
- [ ] Add worker services without changing or recreating persistent volume names; run Alembic upgrade automatically before API startup.
- [ ] Run the focused test and `docker compose -f docker-compose.sprint01.yml config`.

### Task 7: Full Verification Against Existing Data

**Files:**
- Modify only files required by failures found in this verification task.

- [ ] Run `pytest backend/tests -q` and fix all failures without weakening assertions.
- [ ] Run Ruff and mypy using the backend development environment.
- [ ] Build the API and native worker images.
- [ ] Record PostgreSQL, Qdrant, and MinIO counts before migration/startup.
- [ ] Run `alembic upgrade head`, start the stack without `down --volumes`, and confirm counts do not decrease.
- [ ] Exercise health, no-face recognition, known recognition, enrollment, identity get/update/history, process get, and soft delete using disposable test identities only.
- [ ] Confirm pre-existing sample/object/vector counts and IDs remain available.
