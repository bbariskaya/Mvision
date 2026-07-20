# Project Requirements Backend API Design

## Scope

Complete the API in `requirements/ProjectRequirements.md`. UI work is explicitly deferred. Existing PostgreSQL, Qdrant, and MinIO data must remain intact.

## Architecture

Keep the existing presentation, service, and infrastructure layers. FastAPI owns HTTP contracts and sanitized errors. Services own process tracking, recognition, enrollment, identity lifecycle, and cross-store ordering. PostgreSQL remains the business source of truth, Qdrant remains the rebuildable embedding index, and MinIO stores face evidence. A persistent Unix-socket adapter sends encoded JPEG images to the native GPU workers.

## Recognition

`POST /api/v1/faces/recognize` accepts one multipart image, validates size and JPEG content, creates a UUIDv7 process record, and invokes one GPU worker. Every detected face is independently matched against active Qdrant samples. Known identities require `RECOGNITION_THRESHOLD`; anonymous identities require `ANONYMOUS_THRESHOLD`. An unmatched face creates a persistent anonymous identity and returns the immutable snapshot status `new_anonymous`. No-face is a successful response with an empty face list.

Every result stores an immutable PostgreSQL snapshot. New identities and useful observations receive a sample in PostgreSQL, MinIO, and Qdrant. Process events are best effort and never replace mandatory process/result persistence.

## Enrollment

`POST /api/v1/faces/enroll` accepts multipart `image`, `name`, optional JSON `metadata`, and optional `faceId`. The image must contain exactly one face. If `faceId` is supplied, the active identity is preserved and promoted or updated as known. Without `faceId`, an embedding match reuses the existing identity; otherwise a new known identity is created. The uploaded image adds a new sample. Anonymous-to-known promotion preserves the same global face ID.

## Identity And History

Implement get, patch, soft delete, face history, and process-detail endpoints under `/api/v1`. Delete deactivates identity samples and vectors while retaining relational history. Historical recognition snapshots are immutable.

## Contracts And Errors

Responses use camelCase and the requirement statuses `known`, `anonymous`, and `new_anonymous`. Errors use a stable envelope containing code, message, and process ID when one has already been allocated. Invalid, empty, oversized, corrupt, or unsupported images are distinguishable. Enrollment rejects zero or multiple faces.

## Deployment

Docker Compose starts PostgreSQL, Qdrant, MinIO, persistent GPU workers, and API without destructive initialization. Thresholds, storage endpoints, upload limits, worker sockets, and model versions are environment-configurable. Alembic upgrades are additive and do not remove loaded data.

## Verification

Use contract and service tests for every endpoint and lifecycle transition, adapter tests for the worker protocol and storage boundaries, then run the full backend test suite, Docker build, migration upgrade against existing data, health checks, and non-destructive API smoke tests.
