# Deferred Platform Hardening And SDK Notes

**Status:** Deferred, not a current roadmap delivery
**Revised:** 2026-07-23

## Current Baseline

The approved deployment uses one configured API key, registered connector
secrets, encrypted pull-source URLs, internal-only MediaMTX Control API access,
and no viewer authentication. This is the required baseline for the current
four-delivery roadmap.

## Activation Triggers

Add broader platform hardening only when at least one concrete requirement
exists for:

- multiple independent customer/tenant security boundaries;
- user/service-account authorization beyond one deployment API key;
- public Internet exposure requiring OIDC/JWT and RBAC;
- formal audit, legal hold, or deletion workflows;
- customer-facing generated SDKs and version deprecation policy;
- crash-safe Webhook replay, dead-letter management, or delivery audit;
- multi-host scheduling and measured heterogeneous resource placement;
- formal upgrade, backup/restore, or disaster-recovery SLOs.

## Preserved Design Seams

The current design keeps future work possible through:

- `/api/v1` and versioned JSON envelopes;
- immutable session generations and profile versions;
- caller-safe technical IDs;
- registered source/connector secrets;
- stable event IDs;
- MediaMTX desired-state reconciliation;
- worker lease fencing;
- OpenAPI request/response models;
- PostgreSQL business state, MinIO binary storage, and Qdrant as a derived index.

## Deferred Candidates

- OIDC/JWT service identities and RBAC;
- tenant-scoped repositories, storage, vectors, quotas, and audit;
- connector SSRF policy suitable for untrusted public callers;
- secret rotation/versioning and external secret managers;
- PostgreSQL outbox, replay, DLQ, and delivery inspection;
- generated Python/TypeScript SDKs;
- retention/legal-hold workflows;
- 24-hour soak, rolling-upgrade, backup/restore, and disaster-recovery gates;
- SBOM, signed images, and formal supply-chain reporting.

These candidates must not be presented as current prerequisites or implemented
speculatively.
