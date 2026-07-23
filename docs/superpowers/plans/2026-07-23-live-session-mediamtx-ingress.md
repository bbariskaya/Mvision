# Live Session And MediaMTX Ingress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the typed `/api/v1/live/sessions` control plane, API-key protection, and MediaMTX-backed RTSP/WHEP pull plus WHIP push ingress without exposing media internals to callers.

**Architecture:** Keep the existing FastAPI/service/repository layering. Introduce durable session and immutable generation rows, compile public typed requests into internal resolved specs, and let a MediaMTX controller reconcile those specs into opaque paths. Adapt the existing live supervisor to claim a pre-created generation and consume only MediaMTX's internal RTSP URL.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL 16, Alembic, HTTPX, MediaMTX Control API v3, pytest.

## Documentation Locks

- FastAPI `/websites/fastapi_tiangolo`: use `APIKeyHeader` as a security
  dependency so the API-key scheme is represented in OpenAPI; do not manually
  read the header in route code.
- Pydantic `/pydantic/pydantic`: use a `Literal` discriminator for source unions,
  strict `extra="forbid"` request models, and explicit secret exclusion from safe
  serialization.
- SQLAlchemy 2 `/websites/sqlalchemy_en_20`: use `AsyncSession`, row locks,
  `with_for_update(skip_locked=True)`, database unique constraints, and fenced
  `UPDATE ... RETURNING`.
- MediaMTX `/bluenviron/mediamtx`, verified against official v1.19.2
  `mediamtx.yml` and OpenAPI: path source field is `source`, current RTSP pull
  transport field is `rtspTransport` (`sourceProtocol` is deprecated), active
  readiness uses `online` (`ready` is deprecated), WHEP sources use
  `whep://`/`wheps://`, and WebRTC publish/read endpoints are WHIP/WHEP.

## Global Constraints

- Do not use subagents.
- Do not create commits unless the user explicitly asks.
- Preserve existing image/video enrollment and recognition contracts.
- Keep source credentials write-only, encrypted, and absent from logs, traces, metrics, responses, hashes, and process arguments.
- Public source variants are exactly `rtspPull`, `whepPull`, and `whipPush`.
- DeepStream receives only a generation-scoped internal MediaMTX RTSP URL.
- Recognition always uses five-point alignment; no caller-controlled alignment switch is added.
- Reconfiguration creates a new immutable generation.
- MediaMTX Control API state is reconciled from PostgreSQL after restart.
- Keep the current `/api/v1/cameras` API operational until the new live-session E2E gate passes because persisted live-camera state already exists.

---

## File Structure

- Create `backend/app/presentation/auth.py`: API-key dependency for new live routes.
- Create `backend/app/presentation/schemas/live_sessions.py`: public request/response models and discriminated source union.
- Create `backend/app/presentation/schemas/live_connectors.py`: registered connector request/response models.
- Create `backend/app/services/live_session_compiler.py`: deterministic profile/override resolution and safe canonical hash.
- Create `backend/app/services/live_session_service.py`: create/get/list/reconfigure/stop orchestration.
- Create `backend/app/services/live_connector_service.py`: connector registration with encrypted secret data.
- Create `backend/app/services/mediamtx_reconciliation_service.py`: desired-path reconciliation.
- Create `backend/app/infrastructure/media/__init__.py`: media infrastructure package.
- Create `backend/app/infrastructure/media/mediamtx_client.py`: typed internal Control API client.
- Create `backend/app/infrastructure/database/repositories/live_session_repository.py`: session/generation persistence and claims.
- Create `backend/app/infrastructure/database/repositories/live_connector_repository.py`: connector persistence.
- Create `backend/app/presentation/routers/live_sessions.py`: session/capability endpoints.
- Create `backend/app/presentation/routers/live_connectors.py`: connector endpoints.
- Create `backend/alembic/versions/d92a7f4c1b30_live_session_api.py`: additive live-session migration.
- Modify `backend/app/infrastructure/database/models.py`: session, generation, connector models and runtime-attempt relation.
- Modify `backend/app/services/live_supervisor.py`: claim immutable generations and resolve internal RTSP input.
- Modify `backend/app/presentation/dependencies.py`: construct and expose new services.
- Modify `backend/app/main.py`: include new routers and lifecycle reconciliation.
- Modify `backend/app/config.py`: API-key, MediaMTX origins, timeout, and profile settings.
- Modify `backend/.env.example`, `docker-compose.live.yml`: declare runtime settings and MediaMTX connectivity.

---

### Task 1: Live API-Key And MediaMTX Settings

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/app/presentation/auth.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/unit/test_live_api_auth.py`
- Test: `backend/tests/unit/test_live_settings.py`

**Interfaces:**
- Produces: `require_live_api_key(request: Request, supplied: str | None) -> None`.
- Produces settings: `live_api_key`, `mediamtx_control_url`, `mediamtx_internal_rtsp_origin`, `mediamtx_public_whip_origin`, `mediamtx_public_rtsp_origin`, `mediamtx_public_webrtc_origin`, `mediamtx_request_timeout_seconds`.

- [ ] **Step 1: Write failing settings and authentication tests**

```python
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.presentation.auth import require_live_api_key


def test_live_settings_expose_media_origins() -> None:
    settings = Settings(
        _env_file=None,
        live_api_key=SecretStr("test-key"),
        mediamtx_control_url="http://mediamtx:9997",
        mediamtx_internal_rtsp_origin="rtsp://mediamtx:8554",
    )
    assert settings.mediamtx_control_url == "http://mediamtx:9997"
    assert settings.mediamtx_internal_rtsp_origin == "rtsp://mediamtx:8554"


def test_live_api_rejects_missing_or_wrong_key(monkeypatch) -> None:
    app = FastAPI()
    app.state.settings = Settings(_env_file=None, live_api_key=SecretStr("secret"))

    @app.get("/protected", dependencies=[Depends(require_live_api_key)])
    async def protected() -> dict:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/protected").status_code == 401
    assert client.get("/protected", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/protected", headers={"X-API-Key": "secret"}).json() == {"ok": True}
```

- [ ] **Step 2: Run the tests and verify the missing interfaces fail**

Run: `cd backend && pytest tests/unit/test_live_api_auth.py tests/unit/test_live_settings.py -q`

Expected: collection/import failure for `app.presentation.auth` or missing settings fields.

- [ ] **Step 3: Add bounded settings**

Add to `Settings`:

```python
live_api_key: SecretStr | None = None
mediamtx_control_url: str = "http://mediamtx:9997"
mediamtx_internal_rtsp_origin: str = "rtsp://mediamtx:8554"
mediamtx_public_whip_origin: str = "http://localhost:8889"
mediamtx_public_rtsp_origin: str = "rtsp://localhost:8554"
mediamtx_public_webrtc_origin: str = "http://localhost:8889"
mediamtx_request_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
live_profile_id: str = "face-recognition-v1"
live_profile_version: int = Field(default=1, ge=1)
```

Extend `validate_live_secrets()` so `LIVE_ENABLED=true` requires a non-empty
`LIVE_API_KEY` in addition to existing URI keys. Do not print key values.

- [ ] **Step 4: Implement constant-time API-key validation**

```python
import secrets
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader


live_api_key_header = APIKeyHeader(
    name="X-API-Key",
    scheme_name="LiveApiKey",
    auto_error=False,
)


async def require_live_api_key(
    request: Request,
    supplied: Annotated[str | None, Security(live_api_key_header)] = None,
) -> None:
    configured = request.app.state.settings.live_api_key
    if configured is None or supplied is None or not secrets.compare_digest(
        supplied, configured.get_secret_value()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "LIVE_API_KEY_INVALID"},
        )
```

- [ ] **Step 5: Add environment examples without real secrets**

```dotenv
LIVE_API_KEY=replace-me
MEDIAMTX_CONTROL_URL=http://mediamtx:9997
MEDIAMTX_INTERNAL_RTSP_ORIGIN=rtsp://mediamtx:8554
MEDIAMTX_PUBLIC_WHIP_ORIGIN=http://localhost:8889
MEDIAMTX_PUBLIC_RTSP_ORIGIN=rtsp://localhost:8554
MEDIAMTX_PUBLIC_WEBRTC_ORIGIN=http://localhost:8889
MEDIAMTX_REQUEST_TIMEOUT_SECONDS=3
```

- [ ] **Step 6: Run focused tests**

Run: `cd backend && pytest tests/unit/test_live_api_auth.py tests/unit/test_live_settings.py -q`

Expected: PASS.

---

### Task 2: Typed Session Schema And Deterministic Compiler

**Files:**
- Create: `backend/app/presentation/schemas/live_sessions.py`
- Create: `backend/app/services/live_session_compiler.py`
- Test: `backend/tests/unit/test_live_session_compiler.py`
- Test: `backend/tests/contract/test_live_sessions_schema.py`

**Interfaces:**
- Produces: `LiveSessionCreateRequest`, `LiveSessionReconfigureRequest`, `LiveSessionResponse`, `LiveCapabilitiesResponse`.
- Produces: `ResolvedLiveSessionSpec` dataclass.
- Produces: `LiveSessionCompiler.compile(request) -> ResolvedLiveSessionSpec`.

- [ ] **Step 1: Write failing source-union and dependency tests**

```python
import pytest
from pydantic import ValidationError

from app.presentation.schemas.live_sessions import LiveSessionCreateRequest
from app.services.live_session_compiler import LiveSessionCompiler


def request(**overrides) -> dict:
    value = {
        "schemaVersion": 1,
        "cameraId": "gate-1",
        "profile": "face-recognition-v1",
        "source": {"type": "whipPush"},
        "processing": {"mode": "recognize"},
        "json": {"connectorRefs": ["019f0000-0000-7000-8000-000000000001"]},
    }
    value.update(overrides)
    return value


def test_source_union_rejects_url_for_whip_push() -> None:
    with pytest.raises(ValidationError):
        LiveSessionCreateRequest.model_validate(
            request(source={"type": "whipPush", "url": "rtsp://forbidden"})
        )


def test_compile_is_hash_stable() -> None:
    parsed = LiveSessionCreateRequest.model_validate(request())
    first = LiveSessionCompiler().compile(parsed)
    second = LiveSessionCompiler().compile(parsed)
    assert first.spec_hash == second.spec_hash
    assert first.processing.alignment == "fivePoint"


def test_json_requires_connector_or_persistence() -> None:
    parsed = LiveSessionCreateRequest.model_validate(
        request(json={"connectorRefs": [], "persistFrames": False})
    )
    with pytest.raises(ValueError, match="LIVE_JSON_SINK_REQUIRED"):
        LiveSessionCompiler().compile(parsed)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend && pytest tests/unit/test_live_session_compiler.py tests/contract/test_live_sessions_schema.py -q`

Expected: FAIL because schema/compiler modules do not exist.

- [ ] **Step 3: Implement the discriminated source models**

```python
class RtspPullSource(ApiModel):
    type: Literal["rtspPull"]
    url: SecretStr


class WhepPullSource(ApiModel):
    type: Literal["whepPull"]
    url: SecretStr


class WhipPushSource(ApiModel):
    type: Literal["whipPush"]


LiveSource = Annotated[
    RtspPullSource | WhepPullSource | WhipPushSource,
    Field(discriminator="type"),
]
```

Add typed nested models for processing, source policy, JSON, appearance summary,
recording, annotated stream, and location. Set `extra="forbid"` on live request
models so unsupported fields fail instead of being ignored.

Use a live-specific base model rather than changing every existing API model:

```python
class StrictLiveApiModel(ApiModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )
```

- [ ] **Step 4: Implement profile resolution and canonical hashing**

```python
@dataclass(frozen=True)
class ResolvedLiveSessionSpec:
    schema_version: int
    profile_id: str
    profile_version: int
    source_type: str
    processing: ResolvedProcessingSpec
    source_policy: ResolvedSourcePolicy
    json: ResolvedJsonOutput
    recording: ResolvedRecordingOutput
    annotated_stream: ResolvedAnnotatedOutput
    spec_hash: str


class LiveSessionCompiler:
    def compile(self, request: LiveSessionCreateRequest) -> ResolvedLiveSessionSpec:
        if request.profile != "face-recognition-v1":
            raise ValueError("LIVE_PROFILE_NOT_FOUND")
        if not request.json.connector_refs and not request.json.persist_frames:
            raise ValueError("LIVE_JSON_SINK_REQUIRED")
        if request.processing.mode != "recognize" and request.processing.persistent_anonymous:
            raise ValueError("LIVE_SESSION_SPEC_INVALID")
        values = self._resolved_values(request)
        canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
        return ResolvedLiveSessionSpec(
            **values,
            spec_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
```

The canonical values must exclude source URL plaintext and connector secret
plaintext. Store only source type plus secret version/reference in requested and
resolved snapshots.

- [ ] **Step 5: Add OpenAPI secret-exclusion assertions**

Assert `LiveSessionResponse` has no `source.url`, `sourceCiphertext`, internal
RTSP origin, MediaMTX control URL, publisher credential, GPU ID, config path, or
port fields.

- [ ] **Step 6: Run focused tests**

Run: `cd backend && pytest tests/unit/test_live_session_compiler.py tests/contract/test_live_sessions_schema.py -q`

Expected: PASS.

---

### Task 3: Add Durable Sessions, Generations, And Connectors

**Files:**
- Modify: `backend/app/infrastructure/database/models.py`
- Create: `backend/app/infrastructure/database/repositories/live_session_repository.py`
- Create: `backend/app/infrastructure/database/repositories/live_connector_repository.py`
- Modify: `backend/app/infrastructure/database/repositories/__init__.py`
- Create: `backend/alembic/versions/d92a7f4c1b30_live_session_api.py`
- Test: `backend/tests/integration/persistence/test_live_session_repositories.py`
- Test: `backend/tests/unit/test_live_session_models.py`

**Interfaces:**
- Produces models: `LiveSession`, `LiveSessionGeneration`, `LiveConnector`.
- Produces repository methods: `create_session`, `create_generation`, `get`, `list`, `set_desired_state`, `claim_generation`, `renew_run`, `finish_run`.

- [ ] **Step 1: Write failing model/repository tests**

```python
@pytest.mark.asyncio
async def test_generation_snapshots_are_immutable(db_session) -> None:
    repo = LiveSessionRepository()
    session = await repo.create_session(
        db_session,
        camera_external_id="gate-1",
        location_snapshot={"site": "office-a"},
    )
    generation = await repo.create_generation(
        db_session,
        session_id=session.session_id,
        generation=1,
        requested_spec={"profile": "face-recognition-v1"},
        resolved_spec={"profileVersion": 1},
        spec_hash="a" * 64,
        source_type="whipPush",
        source_ciphertext=None,
        ingress_path="ingress/opaque",
    )
    await db_session.commit()
    assert generation.generation == 1
    with pytest.raises(IntegrityError):
        await repo.create_generation(
            db_session,
            session_id=session.session_id,
            generation=1,
            requested_spec={},
            resolved_spec={},
            spec_hash="b" * 64,
            source_type="whipPush",
            source_ciphertext=None,
            ingress_path="ingress/other",
        )
```

- [ ] **Step 2: Run the integration test and verify failure**

Run: `cd backend && pytest tests/integration/persistence/test_live_session_repositories.py -q`

Expected: FAIL because the tables/repositories do not exist.

- [ ] **Step 3: Add additive tables**

Create these constraints in the migration:

```text
live_session:
  session_id UUID primary key
  camera_external_id VARCHAR(255) not null
  location_snapshot JSONB null
  desired_state running|stopped
  current_generation INTEGER >= 1
  created_at, updated_at, stopped_at

live_session_generation:
  generation_id UUID primary key
  session_id FK live_session
  generation INTEGER >= 1
  requested_spec JSONB not null
  resolved_spec JSONB not null
  spec_hash CHAR(64) not null
  profile_id/profile_version
  source_type rtspPull|whepPull|whipPush
  source_ciphertext VARCHAR(8192) null
  ingress_path VARCHAR(255) unique not null
  desired_state running|stopped
  runtime_state ACCEPTED|WAITING_FOR_SOURCE|STARTING|ACTIVE|RECONNECTING|STOPPING|STOPPED|FAILED
  media_state provisioning|waiting|ready|failed
  created_at, started_at, stopped_at, error_code
  UNIQUE(session_id, generation)

live_connector:
  connector_id UUID primary key
  connector_type webhook|kafka
  name VARCHAR(255) unique not null
  safe_config JSONB not null
  secret_ciphertext VARCHAR(8192) null
  enabled BOOLEAN not null
  created_at, updated_at
```

Add `generation_id`, `runtime_attempt`, and generation fencing to a new
`live_session_run` table rather than overloading `live_camera_run`. Existing
legacy rows remain untouched during the additive rollout.

- [ ] **Step 4: Implement transactional generation creation**

`create_generation()` must lock the parent session, require
`generation == current_generation + 1` for reconfigure, then update
`current_generation` in the same transaction. Initial creation writes session
and generation 1 together.

- [ ] **Step 5: Implement claim with `FOR UPDATE SKIP LOCKED`**

Claim only generations whose desired state is running, media state is ready, and
which have no unexpired nonterminal run. A retry creates `runtime_attempt + 1`
without changing generation.

- [ ] **Step 6: Run migration and repository tests**

Run: `cd backend && alembic upgrade head && pytest tests/integration/persistence/test_live_session_repositories.py tests/unit/test_live_session_models.py -q`

Expected: PASS; existing `live_camera` rows remain readable.

---

### Task 4: MediaMTX Control API Client And Path Reconciliation

**Files:**
- Create: `backend/app/infrastructure/media/__init__.py`
- Create: `backend/app/infrastructure/media/mediamtx_client.py`
- Create: `backend/app/services/mediamtx_reconciliation_service.py`
- Test: `backend/tests/unit/test_mediamtx_client.py`
- Test: `backend/tests/unit/test_mediamtx_reconciliation_service.py`

**Interfaces:**
- Produces: `MediaMtxPathSpec`, `MediaMtxPathState`, `MediaMtxClient`.
- Produces: `MediaMtxReconciliationService.reconcile() -> ReconciliationResult`.

- [ ] **Step 1: Write failing HTTP contract tests with `httpx.MockTransport`**

```python
@pytest.mark.asyncio
async def test_add_pull_path_uses_exact_control_endpoint() -> None:
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client = MediaMtxClient(
        "http://mediamtx:9997",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    await client.add_path("ingress/abc", {"source": "rtsp://upstream/live"})
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v3/config/paths/add/ingress/abc"
```

Also test WHEP source preservation, publisher paths, 404 get/delete behavior,
timeouts, non-JSON errors, and URI redaction.

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend && pytest tests/unit/test_mediamtx_client.py tests/unit/test_mediamtx_reconciliation_service.py -q`

Expected: FAIL because media modules do not exist.

- [ ] **Step 3: Implement a narrow typed client**

```python
class MediaMtxClient:
    async def get_config_path(self, name: str) -> dict | None: ...
    async def add_path(self, name: str, config: dict) -> None: ...
    async def replace_path(self, name: str, config: dict) -> None: ...
    async def delete_path(self, name: str) -> None: ...
    async def get_active_path(self, name: str) -> dict | None: ...
```

Percent-encode path names safely while retaining MediaMTX's catch-all name
semantics. Use bounded connect/read/write/pool timeouts. Convert failures into
`MediaMtxError(code, status)` without response bodies or source URLs.

- [ ] **Step 4: Build exact desired configs**

```python
def ingress_config(source_type: str, source_url: str | None) -> dict:
    if source_type == "whipPush":
        return {"source": "publisher"}
    if source_type == "rtspPull":
        assert source_url is not None and source_url.startswith(("rtsp://", "rtsps://"))
        return {"source": source_url, "rtspTransport": "tcp"}
    if source_type == "whepPull":
        assert source_url is not None and source_url.startswith(("whep://", "wheps://"))
        return {"source": source_url}
    raise ValueError("LIVE_SOURCE_TYPE_UNSUPPORTED")
```

- [ ] **Step 5: Implement desired-state reconciliation**

For each nonterminal generation, decrypt the pull source only in memory, compare
safe normalized path configuration, add/replace as needed, query active path,
and update media state. Delete only paths under the configured opaque prefix
which have no desired generation and have passed grace.

Treat `GET /v3/paths/get/{name}` field `online=true` as current readiness.
Do not build new logic on deprecated `ready`/`readyTime` fields.

- [ ] **Step 6: Run focused tests**

Run: `cd backend && pytest tests/unit/test_mediamtx_client.py tests/unit/test_mediamtx_reconciliation_service.py -q`

Expected: PASS.

---

### Task 5: Session And Connector Services Plus Public Routes

**Files:**
- Create: `backend/app/presentation/schemas/live_connectors.py`
- Create: `backend/app/services/live_connector_service.py`
- Create: `backend/app/services/live_session_service.py`
- Create: `backend/app/presentation/routers/live_connectors.py`
- Create: `backend/app/presentation/routers/live_sessions.py`
- Modify: `backend/app/presentation/dependencies.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/contract/test_live_sessions_api.py`
- Test: `backend/tests/contract/test_live_connectors_api.py`
- Test: `backend/tests/unit/test_live_session_service.py`

**Interfaces:**
- Produces: `LiveSessionService.create/get/list/reconfigure/stop/capabilities`.
- Produces: `LiveConnectorService.create/get/list/delete`.
- Consumes compiler, repositories, cipher, and MediaMTX controller from Tasks 2-4.

- [ ] **Step 1: Write failing API contract tests**

```python
def test_create_whip_session_returns_waiting_publish_url(client) -> None:
    response = client.post(
        "/api/v1/live/sessions",
        headers={"X-API-Key": "test-key"},
        json={
            "schemaVersion": 1,
            "cameraId": "gate-1",
            "profile": "face-recognition-v1",
            "source": {"type": "whipPush"},
            "processing": {"mode": "recognize"},
            "json": {"persistFrames": True},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "WAITING_FOR_SOURCE"
    assert body["ingest"]["publishUrl"].endswith("/whip")
    assert "internal" not in response.text


def test_pull_session_never_echoes_source_url(client) -> None:
    secret = "rtsp://alice:secret@customer/live?token=hidden"
    response = client.post(
        "/api/v1/live/sessions",
        headers={"X-API-Key": "test-key"},
        json={
            "schemaVersion": 1,
            "cameraId": "gate-1",
            "profile": "face-recognition-v1",
            "source": {"type": "rtspPull", "url": secret},
            "processing": {"mode": "recognize"},
            "json": {"persistFrames": True},
        },
    )
    assert response.status_code == 201
    for forbidden in ("alice", "secret", "customer", "token="):
        assert forbidden not in response.text
```

- [ ] **Step 2: Run API tests and verify 404/import failure**

Run: `cd backend && pytest tests/contract/test_live_sessions_api.py tests/contract/test_live_connectors_api.py -q`

Expected: FAIL because routes do not exist.

- [ ] **Step 3: Implement connector registration**

Webhook safe config stores timeout, event allowlist, and auth type; URL and auth
secret are encrypted. Kafka safe config stores non-secret producer policy while
brokers/TLS/SASL values are encrypted. Responses expose connector ID, type,
name, enabled state, safe config, and timestamps only.

- [ ] **Step 4: Implement session creation transaction**

```text
validate request
resolve connector references
compile safe resolved spec
generate session ID, generation ID, and opaque ingress path
encrypt pull URL when present
persist session + generation 1 as ACCEPTED/provisioning
commit
provision MediaMTX path
set WAITING_FOR_SOURCE or STARTING based on active path
return safe response
```

If MediaMTX is temporarily unavailable after persistence, retain the desired
generation with media failure state for reconciliation; do not delete durable
intent or expose plaintext failure details.

- [ ] **Step 5: Implement stop and reconfigure**

Stop changes desired state idempotently. Reconfigure compiles generation `N+1`,
provisions its path, requests controlled stop for `N`, and never modifies `N`'s
spec or path in place.

- [ ] **Step 6: Wire dependencies and routers**

Add `live_sessions`, `live_connectors`, and `mediamtx_reconciler` to
`ServiceContainer`; expose dependency getters; include routers in `app.main`.
Apply `Depends(require_live_api_key)` at each new router level.

- [ ] **Step 7: Run service and contract tests**

Run: `cd backend && pytest tests/unit/test_live_session_service.py tests/contract/test_live_sessions_api.py tests/contract/test_live_connectors_api.py -q`

Expected: PASS.

---

### Task 6: Adapt Supervisor To Immutable Session Generations

**Files:**
- Modify: `backend/app/services/live_supervisor.py`
- Modify: `backend/app/infrastructure/live/protocol.py`
- Modify: `backend/pipeline/include/mvision/live_protocol.hpp`
- Modify: `backend/pipeline/src/live_protocol.cpp`
- Modify: `backend/tests/unit/test_live_supervisor.py`
- Modify: `backend/tests/unit/test_live_protocol.py`
- Modify: `backend/pipeline/tests/test_live_protocol.cpp`
- Test: `backend/tests/contract/test_live_protocol_parity.py`

**Interfaces:**
- Consumes: claimable `LiveSessionGeneration` and internal RTSP origin.
- Produces: generation-fenced `StartCommand` with compiled processing/output fields.

- [ ] **Step 1: Add failing supervisor tests**

Assert that the supervisor:

```python
assert start.uri == "rtsp://mediamtx:8554/ingress/opaque-generation"
assert start.header.session_id == SESSION_ID
assert start.header.generation == 3
assert start.sample_every_n == 2
assert start.recording_enabled is False
assert start.annotated_enabled is False
```

Also assert source plaintext is never passed to the native command and retry of
the same generation increments runtime attempt without changing generation.

- [ ] **Step 2: Run protocol/supervisor tests and verify failure**

Run: `cd backend && pytest tests/unit/test_live_supervisor.py tests/unit/test_live_protocol.py tests/contract/test_live_protocol_parity.py -q`

Expected: FAIL on missing session-generation fields.

- [ ] **Step 3: Extend protocol header and StartCommand symmetrically**

Use `session_id` as the public ownership key while retaining `run_id` for runtime
attempt fencing. Add only resolved safe fields required by the native graph:

```text
profile_version
analytics_mode
sample_every_n
detector_threshold
recognition_threshold
top2_margin
track_gap_ns
frame_timeout_ns
latency_ms
reconnect_interval_seconds
reconnect_attempts
annotated_enabled
```

Do not add remote source URL, connector destination, MediaMTX Control API URL, or
recording storage credentials.

- [ ] **Step 4: Replace camera claim in the new worker path**

Add `process_one_session(worker_id)` which claims a media-ready generation,
computes internal RTSP URL from configured origin plus opaque path, and starts
the child. Keep `process_one_camera()` temporarily for the legacy route until
new E2E acceptance passes.

- [ ] **Step 5: Enforce lease/generation fencing on every event**

Reject events whose session ID, run ID, generation, or runtime attempt does not
match the claim. Source reconnect changes runtime state, not generation.

- [ ] **Step 6: Run Python and native protocol tests**

Run: `cd backend && pytest tests/unit/test_live_supervisor.py tests/unit/test_live_protocol.py tests/contract/test_live_protocol_parity.py -q`

Run: `cmake --build build/pipeline -j"$(nproc)" && ./build/pipeline/test_live_protocol`

Expected: PASS.

---

### Task 7: Reconciliation Lifecycle And Real MediaMTX Acceptance

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/worker/live_worker_main.py`
- Modify: `docker-compose.live.yml`
- Create: `configs/mediamtx.yml`
- Create: `backend/tests/integration/media/test_mediamtx_live_sessions.py`
- Create: `backend/scripts/live_session_smoke.py`

**Interfaces:**
- Starts controller reconciliation on API lifecycle.
- Starts session-generation claims in live workers.
- Proves all three source variants against a real MediaMTX process.

- [ ] **Step 1: Add a minimal MediaMTX service**

Configure one deployment-level MediaMTX with internal Control API `:9997`, RTSP
`:8554`, WebRTC/WHIP `:8889`, and no static per-camera paths. Mount recording
storage but leave recording disabled by default. Expose only required public
RTSP/WebRTC ports; keep Control API internal.

- [ ] **Step 2: Start periodic reconciliation without blocking API startup**

Create one lifespan task with bounded interval and cancellation. Run one initial
reconciliation after dependencies are ready. A failed MediaMTX call records safe
state and retries; it does not crash image/video APIs.

- [ ] **Step 3: Switch live worker loop to session claims**

`run_worker()` calls `process_one_session()` for the new deployment. Keep legacy
camera processing behind an explicit temporary environment switch, defaulting to
the new path only after acceptance.

- [ ] **Step 4: Test RTSP pull**

Publish deterministic H.264 to an upstream MediaMTX path, create `rtspPull`, and
poll session state until `ACTIVE`. Verify the native worker input uses the local
MediaMTX path and the public response contains no source URL.

- [ ] **Step 5: Test WHEP pull**

Expose the same fixture through WHEP, create `whepPull`, and verify MediaMTX
bridges it to the same internal RTSP worker contract.

- [ ] **Step 6: Test WHIP push**

Create `whipPush`, assert `WAITING_FOR_SOURCE`, publish fixture video to returned
`/whip` URL, and poll until `ACTIVE` without restarting the worker or API.

- [ ] **Step 7: Test MediaMTX restart reconciliation**

Restart only MediaMTX, assert session leaves stale `ACTIVE`, and verify the path
is recreated and session returns to `ACTIVE` after source recovery.

- [ ] **Step 8: Run the complete Delivery 1 gate**

Run: `cd backend && pytest tests/unit/test_live_api_auth.py tests/unit/test_live_session_compiler.py tests/unit/test_mediamtx_client.py tests/unit/test_mediamtx_reconciliation_service.py tests/unit/test_live_session_service.py tests/contract/test_live_sessions_schema.py tests/contract/test_live_sessions_api.py tests/contract/test_live_connectors_api.py tests/contract/test_live_protocol_parity.py tests/integration/persistence/test_live_session_repositories.py tests/integration/media/test_mediamtx_live_sessions.py -q`

Run: `git diff --check`

Expected: all tests PASS; no secret appears in captured responses/logs.

---

## Self-Review Checklist

- [ ] Every source type reaches one internal RTSP worker contract.
- [ ] Every accepted request has a durable immutable generation before media work.
- [ ] Pull URLs and connector secrets are excluded from snapshots and hashes.
- [ ] Push publish URLs are the only caller-visible ingest URLs.
- [ ] Reconfigure creates generation `N+1`; runtime retry does not.
- [ ] MediaMTX restart restores desired paths from PostgreSQL.
- [ ] Existing enrollment, image recognition, video jobs, and legacy live data remain intact.
- [ ] No placeholder, arbitrary graph property, profile CRUD, scheduler, or OIDC work entered Delivery 1.
