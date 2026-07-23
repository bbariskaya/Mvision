# Isolated Multi-Camera Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run at least three live sessions concurrently through fixed database-backed worker slots, with one native process per session and strict isolation of leases, paths, queues, media, identity events, failures, and teardown.

**Architecture:** Represent deployment capacity as a fixed PostgreSQL `live_worker_slot` inventory. Session creation transactionally reserves one compatible free slot before MediaMTX or GPU work; a worker process configured for that slot claims only its assigned generation and launches one native child. Existing run/lease fencing is extended to immutable generation plus runtime attempt, while every connector queue, recording root, annotated path, and in-memory state object remains generation-owned. Capacity is measured and configured, never inferred dynamically or requested by callers.

**Tech Stack:** Python 3.12, asyncio subprocesses, FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL 16, MediaMTX v1.19.2, Docker Compose, Prometheus/OpenTelemetry, pytest, native DeepStream fixture workers.

## Documentation Locks

- SQLAlchemy 2 `/websites/sqlalchemy_en_20`: reserve and claim slots with explicit transactions, row locks, `with_for_update(skip_locked=True)`, partial unique indexes, and fenced `UPDATE ... RETURNING`.
- FastAPI `/websites/fastapi_tiangolo`: capacity rejection remains a stable service error behind the Delivery 1 API-key dependency; no caller-controlled scheduling fields are added to OpenAPI.
- MediaMTX `/bluenviron/mediamtx`: one deployment server owns public RTSP/WebRTC ports; all ingress and annotated paths remain opaque generation-scoped dynamic path configs reconciled from PostgreSQL.
- Pydantic `/pydantic/pydantic`: capability responses expose measured limits as typed data; session request models continue to reject arbitrary GPU IDs, ports, process counts, and resource classes.

## Global Constraints

- Do not use subagents.
- Do not create commits unless the user explicitly asks.
- Deliveries 1-3 and their immutable generations, frame events, connector workers, MediaMTX paths, recording inventory, annotated branch, and safe teardown are complete prerequisites.
- Initial capacity is a fixed deployment setting proven on the target hardware; there is no dynamic scheduler, overcommit, placement API, or shared DeepStream graph.
- Each occupied slot owns exactly one live generation and at most one active native child process.
- A runtime retry increments `runtime_attempt` while preserving session generation and reserved slot.
- Only the exact worker ID plus lease token plus unexpired lease plus run/generation/attempt may update runtime state or accept worker-originated results.
- API admission rejects before MediaMTX provisioning and GPU work when no compatible slot exists.
- No worker exposes a public RTSP/UDP port. MediaMTX owns public ports once per deployment.
- Tracker IDs are generation-local. Known and persistent anonymous `faceId` values remain global.
- One session's queue, source disconnect, viewer stall, connector failure, recording failure, child crash, or lease loss cannot mutate or block another session.
- Dynamic IDs are allowed in logs/traces but never become metric labels.

---

## File Structure

- Modify `backend/app/infrastructure/database/models.py`: fixed slot ownership and runtime-attempt constraints.
- Create `backend/app/infrastructure/database/repositories/live_capacity_repository.py`: slot inventory, reservation, transfer, state, and release.
- Modify `backend/app/infrastructure/database/repositories/live_session_repository.py`: slot-scoped generation claim and runtime attempts.
- Create `backend/app/services/live_capacity_service.py`: admission policy, slot bootstrap/reconciliation, capabilities, and release orchestration.
- Modify `backend/app/services/live_session_service.py`: reserve before media, transfer on reconfigure, and release after teardown.
- Modify `backend/app/services/live_supervisor.py`: `process_slot`, exact fencing, child ownership, and per-generation service scope.
- Modify `backend/app/infrastructure/live/native_runner.py`: process-group lifecycle and observable PID/teardown result.
- Modify `backend/app/worker/live_worker_main.py`: required fixed slot ID and slot-scoped loop.
- Modify `backend/app/presentation/schemas/live_sessions.py`: measured capacity response fields only.
- Modify `backend/app/presentation/dependencies.py`, `backend/app/main.py`: capacity service and startup reconciliation.
- Modify `backend/app/config.py`, `backend/.env.example`: fixed slot inventory and measured limits.
- Create `backend/alembic/versions/0b7d3c9e6a42_isolated_multi_camera.py`: remove single-running index and add slot/admission constraints.
- Modify `docker-compose.live.yml`: three explicit isolated live worker services and no worker public media ports.
- Modify `backend/app/observability/metrics.py`: bounded slot/admission/child/restart/teardown metrics.
- Create `backend/tests/integration/persistence/test_live_capacity_repository.py`: concurrent reservation/claim/release tests.
- Create `backend/tests/integration/live/test_multi_camera_isolation.py`: three-camera and fault-isolation gate.
- Create `backend/tests/integration/live/test_multi_camera_recovery.py`: worker/MediaMTX/API restart gate.
- Create `backend/scripts/multi_camera_smoke.py`: repeatable target-hardware acceptance runner.
- Create `docs/benchmarks/live-capacity-target-hardware.md`: measured supported workload matrix.

---

### Task 1: Fixed Slot Inventory And Transactional Admission

**Files:**
- Modify: `backend/app/infrastructure/database/models.py`
- Create: `backend/app/infrastructure/database/repositories/live_capacity_repository.py`
- Create: `backend/app/services/live_capacity_service.py`
- Create: `backend/alembic/versions/0b7d3c9e6a42_isolated_multi_camera.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/integration/persistence/test_live_capacity_repository.py`
- Test: `backend/tests/unit/test_live_capacity_service.py`

**Interfaces:**
- Produces model/table: `LiveWorkerSlot` / `live_worker_slot`.
- Produces: `LiveCapacityRepository.reserve/reassign/mark_running/mark_releasing/release`.
- Produces: `LiveCapacityService.admit/reconfigure/reconcile_inventory/capabilities`.
- Consumes generation IDs and profile/output requirements from Delivery 1 compiler.

- [ ] **Step 1: Write failing concurrent-admission tests**

Seed one slot, launch two independent database transactions that reserve the last
slot, and assert exactly one succeeds. Assert the loser receives
`LIVE_CAPACITY_EXHAUSTED`; no generation/media desired state remains from its
rolled-back transaction. Also test encoder compatibility and recording staging
high-watermark rejection.

- [ ] **Step 2: Run persistence tests and verify failure**

Run: `cd backend && pytest tests/integration/persistence/test_live_capacity_repository.py tests/unit/test_live_capacity_service.py -q`

Expected: FAIL because no slot inventory exists.

- [ ] **Step 3: Add the fixed slot table and remove the legacy singleton index**

```text
live_worker_slot:
  slot_id INTEGER primary key
  state FREE|RESERVED|RUNNING|RELEASING
  generation_id UUID FK live_session_generation unique null
  reservation_token UUID unique null
  draining_run_id UUID FK live_session_run null
  encoder_capable BOOLEAN not null
  gpu_id INTEGER not null
  reserved_at/updated_at TIMESTAMPTZ not null
  CHECK ownership fields are all null only in FREE
```

Drop `uq_live_single_running` from legacy `live_camera`. Retain at most one current
desired generation per session with a partial unique index on
`live_session_generation(session_id) WHERE desired_state = 'running'`. During
reconfigure, the old desired generation becomes terminal `superseded` in the same
transaction that marks the replacement desired; its runtime run may remain
`STOPPING` until teardown. Migration `down_revision` is `f42e9b6a5c31`.

- [ ] **Step 4: Add fixed measured settings**

```python
live_worker_slot_count: int = Field(default=3, ge=1, le=32)
live_worker_slot_id: int | None = Field(default=None, ge=0)
live_max_concurrent_sessions: int = Field(default=3, ge=1, le=32)
live_encoder_slot_count: int = Field(default=3, ge=0, le=32)
live_admission_lock_key: int = 0x4D564C4956454341
live_child_terminate_seconds: float = Field(default=5.0, gt=0, le=30)
live_child_kill_seconds: float = Field(default=2.0, gt=0, le=10)
```

Validate max sessions does not exceed slot count and encoder slots do not exceed
slot count. These settings are deployment-owned and absent from session requests.

- [ ] **Step 5: Implement exact slot reservation**

```python
async def reserve(
    self,
    db: AsyncSession,
    generation_id: str,
    reservation_token: str,
    requires_encoder: bool,
    now: datetime,
) -> LiveWorkerSlot | None:
    stmt = (
        select(LiveWorkerSlot)
        .where(
            LiveWorkerSlot.state == "FREE",
            (LiveWorkerSlot.encoder_capable.is_(True) if requires_encoder else true()),
        )
        .order_by(LiveWorkerSlot.slot_id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    slot = (await db.execute(stmt)).scalar_one_or_none()
    if slot is None:
        return None
    slot.state = "RESERVED"
    slot.generation_id = generation_id
    slot.reservation_token = reservation_token
    slot.reserved_at = now
    await db.flush()
    return slot
```

Take the configured transaction advisory lock before checking recording staging
capacity and selecting a slot, so concurrent API processes cannot both pass a
global admission check.

- [ ] **Step 6: Reconcile configured inventory safely**

At startup create missing IDs `[0, slot_count)`, mark the first
`encoder_slot_count` encoder-capable, and reject configuration that would remove
an occupied slot. Never clear a slot merely because the API restarted. Repair a
slot only from durable generation desired state and current run lease.

- [ ] **Step 7: Run migration and admission tests**

Run: `cd backend && alembic upgrade head && pytest tests/integration/persistence/test_live_capacity_repository.py tests/unit/test_live_capacity_service.py -q`

Expected: PASS; concurrent last-slot admission accepts at most one transaction.

---

### Task 2: Reserve Before Media And Transfer Capacity On Reconfigure

**Files:**
- Modify: `backend/app/services/live_session_service.py`
- Modify: `backend/app/services/live_session_compiler.py`
- Modify: `backend/app/presentation/schemas/live_sessions.py`
- Modify: `backend/tests/unit/test_live_session_service.py`
- Modify: `backend/tests/contract/test_live_sessions_api.py`

**Interfaces:**
- Changes: `LiveSessionService.create()` reserves a compatible slot in the session/generation transaction before MediaMTX reconciliation.
- Changes: stop marks slot `RELEASING`; cleanup confirmation releases it.
- Produces capability fields: configured/occupied/available session slots and encoder slots.

- [ ] **Step 1: Write failing service/API tests**

Assert exhausted create returns HTTP 409 with `LIVE_CAPACITY_EXHAUSTED` and makes
zero MediaMTX client calls. Assert encoder exhaustion returns
`LIVE_ENCODER_CAPACITY_EXHAUSTED`; recording high-watermark returns
`LIVE_RECORDING_CAPACITY_EXHAUSTED`. Assert request/OpenAPI contains no `gpuId`,
`slotId`, `workerId`, `resourceClass`, `processCount`, or port fields.

- [ ] **Step 2: Run service/API tests and verify failure**

Run: `cd backend && pytest tests/unit/test_live_session_service.py tests/contract/test_live_sessions_api.py -q`

Expected: FAIL because creation does not reserve fixed capacity.

- [ ] **Step 3: Make admission part of durable creation**

Use this order in one transaction:

```text
compile and validate profile/output requirements
allocate session and generation IDs
insert session + immutable generation desired state
check recording high-watermark under admission lock
reserve compatible live_worker_slot for generation
commit durable intent and capacity together
only then reconcile ingress/recording/annotated MediaMTX paths
```

Rollback all inserted rows when no slot exists. MediaMTX is never called from the
database transaction.

- [ ] **Step 4: Transfer or retain a slot during reconfigure**

If the current slot satisfies the replacement profile, atomically move its
`generation_id` to generation `N+1`, set `draining_run_id` to generation `N`'s
active run, mark the slot `RELEASING`, mark `N` superseded, and request old run
stop. The new generation is not claimable while `draining_run_id` is non-null.
After fenced old-run teardown, clear `draining_run_id` and change the slot to
`RESERVED` for `N+1`. If the slot lacks a newly required capability, reserve a
free compatible replacement or reject before media work.

- [ ] **Step 5: Release only after complete generation teardown**

Stop marks the slot `RELEASING`. Release to `FREE` only after the
native child is gone, connector/appearance workers are closed, recording open
segment is finalized or handed to reconciliation, annotated publisher stopped,
and generation paths entered cleanup/grace state. Use a fenced release matching
the exact generation/reservation token. Reconfigure performs the handoff above
instead of releasing the retained slot.

- [ ] **Step 6: Expose measured capacity without scheduling controls**

Add to capabilities:

```json
{
  "capacity": {
    "configuredSessionSlots": 3,
    "occupiedSessionSlots": 1,
    "availableSessionSlots": 2,
    "configuredEncoderSlots": 3,
    "availableEncoderSlots": 2,
    "admissionMode": "fixedSlots"
  }
}
```

- [ ] **Step 7: Run service/API tests**

Run: `cd backend && pytest tests/unit/test_live_session_service.py tests/contract/test_live_sessions_api.py -q`

Expected: PASS.

---

### Task 3: Slot-Scoped Generation Claims And Runtime Attempts

**Files:**
- Modify: `backend/app/infrastructure/database/repositories/live_session_repository.py`
- Modify: `backend/app/services/live_supervisor.py`
- Modify: `backend/tests/integration/persistence/test_live_session_repositories.py`
- Modify: `backend/tests/unit/test_live_supervisor.py`

**Interfaces:**
- Produces: `claim_generation(db, slot_id, worker_id, lease_token, now, lease_seconds) -> LiveSessionRun | None`.
- Produces: `LiveSupervisor.process_slot(slot_id, worker_id) -> bool`.
- Guarantees all result/state writes are fenced by generation, run, runtime attempt, worker, lease token, and lease expiry.

- [ ] **Step 1: Write failing claim/fencing tests**

Assert slot 0 cannot claim slot 1's generation. Assert two workers configured for
slot 0 cannot both claim. Expire a lease and assert a new run preserves generation
but increments `runtime_attempt`. Send a late frame/state/expiry from attempt 1
after attempt 2 claims and assert no persistence, delivery, or appearance update.

- [ ] **Step 2: Run repository/supervisor tests and verify failure**

Run: `cd backend && pytest tests/integration/persistence/test_live_session_repositories.py tests/unit/test_live_supervisor.py -q`

Expected: FAIL because claims are not fixed-slot scoped.

- [ ] **Step 3: Implement a slot-locked claim transaction**

```text
SELECT live_worker_slot WHERE slot_id=:slot_id FOR UPDATE
require RESERVED, or RUNNING with an expired run lease, and a desired media-ready generation
require draining_run_id is null
SELECT latest run for generation FOR UPDATE
return none if its lease is unexpired and nonterminal
fence expired run as FAILED/LIVE_WORKER_LEASE_EXPIRED
insert run with max(runtime_attempt)+1, new run_id/token/expiry
mark slot RUNNING without changing generation ownership
```

Add `UNIQUE(generation_id, runtime_attempt)` and indexes over desired/media state,
slot ownership, and lease expiry.

- [ ] **Step 4: Apply complete fenced update predicates**

Every worker-originated database update uses:

```python
where(
    LiveSessionRun.run_id == run_id,
    LiveSessionRun.generation_id == generation_id,
    LiveSessionRun.runtime_attempt == runtime_attempt,
    LiveSessionRun.worker_id == worker_id,
    LiveSessionRun.lease_token == lease_token,
    LiveSessionRun.lease_expires_at > now,
)
```

Require one returned row. Otherwise raise `LIVE_WORKER_LEASE_LOST`, stop the child,
and discard all queued late work.

- [ ] **Step 5: Scope all in-memory services to one generation**

Construct frame projection, identity state, appearance aggregation, connector
queues, and persistence queue inside `process_slot` after claim. Pass immutable
generation context into each. Close and discard that scope before another claim;
never retain tracker/assignment/new-anonymous state across runtime attempts.

- [ ] **Step 6: Run claim and supervisor tests**

Run: `cd backend && pytest tests/integration/persistence/test_live_session_repositories.py tests/unit/test_live_supervisor.py -q`

Expected: PASS.

---

### Task 4: One Child Process Per Worker Slot And Deterministic Teardown

**Files:**
- Modify: `backend/app/infrastructure/live/native_runner.py`
- Modify: `backend/app/worker/live_worker_main.py`
- Modify: `backend/app/services/live_supervisor.py`
- Modify: `backend/tests/unit/test_live_native_runner.py`
- Modify: `backend/tests/unit/test_live_supervisor.py`
- Create: `backend/tests/integration/live/test_live_worker_slot_process.py`

**Interfaces:**
- Produces: `NativeLiveProcess(pid, started_at)` observable ownership metadata.
- Produces worker loop that requires one valid configured slot ID.
- Guarantees child termination before slot release or next claim.

- [ ] **Step 1: Write failing process-isolation tests**

Run two fake slots concurrently and assert distinct native PIDs and independent
stdin/stdout/command/event queues. Kill one child and assert only its supervisor
returns a child failure. Simulate lease loss and assert TERM then bounded KILL,
pipe tasks close, and no child remains before the slot can be reclaimed.

- [ ] **Step 2: Run runner/worker tests and verify failure**

Run: `cd backend && pytest tests/unit/test_live_native_runner.py tests/unit/test_live_supervisor.py tests/integration/live/test_live_worker_slot_process.py -q`

Expected: FAIL on missing slot/process lifecycle behavior.

- [ ] **Step 3: Start every native child in its own process group**

```python
process = await asyncio.create_subprocess_exec(
    settings.live_native_executable,
    str(gpu_id),
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    start_new_session=True,
)
```

On cancellation/lease loss, close command input, send `SIGTERM` to the process
group, wait `live_child_terminate_seconds`, then `SIGKILL` and wait
`live_child_kill_seconds`. Report a stable teardown outcome; never release a slot
while `returncode is None`.

- [ ] **Step 4: Require fixed worker identity at startup**

`LIVE_WORKER_SLOT_ID` is mandatory in the worker service and must be less than
configured slot count. Worker ID defaults to a bounded service/hostname value but
is not a metric label. The loop calls only:

```python
processed = await supervisor.process_slot(slot_id, worker_id)
```

There is no scan/claim across other slots.

- [ ] **Step 5: Keep runtime retry independent from generation**

Child crash marks only the current run attempt failed. If generation desired
state remains running, keep slot reserved and allow the same/future worker for
that slot to claim attempt `N+1` after cleanup/backoff. Close tracks/appearance at
the old timing epoch; never pretend continuity.

- [ ] **Step 6: Run process-isolation tests**

Run: `cd backend && pytest tests/unit/test_live_native_runner.py tests/unit/test_live_supervisor.py tests/integration/live/test_live_worker_slot_process.py -q`

Expected: PASS.

---

### Task 5: Three-Worker Deployment And Session-Scoped Observability

**Files:**
- Modify: `docker-compose.live.yml`
- Modify: `backend/app/observability/metrics.py`
- Modify: `backend/app/services/live_capacity_service.py`
- Modify: `backend/tests/unit/test_live_metrics.py`
- Create: `backend/tests/contract/test_live_compose_topology.py`

**Interfaces:**
- Produces three explicit worker services for slots 0, 1, and 2 on GPU 0.
- Produces low-cardinality slot/admission/session/child metrics.
- Consumes one shared MediaMTX deployment and existing durable services.

- [ ] **Step 1: Write failing topology and metrics tests**

Parse Compose and assert three workers have unique `LIVE_WORKER_SLOT_ID`, no
public `ports`, the same internal metrics port is safe in separate containers,
and only MediaMTX exposes RTSP/WebRTC. Assert metric labels contain bounded states/
reasons only, never session/camera/worker/lease/path/face IDs.

- [ ] **Step 2: Define three explicit isolated workers**

Create `live-worker-0`, `live-worker-1`, and `live-worker-2` with slot IDs 0/1/2,
unique OpenTelemetry service instance resources, the same measured GPU ID 0, and
independent container process namespaces. Mount code/config read-only plus only
the shared resources required by the worker. Remove legacy `8554:8554` and fixed
UDP settings from every worker.

- [ ] **Step 3: Add bounded capacity/runtime metrics**

```text
live_slots{state=free|reserved|running|releasing}
live_admission_total{outcome=accepted|rejected,reason=capacity|encoder|recording|profile}
live_sessions{state=starting|active|reconnecting|stopping|failed}
live_lease_total{outcome=renewed|expired|lost}
live_child_total{outcome=started|stopped|failed|killed|teardown_failed}
live_runtime_restart_total{reason=child|lease|source|mediamtx}
```

Set aggregate decoder/encoder/FPS/GPU metrics without per-session labels. Put
dynamic IDs in structured logs/traces only.

- [ ] **Step 4: Run topology and metric tests**

Run: `cd backend && pytest tests/contract/test_live_compose_topology.py tests/unit/test_live_metrics.py -q`

Expected: PASS.

---

### Task 6: Restart And Cross-Session Isolation Recovery

**Files:**
- Modify: `backend/app/services/live_capacity_service.py`
- Modify: `backend/app/services/mediamtx_reconciliation_service.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/live/test_multi_camera_recovery.py`

**Interfaces:**
- Reconciles API, worker, native child, and MediaMTX restarts from durable desired state.
- Consumes exact lease/path/slot fences from prior tasks.

- [ ] **Step 1: Write failing restart scenarios**

Start three generations, then separately restart one worker, kill one native child,
restart MediaMTX, and restart API. Assert unaffected sessions never change state,
old attempts cannot publish results/readiness, desired paths are recreated, and
healthy leased workers are not stopped by API restart.

- [ ] **Step 2: Reconcile slots without stealing healthy leases**

On API startup, inspect each occupied slot plus desired generation and latest run.
Keep `RUNNING` when its lease is unexpired. Set `RESERVED` for desired generations
with no healthy run. Set `RELEASING` for stopped/superseded generations pending
cleanup. Release only after cleanup confirms no child/run ownership and path grace
conditions.

- [ ] **Step 3: Reconcile MediaMTX paths for all desired generations**

Recreate each ingress and optional annotated path independently. Clear stale
media/output ready state while paths are offline. Workers remain reconnecting
until their own ingress is online; one missing path cannot alter another
generation. Recording scan remains generation-directory scoped.

- [ ] **Step 4: Fence old output and result events after restart**

Every `frame_result`, `track_evidence`, `track_expired`, state, metrics, and
annotated output event passes session/run/generation/runtime-attempt/lease checks
before entering any service queue. Drop and count stale events with bounded reason
only.

- [ ] **Step 5: Run recovery tests**

Run: `cd backend && pytest tests/integration/live/test_multi_camera_recovery.py -q`

Expected: PASS.

---

### Task 7: Multi-Camera Acceptance And Measured Capacity Report

**Files:**
- Create: `backend/tests/integration/live/test_multi_camera_isolation.py`
- Create: `backend/scripts/multi_camera_smoke.py`
- Create: `docs/benchmarks/live-capacity-target-hardware.md`
- Modify: `docs/implementation/CURRENT_SPRINT.md`

**Interfaces:**
- Proves the fixed three-slot workload on target hardware.
- Produces a bounded capacity claim tied to exact tested conditions.

- [ ] **Step 1: Start three deterministic camera fixtures concurrently**

Use three independent H.264 paths with overlapping tracker IDs and known/
anonymous fixtures. Assert each session has ordered independent frame JSON,
correct global identities, generation-scoped paths, separate connector queues,
and separate recording/annotation state.

- [ ] **Step 2: Prove fault isolation**

Kill one native process, disconnect another source, stall one annotated viewer,
block one Webhook, fail one recording target, and saturate one frame queue. Assert
the other sessions' states, frame progress, connector delivery, recording, and
viewer output remain unchanged.

- [ ] **Step 3: Prove admission boundaries**

Fill all three slots and create a fourth session. Assert
`LIVE_CAPACITY_EXHAUSTED` before any MediaMTX/GPU call. Issue two concurrent
requests for the last free slot and accept exactly one. Repeat with the last
encoder-capable slot and recording high-watermark.

- [ ] **Step 4: Prove repeated concurrent teardown**

Run at least 50 start/stop cycles across all three slots. Capture process IDs,
threads, file descriptors, sockets, tee request pads, GPU memory, MediaMTX paths,
connector tasks, and recording files before/after. Assert bounded return to the
measured baseline and zero stale generation events.

- [ ] **Step 5: Record the exact supported workload**

Write the target GPU/driver/DeepStream versions, source codec/resolution/FPS,
sampling mode/rate, profile/model versions, recording/annotation combination,
session count, observed latency/FPS/drop rates, GPU memory, and test duration.
Claim support only for the measured matrix; do not extrapolate automatic capacity.

- [ ] **Step 6: Run the complete Delivery 4 gate**

Run: `cd backend && pytest tests/unit/test_live_capacity_service.py tests/unit/test_live_session_service.py tests/unit/test_live_supervisor.py tests/unit/test_live_native_runner.py tests/unit/test_live_metrics.py tests/contract/test_live_sessions_api.py tests/contract/test_live_compose_topology.py tests/integration/persistence/test_live_capacity_repository.py tests/integration/persistence/test_live_session_repositories.py tests/integration/live/test_live_worker_slot_process.py tests/integration/live/test_multi_camera_recovery.py tests/integration/live/test_multi_camera_isolation.py -q`

Run: `git diff --check`

Expected: all tests PASS; three simultaneous sessions remain isolated, fourth
admission is rejected before media/GPU work, and resource measurements remain
bounded through repeated teardown.

---

## Self-Review Checklist

- [ ] Fixed slot inventory is durable, configured, and reconciled without clearing healthy ownership.
- [ ] Concurrent last-slot requests cannot both succeed.
- [ ] Capacity is reserved before MediaMTX and GPU work.
- [ ] Every worker claims one configured slot only and owns at most one child.
- [ ] Runtime attempt increments do not create a new generation.
- [ ] Every result/state update is lease, generation, attempt, and worker fenced.
- [ ] Slot release waits for complete child/service/media teardown.
- [ ] No public worker RTSP/UDP port remains.
- [ ] Queues, paths, recording roots, OSD state, and trackers are generation scoped.
- [ ] Global identity matching/anonymous creation is concurrency safe while tracker IDs remain local.
- [ ] Worker/native/source/connector/viewer/recording failure in one session cannot mutate another.
- [ ] Metrics use bounded labels and capacity claims name exact measured conditions.
- [ ] No dynamic scheduler, shared graph, multi-host placement, body ReID, trajectory stitching, or caller resource controls entered Delivery 4.
