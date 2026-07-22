# Live Platform Hardening And SDK Design

**Status:** Draft for user review  
**Phase:** Live Analytics Platform Phase 7

## Goal

Turn the accepted live platform contracts into a secure, versioned, operable API
with tenant isolation, audit, secret rotation, retention/reconciliation,
generated clients, and real load/upgrade/recovery evidence.

## Authentication And Caller Identity

Support OIDC/JWT user/service identities and scoped service accounts. Tokens are
validated for issuer, audience, signature, expiry, and clock skew. Internal
worker/MediaMTX/connector traffic uses separate service identity and network
policy; it does not reuse caller credentials.

## Authorization

Initial RBAC capabilities:

```text
location:read|write
source:read|write|use
profile:read|publish
connector:read|write|use|rotate
session:read|start|reconfigure|stop
result:read
recording:read|download
delivery:read|replay
worker:read|drain
```

Every resource belongs to a caller/tenant scope. Connector use and source use
require explicit permission, not only knowledge of an ID. Admin operations are
separate from session caller operations.

## Tenant Isolation

- tenant/caller scope is explicit in every business table and unique key;
- repository queries require scope and reject missing scope;
- object keys use opaque technical IDs and tenant-owned prefixes without names;
- Qdrant payload includes non-PII tenant scope required for filtering;
- worker commands contain only the scoped resources for one generation;
- cross-tenant profile/connectors require explicit platform ownership;
- caches and pagination cursors are scope bound and signed.

## Audit

Immutable audit events cover:

- location/source/profile/connector create/update/delete;
- secret rotation and connector tests;
- session start/reconfigure/stop/cancel;
- profile/capability version used;
- recording access/download;
- delivery replay;
- worker drain and administrative placement actions.

Audit payloads contain actor, action, target technical ID, outcome, request ID,
timestamp, and safe changed-field names. They never contain source URI,
credentials, embeddings, full result payloads, or webhook responses.

## Secret Management

Source and connector secrets use encrypted-at-rest values or external secret
references with version IDs. Rotation creates a new secret version; active
generations retain their resolved version until controlled reconfigure unless
emergency revocation requires stop.

Policies include:

- no secret in argv/environment where avoidable;
- bounded in-memory plaintext lifetime;
- explicit zero/release for native reference vectors and secret buffers where
  practical;
- no secret serialization in specs, events, audit, traces, metrics, or errors;
- connector-test output returns only safe reachability/auth outcome codes.

## Webhook Network Security

Registration and delivery enforce HTTPS/origin policy, DNS/IP allowlists,
metadata/link-local/private-network restrictions, rebinding checks, disabled
redirects, response/body limits, and bounded timeouts. Admin can define explicit
private integration allowlists; arbitrary caller URLs remain forbidden.

## API Versioning

- public paths use `/v1`;
- request/response/event/session specs carry schema version where persisted or
  delivered;
- additive fields are backward compatible within v1;
- enum additions are declared through capabilities;
- breaking changes require a new API/schema version;
- deprecation and sunset dates are exposed in capabilities and headers;
- stored generations retain their original schema and resolved semantics;
- event consumers can select supported event schema versions per connector.

## OpenAPI And SDK

OpenAPI is the source for generated clients, but generated models do not replace
server-side domain validation.

Initial SDK deliverables:

- Python typed client;
- TypeScript typed client;
- session builder validated against capabilities;
- idempotency, cursor pagination, retry-safe GET helpers;
- event envelope/Webhook signature verification helpers;
- Kafka consumer event-ID deduplication example;
- examples for JSON-only, recording, annotated, Webhook, and Kafka sessions.

SDKs never accept raw secret values in repr/log output and distinguish write-only
fields.

## Retention And Deletion

Separate policies cover:

- source/session metadata;
- raw detections;
- appearance intervals;
- recording video and sample indexes;
- snapshots;
- result/outbox/delivery history;
- audit;
- telemetry.

Deletion is manifest driven and idempotent. Business metadata does not reference
deleted binary as available. Legal hold overrides normal retention. A face
identity deletion/anonymization workflow explicitly handles appearance history,
snapshots, vectors, delivered-event limitations, and immutable external copies.

## Reconciliation

Periodic jobs prove consistency among:

- PostgreSQL segment manifests and MinIO objects;
- PostgreSQL active samples and Qdrant points;
- open sessions/generations and worker leases/processes;
- MediaMTX paths and desired session outputs;
- outbox attempts and connector state;
- retention tombstones and binary deletion.

Repairs are safe, bounded, auditable, and never reset production volumes.

## Rate Limits And Quotas

Quotas are caller scoped for source/profile/connector/session counts, concurrent
resource classes, recording bytes, detection event rate, API request rate,
Webhook/Kafka backlog, and replay operations.

Limit errors are stable and expose no other tenant utilization. Admission limits
are enforced before expensive source/GPU work.

## Operational SLOs

Define and measure, by bounded class rather than dynamic IDs:

- session acceptance-to-active latency;
- source reconnect recovery;
- appearance persistence latency;
- recording finalization/evidence-link delay;
- result delivery latency and backlog;
- API availability/latency;
- worker lease health;
- data reconciliation lag.

SLO values are set only after baseline measurement. Alerts link to runbooks and
do not imply external notification channels that were not configured.

## Load And Soak

Required evidence includes:

- API/session/control load without GPU work;
- measured supported concurrent camera matrix;
- JSON-only versus recording versus annotated resource profiles;
- connector backlog and recovery load;
- 24-hour minimum live soak for the release candidate;
- recording retention and disk high-watermark behavior;
- repeated reconfigure/start/stop and worker restart;
- memory, file descriptor, thread, GPU memory, queue, and storage growth bounds.

Results state exact hardware, source resolution/cadence, models, profiles, and
output modes. No generalized camera capacity claim is inferred from one fixture.

## Upgrade And Disaster Recovery

- PostgreSQL migrations are additive and downgrade/forward tested where safe;
- profile/capability versions remain available for running generations;
- rolling API/worker version compatibility is contract tested;
- MediaMTX/config upgrades use pinned artifact and recording playback tests;
- PostgreSQL backup/restore, MinIO object recovery, and Qdrant derived-index
  rebuild are exercised;
- connector outbox resumes without losing accepted domain events;
- recovery reports evidence gaps rather than fabricating exact state.

## Supply Chain And Deployment

- production images and external services are pinned by digest/version;
- SBOM and license/source attribution are produced;
- model/config artifact hashes are recorded per generation;
- no runtime model/system CUDA/driver download or mutation;
- deployment separates public API, internal control plane, media, and storage
  networks;
- only explicitly required public media/API ports are exposed.

## Acceptance

- unauthorized cross-tenant reads/writes/use are denied in repository and API
  integration tests;
- all state changes emit safe audit records;
- source/connector secret rotation and emergency revoke work without leakage;
- SSRF, redirect, DNS rebinding, oversized response, and timeout fixtures fail
  safely;
- old/new API/event/schema clients pass declared compatibility matrix;
- generated Python/TypeScript clients execute canonical workflows;
- quota/rate-limit/admission behavior is deterministic;
- retention and legal-hold fixtures preserve/delete exact intended artifacts;
- reconciliation repairs controlled missing/orphan fixtures;
- load/24h soak show bounded resources and no result corruption;
- restore rebuilds Qdrant from business/vector source evidence and resumes
  pending outbox deliveries;
- security/privacy scans find no URI, credential, embedding, unauthorized PII,
  or raw exception in external or telemetry surfaces.
