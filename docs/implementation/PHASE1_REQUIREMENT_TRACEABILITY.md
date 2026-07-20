# Phase 1 — Requirement Traceability Matrix

Source document: `requirements/ProjectRequirements.md`.

| # | Requirement Clause | Sprint | Planned Source / Test | Status |
|---|---|---|---|---|
| 1 | Image input acceptance, validation, no-face success, corrupt/empty error | 03 | `backend/app/presentation/routers/face_router.py`, `controllers/recognition_controller.py`, `schemas/recognition.py`; integration tests for valid/no-face/corrupt uploads | PLANNED_SPRINT_03 |
| 2 | Detect all faces; return bounding boxes; multi-face independent processing | 02 | Native GPU pipeline: PGIE YOLOv8-Face parser + SGIE ArcFace R50; detection tests | PLANNED_SPRINT_02 |
| 3 | Persistent faceId per face; similarity threshold; statuses `known`/`anonymous`/`new_anonymous`; name/metadata only in `known`; mixed results | 03 | `backend/app/services/recognition_service.py`, `services/matcher.py`, `services/identity_lifecycle_service.py`; lifecycle unit + integration tests | PLANNED_SPRINT_03 |
| 4 | Automatic `new_anonymous` creation; persist anonymous faces; enroll anonymous → `known` preserving faceId | 03 | `backend/app/services/enrollment_service.py`, `services/identity_lifecycle_service.py`; enrollment tests | PLANNED_SPRINT_03 |
| 5 | Database / enrollment management; query/update/delete; multiple samples per identity | 01 | Canonical five-table schema (`face_identity`, `face_sample`, `process_record`, `recognition_result`, `process_event`), repositories; real PostgreSQL integration tests | SPRINT_01_PASS |
| 6 | Unique `processId` per request; returned in response; later queryable | 01 | `process_record` table + `ProcessRecordRepository`; UUIDv7 generation; query by processId tested | SPRINT_01_PASS |
| 7 | Process logging with timestamp, task type, face count, faceIds/statuses; persistent and non-blocking | 01 | `process_event` table + `ProcessEventRepository`; cross-store service emits sanitized events; real PostgreSQL integration tests | SPRINT_01_PASS |
| 8 | Face history by faceId; process detail by processId | 03 | `GET /faces/{faceId}/history`, `GET /processes/{processId}` routes + services; history query tests | PLANNED_SPRINT_03 |
| 9 | API-only; input/output contracts; structured consistent responses; standardized errors | 01 | `architecture/04-phase1-api-contract.md`; Pydantic schemas; error schema in `backend/app/services/exceptions.py` | SPRINT_01_PASS (docs + schemas) |
| 10 | Endpoints: `POST /faces/recognize`, `POST /faces/enroll`, `GET /faces/{faceId}`, `PATCH /faces/{faceId}`, `DELETE /faces/{faceId}`, `GET /faces/{faceId}/history`, `GET /processes/{processId}` | 03 | `backend/app/presentation/routers/face_router.py`, `process_router.py` with controllers/schemas; endpoint integration tests | PLANNED_SPRINT_03 |
| 11 | Response content: processId, faceCount, per-face faceId/status/name/metadata/boundingBox/confidence | 03 | `backend/app/presentation/schemas/recognition.py`, `enrollment.py`, `process.py`; schema validation tests | PLANNED_SPRINT_03 |
| 12 | Docker deployment; Dockerfile; env-driven config; persistent data; docker-compose for multi-service | 04 | `docker-compose.sprint01.yml` (deps only in Sprint 01), full `docker-compose.yml`, `backend/Dockerfile`; build + health smoke tests | SPRINT_01_PARTIAL (infra deps); PLANNED_SPRINT_04 |

Additional binding constraints from `AGENTS.MD`:

- Three-layer architecture only: Presentation → Service → Infrastructure. Enforced from Sprint 01 scaffolding.
- Five canonical PostgreSQL tables. Active Sprint 01.
- MinIO aligned evidence storage; no PII in object keys. Active Sprint 01.
- Qdrant pointId == `sample_id`; payload allowlist. Active Sprint 01.
- Native GPU hot path deferred to Sprint 02.
