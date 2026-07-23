# Isolated Multi-Camera Design

**Status:** Approved direction
**Delivery:** 4 - Isolated Multi-Camera
**Revised:** 2026-07-23

## Goal

Run several live sessions concurrently without introducing a general GPU
scheduler or a shared dynamic DeepStream pipeline. The initial design uses a
fixed worker pool, existing PostgreSQL claim/lease fencing, and one native
process per active session.

## Prerequisites

- immutable session generations;
- generation-scoped MediaMTX ingress and annotated paths;
- no fixed per-camera public RTSP/UDP port;
- frame, appearance, recording, connector, and runtime state scoped by session
  and generation;
- deterministic single-session teardown and recovery;
- declared deployment concurrency limit.

## Non-Goals

- dynamic source add/remove inside one shared DeepStream graph;
- arbitrary GPU/resource placement requested by callers;
- heterogeneous multi-host scheduling;
- cross-camera body ReID, trajectories, or topology;
- overcommit based on optimistic GPU utilization;
- automatic capacity prediction across unknown models and resolutions.

## Topology

```text
Live API / Session Controller
  -> PostgreSQL desired generations
       -> fixed live worker pool
            -> worker slot 1 -> native process/session A
            -> worker slot 2 -> native process/session B
            -> worker slot 3 -> native process/session C

Mvision MediaMTX
  -> ingress A/B/C
  -> optional annotated A/B/C

PostgreSQL/Qdrant/MinIO
  -> generation-scoped business and binary data
```

Each worker slot processes one claimed generation at a time. Deployment scale
defines available slots. A shared GPU may back several measured slots, but the
configured limit is fixed from acceptance evidence rather than inferred live.

## Existing Claim And Lease Reuse

`LiveRunRepository.claim()` already provides the core ownership boundary. The
multi-camera delivery extends it from one globally permitted run to several
independent claims.

Each active claim contains:

- session ID and generation;
- run ID;
- worker ID;
- lease token and expiry;
- runtime attempt;
- desired and runtime state.

Only the worker holding the exact lease token may update runtime state or commit
worker-originated results. Lease loss stops the native child and rejects late
events.

## Admission

The API checks capacity before provisioning media or starting GPU work.

Initial admission inputs:

- configured maximum concurrent sessions;
- active and starting generation count;
- available fixed worker slots;
- selected profile capability;
- annotated encoder availability when requested;
- recording staging high-watermark.

If no slot is available, creation returns `LIVE_CAPACITY_EXHAUSTED`. The initial
release does not queue sessions silently and never reports false `ACTIVE`.

The limit is deployment configuration, not a caller-provided resource class.

## Database Changes

- remove `uq_live_single_running`;
- enforce at most one nonterminal generation per session;
- retain unique session/generation identity;
- add indexes for claimable desired generations and active lease expiry;
- use transactional admission or an equivalent database guard so concurrent
  session requests cannot both consume the last slot;
- retain bounded transition history for recovery.

## Media Isolation

- ingress and annotated path names use opaque generation IDs;
- no worker exposes a public RTSP port;
- MediaMTX owns public RTSP/WebRTC ports once per deployment;
- publisher targets and credentials are generation scoped;
- recording roots and MinIO keys are generation scoped;
- a stale worker cannot publish readiness for a replacement path;
- path deletion follows worker stop and bounded viewer grace.

## Process Isolation

- one native child owns one DeepStream graph;
- each child has independent command, frame-result, identity-evidence, and output
  queues;
- queue saturation in one session cannot consume another session's queue;
- child crash is reported against only its lease/run;
- teardown releases source and tee request pads, bus watches, probes, threads,
  sockets, encoder contexts, and GPU buffers;
- dynamic batching is not used to hide teardown defects.

## Identity Concurrency

Known and anonymous identities are global across sessions. Native tracker IDs are
not.

Concurrent sessions search the same Qdrant gallery and persist through the same
business services. New anonymous creation requires a final gallery recheck and a
database identity-level guard so two sessions do not create two active global
IDs for the same accepted evidence window.

Cross-camera appearance correlation is simply the same global `faceId` appearing
in separate camera/location results. Body ReID and trajectory stitching remain
out of scope.

## Connector Isolation

- each session has bounded connector queues;
- one slow Webhook does not block another connector or session;
- frame-drop counters are attributed in logs/traces and aggregate metrics without
  high-cardinality labels;
- critical track/session lifecycle uses a separate control path;
- stopping a session drains or cancels its connector work according to the
  documented direct-delivery policy.

## Recovery

### Worker Restart

The expired lease fences the old process. A free worker slot may claim the same
desired generation as a new runtime attempt. Timing continuity is not assumed;
open tracks and optional appearance intervals close before the new timing epoch.

### Native Child Crash

The worker marks the run failed or reconnecting according to retry policy,
releases the slot after cleanup, and does not mutate another run.

### MediaMTX Restart

The Session Controller recreates desired ingress/annotated paths. Workers remain
reconnecting until their internal input path is readable and do not report stale
`ACTIVE`.

### API Restart

Durable desired generations, current leases, and MediaMTX active paths are
reconciled. API restart does not require stopping healthy leased workers.

## Scaling Beyond One Host

The fixed pool contract deliberately preserves a later seam:

- worker ID and capabilities can become a registry;
- fixed slots can become measured resource reservations;
- claim selection can become placement;
- one-process-per-session can remain a supported isolation class;
- a compatible shared/batched runtime can be added behind the same generation
  fencing.

None of this is required before the fixed-pool acceptance gate passes.

## Observability

Metrics include:

- configured, occupied, and available slot totals;
- admission accepted/rejected counts by bounded reason;
- active/starting/reconnecting session totals;
- lease renew/expiry and runtime restart totals;
- aggregate input/processed/output FPS;
- child process and teardown outcomes;
- aggregate decoder/encoder/GPU memory utilization.

Session, camera, worker, lease, path, and face IDs are not metric labels.

## Stable Errors

- `LIVE_CAPACITY_EXHAUSTED`;
- `LIVE_PROFILE_CAPABILITY_UNAVAILABLE`;
- `LIVE_ENCODER_CAPACITY_EXHAUSTED`;
- `LIVE_RECORDING_CAPACITY_EXHAUSTED`;
- `LIVE_WORKER_LEASE_LOST`;
- `LIVE_WORKER_START_FAILED`;
- `LIVE_WORKER_TEARDOWN_FAILED`.

## Acceptance

- concurrently start at least three deterministic camera fixtures;
- every session emits independent ordered frame JSON;
- known/global-anonymous IDs are correct without tracker-ID collision;
- kill one native process and prove other sessions continue;
- disconnect one source and prove other session states do not change;
- stall one annotated viewer and one connector without affecting others;
- restart MediaMTX and verify all desired paths reconcile;
- restart one worker and verify lease fencing and a clean new runtime attempt;
- fill all slots and verify the next request is rejected before media/GPU work;
- issue concurrent requests for the last slot and accept at most one;
- repeatedly start/stop all sessions and measure bounded file descriptors,
  threads, sockets, request pads, GPU memory, and MediaMTX paths;
- verify no frame, identity assignment, connector event, recording, path, or URL
  crosses session generations;
- report measured capacity only for the tested hardware, source resolution,
  sampling, profile, recording, and annotated-output combination.
