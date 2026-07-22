# Multi-Camera Scheduler Design

**Status:** Draft for user review  
**Phase:** Live Analytics Platform Phase 6

## Goal

Run multiple independent camera sessions across available GPU workers with
durable placement, leases, quotas, admission control, and failure isolation.
Correctness uses one native pipeline process per camera initially.

## Prerequisites

- immutable SessionGeneration specs;
- generation-scoped MediaMTX ingress/output paths;
- ports and paths allocated internally rather than fixed globally;
- source, appearance, recording, and delivery data scoped by session/generation;
- reliable single-session lifecycle and teardown evidence.

## Non-Goals

- cross-camera body ReID or trajectory stitching;
- dynamic DeepStream source add/remove inside one shared pipeline;
- caller selection of arbitrary host process/GPU arguments;
- overcommit before measured resource models;
- high availability across data centers.

## Topology

```text
Live API / Session Controller
        -> Scheduler
             -> Worker Agent host-a
                  -> GPU 0 slot(s) -> native session process A
                  -> GPU 1 slot(s) -> native session process B
             -> Worker Agent host-b
                  -> GPU 0 slot(s) -> native session process C

MediaMTX paths and PostgreSQL state remain session/generation scoped.
```

One process per camera provides fault, memory, protocol, and teardown isolation.
After this topology passes correctness/load gates, measured compatible sessions
may later share a batched native runtime behind the same scheduler contract.

## Worker Capability Registry

Each worker agent heartbeats:

- worker/host instance ID;
- software/config capability version;
- GPU IDs and immutable hardware properties;
- supported model/profile/output capabilities;
- total and allocatable GPU memory;
- encoder session capacity when annotated output is supported;
- active reserved resource classes;
- health/draining state;
- heartbeat/lease timestamps.

Dynamic utilization is scheduling evidence, not a high-cardinality metric label.

Worker states:

```text
REGISTERING -> READY -> DRAINING -> OFFLINE
                    -> DEGRADED
```

## Resource Classes

Profiles declare a bounded estimate rather than arbitrary caller numbers:

```text
detection-standard
recognition-standard
recognition-recording
recognition-annotated
recognition-recording-annotated
```

Each version estimates GPU memory, decoder slots, encoder slots, CPU, disk
staging, and expected bandwidth. Estimates are calibrated from measured runtime
and include safety margins.

Normal callers request a class/profile. Admin profile versions can express GPU
architecture requirements or affinity. Exact placement remains scheduler-owned.

## Placement Algorithm

First version uses deterministic constrained best-fit:

1. Filter workers by READY state and capability compatibility.
2. Enforce caller/tenant/session quotas.
3. Enforce GPU memory, decoder, encoder, disk, and bandwidth reservations.
4. Prefer an already warm compatible worker when safe.
5. Choose the smallest remaining capacity that satisfies the request.
6. Persist reservation and assignment transactionally.
7. Issue a generation-fenced launch command.

Tie breaks are stable by worker and GPU ID. Random placement is not used in
acceptance tests.

## Durable Lease And Fencing

`live_worker_lease` records:

- worker ID;
- session ID/generation;
- lease token;
- allocated GPU/resource slot;
- issued, renewed, and expiry timestamps;
- launch/stop command revision;
- state and failure code.

Only the holder of the exact generation and lease token may mutate runtime state
or commit worker-originated results. Lease loss stops/cancels the native child
and prevents terminal mutation from a stale worker.

## Admission Control

Rejection occurs before source connection when any requirement cannot be
reserved:

- tenant/session quota;
- no compatible profile/model capability;
- GPU memory/decoder/encoder capacity;
- recording staging high-watermark;
- connector/result quota for requested detection volume;
- worker drain or maintenance policy.

The API returns `SESSION_CAPACITY_EXHAUSTED` with a safe bounded reason and may
leave the session `ACCEPTED` for queueing only when the caller explicitly allows
queueing. It never reports false `ACTIVE`.

## Queueing And Fairness

Accepted queued sessions have priority class, caller scope, accepted timestamp,
and optional deadline. Weighted fair scheduling prevents one caller from
starving others. Priority cannot bypass hard resource or security constraints.

Cancellation removes queued reservation intent idempotently. A start/cancel race
is resolved by generation command revision and lease fencing.

## Process And Media Isolation

- each session has a separate native child and bounded Python command/event
  queues;
- no fixed RTSP/UDP port is shared as session identity;
- MediaMTX ingress and annotated paths include generation-scoped opaque IDs;
- output publisher credentials are session scoped;
- recording staging/object keys are session scoped;
- a crash, queue saturation, output stall, or reconnect in one process cannot
  mutate another session;
- worker agent logs never include source URI, connector secret, or biometric
  vectors.

## Recovery

### Worker Agent Restart

The scheduler compares durable desired generations with live process inventory.
Unproven processes are stopped. Desired sessions receive fresh leases and launch
commands; generation does not change unless policy requires reconfiguration.

### Host/GPU Failure

Expired worker heartbeats fence all leases. Sessions become `DEGRADED` and may be
reassigned according to restart policy. Reassignment increments runtime attempt,
not SessionSpec generation. Timing continuity is not assumed; appearance
intervals close with a stable reason and new timing epochs begin.

### Draining

Drain rejects new placement. Existing sessions either finish naturally, migrate
through controlled stop/restart, or are force-stopped only after deadline policy.

## Global Identity Concurrency

Sessions share the global identity gallery through existing business services,
not native cross-camera IPC. Concurrent global anonymous creation requires
identity-level fencing and final gallery recheck. Cross-camera body/trajectory
association remains out of scope.

## Observability

Metrics include bounded worker state, available/reserved resource totals,
placement result enums, queue depth, lease expiry, process restart, and per-class
admission outcomes. Worker/session/camera/tenant/GPU serial IDs are not metric
labels.

Traces cover admission, placement, reservation, launch, lease renewal, stop,
reassignment, and recovery. They contain safe IDs only under telemetry privacy
policy.

## Acceptance

### Contract

- incompatible profile never reaches launch;
- deterministic input produces deterministic placement;
- quota/capacity errors are stable and non-secret;
- stale lease/generation cannot mutate state or results.

### Real Runtime

- run at least three simultaneous camera fixtures across available GPUs;
- verify independent FPS, identity, appearance, recording, and optional output;
- kill one native process and prove others continue;
- stall one viewer and prove other inference counters continue;
- disconnect one source and prove other states do not change;
- restart one worker agent and verify fencing/recovery;
- drain one worker and verify no new placement;
- saturate declared capacity and verify admission rejection without OOM;
- repeatedly start/stop concurrent sessions and measure stable resources;
- verify no path, port, file, event, or result crosses session generations.

### Performance

Measure per-camera and aggregate p50/p95/p99 latency, FPS, GPU memory, decoder and
encoder utilization. Do not claim a capacity number beyond the measured profile,
source resolution, model, and output combination.

## Later Optimization Gate

Dynamic batching/shared pipelines may begin only after isolated multi-camera
PASS. It must preserve the same SessionGeneration, lease, appearance, delivery,
and failure contracts and prove that one source cannot stall or contaminate
another batch member.
