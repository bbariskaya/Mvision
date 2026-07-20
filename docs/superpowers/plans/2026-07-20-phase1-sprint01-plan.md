# Phase 1 — Sprint 01 Plan: Data Foundation

**Goal:** Deliver the canonical contract, five-table PostgreSQL schema, MinIO/Qdrant adapter foundations, cross-store persistence service, and real integration tests for Phase 1. No GPU inference, no model download, no product recognition/enroll routes.

**Branch:** `phase1-data-layer`

---

## Non-Goals (deferred)

- GPU decode, YOLOv8-Face TensorRT, ArcFace TensorRT, CUDA/NPP alignment.
- `/faces/recognize`, `/faces/enroll` functional endpoints that perform real inference.
- Model weight download/export (R50/R100).
- DeepStream/CUDA production code.
- OpenCV/FFmpeg inference path.
- UnitOfWork / ports / hexagonal / DDD aggregate / CQRS / generic base repository.

---

## Core Decisions

1. **Architecture:** Three-layer backend only — `presentation` (router/controller/schemas) → `service` (workflow + transaction boundary) → `infrastructure` (repositories + adapters).
2. **UUIDv7:** Use `fastuuid7` PyPI package (RFC 9562 compliant); generate deterministic IDs outside DB transactions for idempotent retries.
3. **Five canonical tables:** `face_identity`, `face_sample`, `process_record`, `recognition_result`, `process_event`.
4. **Storage contract:** MinIO key `faces/{faceId}/{sampleId}/aligned`; only aligned face evidence bytes, no original image, no PII in key.
5. **Vector contract:** Qdrant collection `face_samples_arcface_r50_webface_v1`, dimension 512, cosine, pointId == `sample_id`, payload allowlist only: sample_id, face_id, active, embedding_model_version, preprocess_version.
6. **Cross-store lifecycle:** PG reserve → PG pending sample → MinIO upload + SHA-256 → PG blob_ready → Qdrant upsert → PG active/indexed → PG result/event (service owns boundary, no distributed transaction).
7. **Repositories:** Domain-specific concrete repositories receive `AsyncSession`; no commit/rollback inside repositories; no generic base.

---

## Milestones & Deliverables

### M1 — Canonical Contract & Docs
- Finalize API request/response Pydantic schemas for Phase 1 endpoints.
- Write `docs/superpowers/plans/2026-07-20-phase1-sprint01-plan.md` (this file) and update `PHASE1_SPRINT1.md`.
- Resolve conflicts with old plan `phase1-gpu-hot-path.md` (tables, UUIDv7, Qdrant pointId, payload, soft-delete).

### M2 — PostgreSQL Schema & Migrations
- Create SQLAlchemy 2.0 async models under `backend/src/db/models.py`.
- Create `backend/src/db/base.py`, `backend/src/db/ids.py`, `backend/src/db/session.py`.
- Set up Alembic async under `backend/alembic/` and produce single initial migration.
- Remove stale empty `backend/db/alembic/` and old DB skeleton if incomplete.

### M3 — Repositories
- Implement `FaceIdentityRepository`, `FaceSampleRepository`, `ProcessRecordRepository`, `RecognitionResultRepository`, `ProcessEventRepository` under `backend/src/infrastructure/persistence/`.
- Each method takes `AsyncSession`; no commits.

### M4 — MinIO Adapter
- Implement `backend/src/infrastructure/storage/minio_adapter.py`.
- Primitives: `ensure_bucket`, `upload_aligned_sample`, `stat_aligned_sample`, `get_aligned_sample`, `delete_aligned_sample`.
- SHA-256 in metadata; media-type allowlist; size limit; private bucket; async via `asyncio.to_thread`.

### M5 — Qdrant Adapter
- Implement `backend/src/infrastructure/vector/qdrant_adapter.py`.
- Primitives: `setup`, `upsert`, `activate`, `deactivate`, `delete`, `search`, `get`, `exists`.
- Validate 512-D finite L2-normalized vectors; strict payload allowlist; async `AsyncQdrantClient`.

### M6 — Cross-Store Persistence Service
- Implement `backend/src/services/sample_persistence_service.py`.
- Orchestrate lifecycle sequence: reserve → pending → MinIO → blob_ready → Qdrant → active.
- Record `process_event` sanitized details on partial failure.
- Implement `backend/src/services/reconciliation_service.py` for orphan cleanup.

### M7 — Configuration & Composition
- `backend/src/config.py` via Pydantic Settings for DATABASE_URL, MINIO_*, QDRANT_*, model/preprocess versions.
- `docker-compose.sprint01.yml` with `postgres`, `minio`, `qdrant`, `api` skeleton only.
- `Makefile` targets: `infra-up`, `infra-down`, `db-migrate`, `test-integration`.

### M8 — Real Integration Tests
- PostgreSQL repository tests with `pytest-asyncio` and real DB.
- MinIO adapter tests against real MinIO container.
- Qdrant adapter tests with synthetic 512-D normalized vectors against real Qdrant.
- Cross-store persistence happy path and partial failure tests.

### M9 — Skeleton API
- FastAPI app skeleton with lifespan wiring.
- Health endpoint.
- Not-yet-implemented route stubs returning 501 for Phase 1 endpoints (optional, for OpenAPI scaffolding only).

---

## File Tree Target

```
backend/
  pyproject.toml / requirements.txt
  alembic/
    env.py
    script.py.mako
    versions/<hash>_phase1_canonical_schema.py
  src/
    __init__.py
    main.py
    config.py
    db/
      base.py
      ids.py
      models.py
      session.py
    infrastructure/
      persistence/
        __init__.py
        identity_repository.py
        sample_repository.py
        process_repository.py
        result_repository.py
        event_repository.py
      storage/
        __init__.py
        minio_adapter.py
        exceptions.py
      vector/
        __init__.py
        qdrant_adapter.py
        exceptions.py
    services/
      __init__.py
      sample_persistence_service.py
      reconciliation_service.py
      exceptions.py
    presentation/
      __init__.py
      router/
        __init__.py
        health.py
      schemas/
        __init__.py
        common.py
  tests/
    integration/
      conftest.py
      persistence/
        test_identity_repository.py
        test_sample_repository.py
        test_process_repository.py
      storage/
        test_minio_adapter.py
      vector/
        test_qdrant_adapter.py
      services/
        test_sample_persistence.py
docker-compose.sprint01.yml
Makefile
.env.example
PHASE1_SPRINT1.md
docs/superpowers/plans/2026-07-20-phase1-sprint01-plan.md
```

---

## Schema Summary (PostgreSQL)

`face_identity` — `face_id` PK, `status` {anonymous,known}, `name`, `metadata` JSONB, `is_active`, `created_at`, `updated_at`, `deleted_at`, `version`.

`face_sample` — `sample_id` PK, `face_id` FK, `lifecycle_state` {pending,blob_ready,active,indexing_failed,inactive,orphaned}, `object_key`, `media_type`, `sha256`, `model_version`, `preprocess_version`, `is_active`, timestamps, deleted_at, version.

`process_record` — `process_id` PK, `process_type` {recognize,enroll,update,delete}, `status`, `face_count`, `created_at`, `completed_at`, `details` JSONB, `version`.

`recognition_result` — `result_id` PK, `process_id`, `face_id`, `status_snapshot` {anonymous,known,new_anonymous}, `name_snapshot`, `metadata_snapshot`, `bounding_box`, `confidence`, `sequence_index`, `created_at`.

`process_event` — `event_id` PK, `process_id`, `event_type`, `sanitized_details` JSONB, `created_at`.

---

## Cross-Store Happy Path

1. Service generates `process_id`, `face_id`, `sample_id` (UUIDv7).
2. Creates `face_identity` (anonymous if new) and `face_sample` (pending).
3. Uploads aligned bytes to MinIO at `faces/{face_id}/{sample_id}/aligned.jpg`, gets SHA-256.
4. Updates `face_sample` → `blob_ready` with object_key, media_type, sha256.
5. Upserts 512-D normalized embedding to Qdrant with pointId = `sample_id` and allowlist payload.
6. Updates `face_sample` → `active`/`indexed` and `is_active=true`.
7. Records immutable `recognition_result` and final `process_event`.

All steps except external adapter calls stay inside a single SQLAlchemy transaction boundary where feasible; external calls are bracketed by PG state transitions so retries remain idempotent.

---

## Acceptance Criteria

- `alembic upgrade head` runs successfully against PostgreSQL.
- All five repository methods have integration tests passing against real PostgreSQL.
- MinIO adapter integration tests pass: bucket idempotency, upload/stat/get/delete, SHA-256 roundtrip, unsupported media rejection, size limit, no PII in key.
- Qdrant adapter integration tests pass: collection idempotent setup, valid/invalid vector upsert, search with active/version filters, deactivate/delete.
- Cross-store persistence service test passes for happy path and one partial-failure scenario (e.g. Qdrant upsert fails, sample reconciled).
- `docker-compose.sprint01.yml` brings up postgres + minio + qdrant + api skeleton; `api` health endpoint responds.
- No model weights downloaded, no GPU code, no OpenCV/FFmpeg production path, no UnitOfWork/ports/DDD/CQRS introduced.

---

## Open Questions / Blockers

1. **R50 model selected:** `models/arcface_r50_dynamic.onnx` is the active model; Qdrant collection and model_version tags reflect ArcFace R50 WebFace.
2. **`fastuuid7` approval:** Confirm using `fastuuid7` package instead of `uuid7`.
3. **Local test credentials:** Confirm default Docker Compose credentials/ports (postgres 5432, minio 9000/9001, qdrant 6333).
4. **`AGENTS.MD` ownership:** Confirm uncommitted diff is user-owned and should not be reverted.

---

## Notes on Old Plan Conflicts

`docs/superpowers/plans/2026-07-20-phase1-gpu-hot-path.md` predates the canonical model. Conflicts include:
- Tables (`face_records`, `process_logs`, `face_appearances`) vs canonical five tables.
- UUIDv4 vs UUIDv7.
- MinIO bucket `images` / original image storage vs aligned evidence bucket.
- Qdrant pointId = `face_id` vs `sample_id`.
- Qdrant payload containing `name` vs allowlist-only.
- Hard delete vs soft lifecycle.

Sprint 01 follows AGENTS.MD canonical model. Old plan remains as historical reference for overall GPU direction only.
