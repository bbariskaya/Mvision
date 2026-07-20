# Phase 1 — System Architecture

## Product Boundary
MergenVision Phase 1 is an API-only face recognition service. It accepts an encoded image and returns per-face `faceId`, `status`, optional name/metadata, bounding box, and confidence, plus a queryable `processId`. All persistent state lives in PostgreSQL/MinIO/Qdrant; GPU inference is added in Sprint 02.

## Three-Layer Architecture

```text
Presentation (Router + Controller + API Schemas)
└── Service (workflow + lifecycle + transaction + cross-store orchestration)
    └── Infrastructure (PostgreSQL repositories + MinIO adapter + Qdrant adapter + GPU adapter in Sprint 02)
```

- Presentation handles HTTP routing, request/response mapping, and sanitized error conversion. No business logic.
- Service owns identity lifecycle, cross-store staged persistence, and SQLAlchemy transaction boundaries.
- Infrastructure owns concrete storage adapters and models. Repositories never call `commit()`/`rollback()`.

## PostgreSQL / MinIO / Qdrant Ownership

- **PostgreSQL:** Business source-of-truth. Identity lifecycle, sample lifecycle, process records, immutable recognition snapshots, process events.
- **MinIO:** Canonical aligned face evidence binary objects. Object key contains only UUID/technical segments: `faces/{faceId}/{sampleId}/aligned`.
- **Qdrant:** Rebuildable 512-D cosine vector index. Point ID equals `sample_id`. Minimal payload allowlist only.

## Future Phase 2 Sharing
Phase 2 video pipeline will reuse the same global `faceId` gallery, the same Qdrant collection/model/preprocess version, and the same MinIO aligned evidence contract.

## Failure Boundaries
- No UnitOfWork, no ports, no distributed transaction, no microservice decomposition.
- Cross-store stages use explicit PostgreSQL lifecycle states so retries remain idempotent.
- Logging/reconciliation failures are isolated; primary process/result traceability is mandatory.
