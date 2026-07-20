# Sprint 01 — Data Foundation

## Objective
Deliver canonical product contract, three-layer backend skeleton, PostgreSQL migration/repositories, MinIO/Qdrant adapters, cross-store persistence/reconciliation, and real dependency integration tests. No GPU inference, no model download, no product recognition/enroll routes.

## Deliverables
- `docs/implementation/CURRENT_SPRINT.md` (this file)
- `docs/implementation/PHASE1_REQUIREMENT_TRACEABILITY.md`
- `docs/implementation/REFERENCE_DECISION_LOG.md`
- `docs/implementation/RUNTIME_INVENTORY.md`
- `architecture/01-phase1-system-architecture.md`
- `architecture/02-phase1-identity-process-lifecycle.md`
- `architecture/03-phase1-postgresql-erd.md`
- `architecture/04-phase1-api-contract.md`
- `architecture/05-phase1-native-gpu-contract.md`
- `architecture/06-phase1-cross-store-lifecycle.md`
- `backend/` three-layer source tree
  - `app/main.py`, `app/config.py`, health router, structured errors
  - `app/infrastructure/database/models.py`
  - `app/infrastructure/database/repositories/*`
  - `app/infrastructure/object_storage/minio_adapter.py`
  - `app/infrastructure/vector_store/qdrant_adapter.py`
  - `app/services/face_sample_persistence_service.py`
  - `app/services/storage_reconciliation_service.py`
  - `app/services/exceptions.py`
  - `alembic/` initial migration
  - `tests/integration/` real dependency tests
- `docker-compose.sprint01.yml`
- `Makefile`

## 20-Step Checklist

- [x] Step 1 — Preflight and safety snapshot
- [x] Step 2 — Requirement traceability matrix
- [x] Step 3 — Reference evidence matrix
- [x] Step 4 — Runtime and artifact inventory
- [x] Step 5 — Establish Sprint 01 ledger (this file)
- [x] Step 6 — Freeze high-level architecture
- [x] Step 7 — Freeze identity and process semantics
- [x] Step 8 — Freeze ERD
- [x] Step 9 — Freeze API contract (no implementation)
- [x] Step 10 — Freeze GPU boundary and model candidate decision
- [x] Step 11 — Freeze cross-store lifecycle
- [x] Step 12 — Scaffold minimal backend
- [x] Step 13 — Configuration and secret validation (`backend/app/config.py`, `.env.example`)
- [x] Step 14 — SQLAlchemy models and UUIDv7
- [x] Step 15 — Alembic migration validated on real PostgreSQL
- [x] Step 16 — Concrete repositories + real PG integration tests
- [x] Step 17 — MinIO adapter + integration tests
- [x] Step 18 — Qdrant adapter + integration tests
- [x] Step 19 — Persistence and reconciliation services + tests
- [x] Step 20 — Full Sprint 01 acceptance and hard stop

## Acceptance Commands

```bash
docker compose -f docker-compose.sprint01.yml up -d postgres minio qdrant
docker compose -f docker-compose.sprint01.yml run --rm api alembic upgrade head
docker compose -f docker-compose.sprint01.yml run --rm pytest tests/integration -v
make phase1-s1-static
make phase1-s1-postgres
make phase1-s1-storage
make phase1-s1-acceptance
```

## Non-Goals
- GPU decode, YOLOv8-Face TensorRT, ArcFace TensorRT
- `/faces/recognize`, `/faces/enroll` functional inference endpoints
- Model weight download/export
- DeepStream/CUDA production code
- OpenCV/FFmpeg inference path
- UnitOfWork / ports / hexagonal / DDD aggregate / CQRS / generic base repository
- Video/live/UI/bulk/import features
- Git commit/push

## Hard Stops
- Active root is not `/home/user/Workspace/Mvision`.
- `ProjectRequirements.md` is missing or differs materially.
- More than five tables required.
- A `person` model appears necessary.
- UnitOfWork/port architecture appears necessary.
- A model/weight/download/system package is required in Sprint 01.
- Live data migration/destructive repair is required.
- Existing user changes overlap target files and cannot be preserved.
- MinIO/Qdrant/PG credentials are unavailable for real tests.

## Evidence Classification
- `SOURCE_VERIFIED` — Source/migration/test directly observed.
- `RUNTIME_VERIFIED` — Command executed against real dependency container.
- `USER_REPORTED_NOT_REPRODUCED` — Claim without local evidence.
- `NOT_PROVEN` — Not yet validated.

## Sprint 01 Results

| Gate | Command | Result |
|------|---------|--------|
| Static | `make phase1-s1-static` | PASS |
| PostgreSQL | `make phase1-s1-postgres` | PASS |
| Storage | `make phase1-s1-storage` | PASS |
| Acceptance | `make phase1-s1-acceptance` | PASS |
| Integration tests | `pytest tests/integration` | 37 passed |
| Migration | `alembic current` | `58ecca5e38a3 (head)` |
| Git diff check | `git diff --check` | clean |

Final status: **SPRINT01_FOUNDATION_COMPLETE_STOPPED_BEFORE_SPRINT02**
