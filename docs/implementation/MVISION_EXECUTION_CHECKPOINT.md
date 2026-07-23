# Mvision Execution Checkpoint

Last updated: 2026-07-23

This is the canonical resume point for compaction, a new session, or an agent
handoff. Update it after every major GREEN task, architecture decision,
root-cause fix, or blocker.

## Working Rules

- Use Context7 continuously before and during decisions involving libraries,
  frameworks, SDKs, APIs, CLI tools, MediaMTX, or infrastructure products.
- Do not optimize Context7 usage for quota; current official documentation is
  preferred over memory.
- Do not use subagents or create commits unless the user explicitly requests it.
- Work on the current `main` checkout was explicitly approved. Preserve all
  unrelated dirty-worktree changes.
- Fix every known in-scope defect. Remove stale code and artifacts only after
  their replacement passes its complete E2E gate.
- There is no user login or role hierarchy. All users have full privileges.
  `/api/v1/live/*` uses only a transparent internal `X-API-Key` injected by
  Nginx; the browser and operator never receive it.
- GPU nodes are fungible: every node uses the same image and has every native
  binary. Image, video, and live remain separate processes for fault isolation.
- Periodically, and especially after compaction or a major task boundary,
  re-read this checkpoint, the active authoritative plans, and the latest linked
  prompt-memory checkpoints instead of relying only on conversation summaries.

## Completed Phase 1 And Phase 2

The Phase 1/2 compliance plan in
`docs/superpowers/plans/2026-07-23-phase1-phase2-requirements-compliance.md`
is implemented:

- corrupt-image rejection, exact-one enrollment, stable `faceId`, and aligned
  evidence only;
- durable image process details;
- lifecycle-aware video identity voting;
- configurable video limits and object prefixes;
- global concurrency admission, exhausted lease recovery, and lease-loss
  propagation;
- fenced deterministic video finalization and consistent cancellation/errors;
- continuous retention enforcement and complete appearance references.

Latest complete evidence:

- Python unit + contract + native parity: `265 passed`;
- native GPU/DeepStream CTest: `13/13 passed`;
- Ruff: clean;
- mypy: `82` application source files clean;
- Compose config: valid;
- Alembic: one head, `c83f19d4a2e7`;
- `git diff --check`: clean.

## Native Build Decision

- Canonical source: `backend/pipeline`.
- `build/pipeline-new` is stale build output, not a second source pipeline.
- `backend/pipeline/Dockerfile.native-test` supplies the pinned DeepStream 9
  test builder and missing `libmsgpack-dev` dependency.
- `make native-test` configures and builds `build-native-tests` as the host user,
  runs all 13 CTest targets with GPU access, and runs Python/native parity.
- The old/root-owned build artifacts can be removed only after the canonical
  runtime image consumes the verified replacement artifacts.

## Important Root-Cause Fixes

- Root-owned `build/` had no root CTest metadata and container-generated CTest
  files used absolute `/workspace` paths. A host-UID mounted container build
  fixed ownership and path correctness.
- The DeepStream base image did not contain `msgpack.hpp`; the native test image
  now installs `libmsgpack-dev` reproducibly.
- Enabling anonymous video voting initially affected live recognition because
  both domains shared one voter instance. The voter now has explicit eligible
  lifecycle policy and live uses a separate known-only voter.
- `lease_token` is only an internal worker ownership/fencing nonce. It is not
  user authentication.

## Active Plan

Plan: `docs/superpowers/plans/2026-07-23-live-session-mediamtx-ingress.md`

### Task 1: Complete

Transparent internal API-key and bounded MediaMTX/profile settings:

- `backend/app/presentation/auth.py`;
- `backend/app/config.py`;
- `backend/.env.example`;
- `backend/tests/unit/test_live_api_auth.py`;
- `backend/tests/unit/test_live_settings.py`.

Evidence: `19 passed`, mypy clean, Ruff clean.

### Task 2: Complete

Strict Pydantic v2 live session schema and secret-free deterministic compiler:

- `backend/app/presentation/schemas/live_sessions.py`;
- `backend/app/services/live_session_compiler.py`;
- `backend/tests/unit/test_live_session_compiler.py`;
- `backend/tests/contract/test_live_sessions_schema.py`.

Evidence: `9 passed`, warning-free, mypy clean, Ruff clean.

### Task 3: Complete

Durable session, immutable generation, fenced runtime-attempt, and connector
persistence is complete:

- `LiveSession`, `LiveSessionGeneration`, `LiveSessionRun`, and `LiveConnector`
  in `backend/app/infrastructure/database/models.py`;
- `backend/app/infrastructure/database/repositories/live_session_repository.py`;
- `backend/app/infrastructure/database/repositories/live_connector_repository.py`;
- repository exports in `backend/app/infrastructure/database/repositories/__init__.py`.

The additive migration
`backend/alembic/versions/d92a7f4c1b30_live_session_api.py` creates only new
tables and keeps legacy `live_camera` data untouched.

Evidence:

- new repository integration: `4 passed`;
- all legacy + new persistence and model tests: `28 passed`;
- test database current: `d92a7f4c1b30 (head)`;
- one Alembic head: `d92a7f4c1b30`;
- mypy and Ruff: clean.

### Task 4: Complete At Typed Client/Reconciler Level

The narrow MediaMTX Control API client and PostgreSQL desired-state reconciler
are implemented:

- `backend/app/infrastructure/media/mediamtx_client.py`;
- `backend/app/services/mediamtx_reconciliation_service.py`;
- reconciliation persistence methods in `LiveSessionRepository`;
- focused client/reconciliation and repository integration tests.

Review against current Context7 MediaMTX v1.19.2 and HTTPX documentation found
and fixed two gaps before closure:

- `/v3/config/paths/list` defaults to 100-item pagination, so the client now
  reads and validates every reported page;
- a generation with desired state `running` remains a desired media path after
  a failed runtime attempt because that generation can be retried. Runtime
  `FAILED` no longer causes reconciliation to stale-delete its ingress path.

Evidence:

- focused MediaMTX client/reconciliation: `10 passed`;
- live-session repository/model tests: `7 passed`;
- all persistence integration tests: `27 passed`;
- all Python unit/contract tests with canonical native parity binary:
  `293 passed`;
- mypy: `90` application source files clean;
- Ruff and `git diff --check`: clean.

This evidence uses HTTPX `MockTransport`; no real MediaMTX process was running.
Real RTSP pull, WHEP pull, WHIP push, and restart reconciliation remain
`NOT_TESTED` until Task 7 starts the pinned MediaMTX Docker service.

### Task 5: Complete At Service And Public API Contract Level

The typed live session and connector control plane is implemented:

- `LiveSessionService.create/get/list/reconfigure/stop/capabilities`;
- `LiveConnectorService.create/get/list/delete`;
- strict Webhook/Kafka create schemas and secret-free response schemas;
- API-key-protected `/api/v1/live/capabilities`, session, and connector routers;
- dependency-container construction and MediaMTX client lifecycle cleanup;
- current-generation repository lookup and configurable compiler profile identity;
- generic bounded MultiFernet encryption for WHEP/source and connector secret
  payloads while retaining the legacy RTSP-only camera cipher methods.

Security and correctness fixes found during inline review:

- FastAPI's default request-validation response echoed rejected secret input.
  `/api/v1/live/*` now uses a sanitized validation envelope which never returns
  source URLs, Webhook destinations/tokens, or Kafka credentials;
- malformed session/connector UUIDs are rejected before PostgreSQL;
- connector references are canonical UUIDs and configured profile ID/version is
  used consistently by capabilities and the compiler;
- MediaMTX reconciliation cycles are serialized in-process to prevent duplicate
  concurrent path add/replace operations;
- a Control API outage during stale-path listing preserves already-recorded
  generation media failures instead of rolling them back;
- media recovery clears only `LIVE_MEDIA_PATH_FAILED`; worker/runtime error codes
  remain durable.

Evidence:

- Task 1-5 focused live tests: `68 passed`;
- complete Python unit/contract suite with canonical native parity binary:
  `323 passed`;
- all persistence integration tests: `27 passed`;
- mypy: `95` application source files clean;
- Ruff lint and Task 4/5 scoped format: clean;
- Alembic: one current head, `d92a7f4c1b30`;
- `git diff --check`: clean.

Real MediaMTX, camera media, Webhook delivery, and Kafka delivery remain
`NOT_TESTED`; Task 5 used typed contracts/fakes plus real PostgreSQL repository
tests. The user explicitly requires one real RTSP/MediaMTX frame to be delivered
to both a Webhook receiver and a real Kafka broker during today's Delivery 2
acceptance. Use pinned Docker services, not host installation or fake clients.

## Exact Next Step

Start Task 6 in
`docs/superpowers/plans/2026-07-23-live-session-mediamtx-ingress.md`:

1. Re-read the current live protocol/supervisor code and the Task 6 contract;
   re-check MessagePack/native lifecycle dependencies in Context7 where relevant.
2. Add RED supervisor and protocol parity tests for immutable session generation,
   runtime attempt, resolved safe processing fields, and internal MediaMTX RTSP
   input only.
3. Extend Python and C++ protocol symmetrically with one atomic version bump.
4. Add `process_one_session(worker_id)` while retaining the legacy camera path
   until real new-session E2E acceptance passes.
5. Run Python protocol/supervisor tests, native CTest/parity, Ruff, mypy, and
   update both checkpoints before Task 7 Docker MediaMTX acceptance.

Keep legacy `live_camera` and `live_camera_run` operational until the new live
session path passes the real MediaMTX E2E acceptance gate.
