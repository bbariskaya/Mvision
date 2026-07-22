# Live Analytics Platform Roadmap Design

**Status:** Draft for user review  
**Date:** 2026-07-22

## Product Outcome

Mvision evolves from a fixed single-camera process into a configurable live
analytics platform. Callers can create sessions from durable or inline camera
sources, select typed analytics behavior, receive durable JSON results through
pull/Webhook/Kafka, optionally request an annotated stream URL, and later run
multiple isolated camera sessions.

The primary result remains person appearance history: who appeared at which
caller-provided camera/location, in which UTC intervals, and for how long.

## Locked Decisions

- Existing hardcoded camera/start behavior does not require backward
  compatibility.
- Runtime configuration uses typed fields and versioned profiles.
- Arbitrary GStreamer properties, config paths, and shell commands are forbidden.
- Normal session requests use registered `connectorRef` values.
- Durable and authorized inline camera sources are both supported.
- Reconfiguration creates a new immutable generation and controlled restart.
- Realtime appearance results are authoritative.
- MediaMTX recording is durable evidence/replay, not the primary result.
- Unknown persons can become global persistent anonymous identities after
  bounded evidence and duplicate checks.
- Pull API, Webhook, and Kafka are required delivery modes.
- Annotated output is optional and must not exist for JSON-only sessions.
- Multi-camera starts with isolated per-camera pipelines; batching is later.

## Phase Order

### Phase 1: Live Requirements And Contract Freeze

Deliverables:

- `requirements/live-streaming-requirements.md`;
- appearance, source-time, location, recording-evidence, session, output, and
  connector vocabulary;
- explicit differences between bounded uploaded video and unbounded live input.

Gate: all later specs use the same field semantics and failure vocabulary.

### Phase 2: Configurable Camera Session API

Deliverables:

- capability discovery;
- caller-owned locations;
- durable and inline sources;
- versioned pipeline profiles;
- registered connector references;
- immutable session generations;
- typed overrides and dependency validation;
- replacement of hardcoded global runtime behavior.

Gate: JSON-only and annotated session specs compile deterministically into
different internal pipeline graphs.

### Phase 3: MediaMTX Recording And Realtime Appearance

Deliverables:

- generation-scoped MediaMTX ingress paths;
- absolute timestamp propagation;
- 15-minute fMP4 recording;
- MinIO segment/index storage and PostgreSQL manifests;
- known/global-anonymous realtime appearance intervals;
- exact sample evidence linkage;
- fast and real-duration E2E harnesses.

Gate: deterministic fixture appearance results and zero-frame evidence match.

### Phase 4: Durable JSON Result Delivery

Deliverables:

- canonical event envelopes;
- PostgreSQL outbox;
- pull result APIs;
- Webhook and Kafka adapters;
- retry, replay, ordering, and dead-letter state.

Gate: connector outages do not stop analytics and all accepted events remain
recoverable.

### Phase 5: Optional Annotated Media Output

Deliverables:

- typed OSD configuration;
- conditional encoder/media graph;
- generation-scoped MediaMTX annotated paths;
- RTSP first, with HLS/WebRTC exposed only through declared capabilities;
- ready-state URL publication and viewer isolation.

Gate: JSON-only sessions instantiate no output branch; annotated sessions stream
without blocking inference.

### Phase 6: Multi-Camera Scheduler

Deliverables:

- worker capability and heartbeat registry;
- GPU/resource leases;
- placement, quotas, and admission control;
- per-session process isolation and recovery;
- camera-scoped ports/paths removed in favor of allocated resources.

Gate: concurrent cameras remain fenced and one failure cannot corrupt another.

### Phase 7: Platform Hardening And SDK

Deliverables:

- authentication, RBAC, tenant isolation, and audit;
- connector secret rotation and SSRF policy;
- retention/reconciliation controls;
- version compatibility and deprecation policy;
- generated clients/SDK;
- load, soak, upgrade, and disaster-recovery evidence.

Gate: published API version has reproducible security, compatibility, and
operational acceptance evidence.

## Cross-Phase Architecture

```text
Caller
  -> Live API / Session Controller
       -> Source + Location + Profile + Connector registries
       -> Session compiler / immutable generation
       -> Scheduler / worker lease
       -> MediaMTX path controller
       -> Live GPU worker
            -> realtime identity + appearance
            -> optional annotated stream
       -> Recording ingestion
            -> MinIO video/index
            -> PostgreSQL manifest/evidence
       -> PostgreSQL results + outbox
            -> Pull API
            -> Webhook adapter
            -> Kafka adapter
```

## Shared Invariants

- PostgreSQL is the business source of truth.
- MinIO owns binary recordings, snapshots, and immutable sample indexes.
- Qdrant is a derived global identity vector index.
- C++/GPU owns frame-rate-sensitive processing; no blocking external I/O occurs
  in probes.
- Requested specs and resolved specs are stored without secrets.
- Every result is attributable to one session generation and spec hash.
- External connector delivery is never the persistence source of truth.
- Optional outputs do not alter recognition correctness.
- No phase claims production readiness from mocks or short fixtures alone.

## Deferred Work

- Cross-camera body ReID and trajectory stitching;
- arbitrary user-supplied plugins or pipeline graphs;
- caller-supplied executable code;
- exact-once semantics across arbitrary external systems;
- automatic physical-location inference from images;
- dynamic DeepStream batching before isolated multi-camera correctness passes.

## Documentation Set

- `requirements/live-streaming-requirements.md`
- `docs/superpowers/specs/2026-07-22-configurable-camera-session-api-design.md`
- `docs/superpowers/specs/2026-07-22-mediamtx-recording-realtime-appearance-design.md`
- `docs/superpowers/specs/2026-07-22-durable-live-result-delivery-design.md`
- `docs/superpowers/specs/2026-07-22-optional-annotated-stream-design.md`
- `docs/superpowers/specs/2026-07-22-multi-camera-scheduler-design.md`
- `docs/superpowers/specs/2026-07-22-live-platform-hardening-sdk-design.md`
