# Phase 1 — Cross-Store Lifecycle

## Principle
PostgreSQL, MinIO and Qdrant do **not** share a transaction. The Service implements an explicit staged workflow bracketed by PostgreSQL lifecycle states.

## Happy Path

```mermaid
sequenceDiagram
    participant S as Service
    participant PG as PostgreSQL
    participant M as MinIO
    participant Q as Qdrant

    S->>PG: Reserve UUIDv7 faceId/sampleId
    S->>PG: Create identity + sample(pending)
    S->>M: Upload aligned bytes to faces/{faceId}/{sampleId}/aligned
    S->>PG: Update sample → blob_ready (+object_key, sha256)
    S->>Q: Upsert pointId=sampleId, 512-D normalized embedding
    S->>PG: Update sample → active/indexed
    S->>PG: Record result + process complete
```

## Retry and Idempotency
- Reserved UUIDv7 IDs are reused across retries.
- MinIO upload is idempotent; SHA-256 is rechecked.
- Qdrant upsert is idempotent by point ID.
- Repository methods never commit; Service owns transaction boundaries.

## Failure Branches

| Stage | Failure | Effect | Compensation / Event |
|-------|---------|--------|----------------------|
| Identity/sample insert | PG error | No mutation | `failed` process record + event |
| MinIO upload | Storage error | Sample remains `pending` | sanitized event, retry later |
| MinIO stat/checksum | SHA mismatch | Sample marked `failed` | sanitized event |
| Qdrant upsert | Vector error | Sample remains `blob_ready` | sanitized event, retry later |
| PG finalization | PG error | Qdrant may have point; sample not `active` | reconciliation detects mismatch |

## Reconciliation
`StorageReconciliationService` inspects PostgreSQL, MinIO, and Qdrant and reports:

- Sample `active` but object missing.
- Sample `active` but vector missing.
- Object exists without PostgreSQL sample.
- Vector exists without PostgreSQL sample.
- Payload/version mismatches.

Dry-run mode reports only; mutation mode repairs with explicit Service approval.

## No UnitOfWork / Distributed Transaction
No `UnitOfWork` class, no saga framework, no two-phase commit. Transaction boundaries are normal SQLAlchemy sessions managed by the Service; external stages are explicit and inspectable.
