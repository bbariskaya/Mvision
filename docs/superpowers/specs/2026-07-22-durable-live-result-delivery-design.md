# Durable Live Result Delivery Design

**Status:** Draft for user review  
**Phase:** Live Analytics Platform Phase 4

## Goal

Expose durable live analytics through pull APIs and deliver selected event types
to registered Webhook and Kafka connectors without making connector availability
part of media-processing correctness.

## Delivery Guarantees

- PostgreSQL domain rows and outbox rows are authoritative.
- External delivery is at-least-once.
- Every event has a globally stable event ID for consumer deduplication.
- Ordering is preserved per session generation by a stable ordering key and
  monotonically increasing sequence.
- No claim of end-to-end exactly-once delivery is made across arbitrary consumer
  systems.
- Connector failure never rolls back a committed appearance or stops inference.

## Event Types

Initial versioned types:

```text
live.session.accepted
live.session.active
live.session.degraded
live.session.failed
live.session.stopped
live.appearance.started
live.appearance.updated
live.appearance.ended
live.detection.observed          # optional high-volume mode
live.identity.new_anonymous
live.identity.became_known
live.recording.ready
live.recording.failed
live.annotated_output.ready
live.annotated_output.failed
```

Appearance `updated` delivery is coalesced by policy and never emitted per frame.
Per-frame detections require explicit SessionSpec selection and independent
retention/backpressure limits.

## Canonical Event Envelope

```json
{
  "eventId": "uuid-v7",
  "eventType": "live.appearance.ended",
  "schemaVersion": 1,
  "occurredAtUtc": "2026-07-22T14:42:05.100Z",
  "persistedAtUtc": "2026-07-22T14:42:05.140Z",
  "orderingKey": "session-uuid:4",
  "sequence": 381,
  "sessionId": "uuid",
  "generation": 4,
  "specHash": "sha256",
  "cameraSourceId": "uuid",
  "location": {
    "locationId": "uuid",
    "siteId": "office-a",
    "areaId": "entrance"
  },
  "subject": {
    "faceId": "uuid",
    "status": "known",
    "name": "Baris"
  },
  "data": {
    "appearanceId": "uuid",
    "startUtc": "2026-07-22T14:30:10.420Z",
    "endUtc": "2026-07-22T14:42:05.100Z",
    "durationSeconds": 713.68,
    "evidenceState": "exact"
  }
}
```

Names/metadata are included only when connector policy permits them. Embeddings,
source credentials, internal paths, and raw exceptions are never included.

## Outbox Model

Domain mutation and outbox creation happen in one PostgreSQL transaction.

`live_result_outbox` contains:

- event ID/type/schema version;
- ordering key and sequence;
- canonical safe payload;
- domain aggregate reference;
- created/available timestamps;
- retention/replay metadata.

`live_delivery_attempt` contains one row per event/connector target:

- connector ID and immutable connector version;
- state: `PENDING|LEASED|DELIVERED|RETRY_WAIT|TERMINAL_FAILED|CANCELLED`;
- attempt count and next attempt UTC;
- lease owner/expiry;
- safe status/failure code;
- first/last attempt and delivered timestamps;
- destination acknowledgement metadata without response body/secrets.

Workers claim attempts with bounded batches, leases, and `SKIP LOCKED`. A lease
expiry makes an attempt eligible again, preserving at-least-once semantics.

## Pull APIs

```text
GET /v1/live/sessions/{sessionId}/events
GET /v1/live/sessions/{sessionId}/appearances
GET /v1/live/sessions/{sessionId}/detections
GET /v1/live/faces/{faceId}/appearances
GET /v1/live/locations/{locationId}/appearances
GET /v1/live/connectors/{connectorId}/deliveries
GET /v1/live/deliveries/{eventId}
POST /v1/live/deliveries/{eventId}/replay
```

Queries use cursor pagination, UTC half-open ranges, caller scope, and bounded
page sizes. Detection payloads are not joined into appearance lists by default.

## Webhook Connector

Registered configuration includes HTTPS origin/path policy, authentication type,
encrypted secret reference, event allowlist, timeout, retry policy, and optional
custom non-secret headers.

Request:

- method `POST`;
- canonical JSON body;
- `Content-Type: application/json`;
- event ID, type, schema, timestamp, and delivery-attempt headers;
- HMAC signature over timestamp plus exact body when HMAC auth is selected;
- bounded connect/read/write timeout and body size.

Success is any configured 2xx response. Timeout, connection failure, 408, 429,
and 5xx are retryable. Other 4xx responses are terminal unless connector policy
explicitly lists them. Redirects are disabled by default; response bodies are not
persisted or logged.

Webhook URLs pass registration-time and send-time SSRF controls: HTTPS policy,
DNS/IP allowlist, private/link-local/metadata-address restrictions, and rebinding
protection.

## Kafka Connector

Registered configuration includes broker set, topic, optional DLQ topic,
TLS/SASL secret references, event allowlist, compression, batching, and timeout.

Producer contract:

- key is `orderingKey`, ensuring one session generation maps to one partition;
- event ID/type/schema are headers and also remain in the envelope;
- `enable.idempotence=true`;
- `acks=all`;
- retries enabled;
- `max.in.flight.requests.per.connection <= 5`;
- bounded delivery timeout and request size;
- safe producer client ID contains no caller/person data.

Kafka idempotence reduces duplicate broker writes. Application-level outbox
recovery can still resend after an uncertain acknowledgement, so consumers must
deduplicate by event ID. Kafka provides partition ordering; application DLQ
topic behavior is implemented by Mvision policy, not assumed automatically.

## Retry And Dead-Letter Policy

Exponential backoff with jitter is bounded by connector policy. Retry state is
durable and survives worker restart.

On maximum attempts or terminal error:

- attempt becomes `TERMINAL_FAILED`;
- domain result remains committed;
- operator can inspect safe failure code and replay;
- Kafka connector may publish a safe failure envelope to its registered DLQ;
- Webhook failures remain queryable and replayable through Mvision.

Replay creates a new attempt for the same event ID and connector version or an
explicit newly selected connector version. It never duplicates the domain row.

## Backpressure

- Outbox and per-connector pending counts are bounded by quotas/alerts.
- Appearance lifecycle events are never dropped after acceptance.
- Detection events may be sampled/coalesced/rejected according to declared
  SessionSpec policy before outbox insertion.
- A saturated connector does not block another connector.
- Delivery workers use separate resource pools from live inference workers.

## Connector Lifecycle

Connectors are versioned. Secret rotation creates a new secret/config version.
Existing delivery attempts retain their target version unless explicitly
replayed to a newer one. Disablement prevents new attempts and leaves historical
delivery evidence intact.

## Observability

Metrics use bounded connector type/state/error enums, never connector IDs,
topics, URLs, event IDs, session IDs, or face IDs. Traces cover claim, serialize,
send, acknowledge, retry scheduling, and terminal transition without payloads.

## Acceptance

- domain row and outbox row commit atomically;
- rollback produces neither;
- pull APIs return committed results while connectors are offline;
- webhook signature fixture verifies exact body and timestamp;
- SSRF targets and redirects are rejected;
- webhook timeout/429/5xx retry; configured 2xx succeeds; terminal 4xx stops;
- Kafka messages use session-generation key and preserve partition order;
- Kafka producer settings satisfy idempotence/acks/in-flight contract;
- simulated uncertain acknowledgement may duplicate delivery but retains one
  event ID;
- consumer fixture deduplicates by event ID;
- worker crash after send/before acknowledgement safely retries;
- connector outage does not change camera state, FPS, recording, or appearance;
- terminal failure and replay survive restart;
- secrets and response bodies never enter logs, traces, metrics, or APIs;
- high-volume detection policy cannot starve appearance lifecycle events.
