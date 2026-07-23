# Optional Live Recording Design

**Status:** Approved direction
**Delivery:** 3 - Optional Media Outputs
**Revised:** 2026-07-23

## Goal

When requested by a live session, record the canonical unannotated MediaMTX
ingress as nominal 15-minute fMP4 segments. Recording is independent from frame
JSON, identity resolution, appearance aggregation, and annotated output.

The initial release provides durable segment inventory and playback/download
references. It does not require an exact per-video-sample sidecar or zero-frame
join between JSON and a recording.

## Topology

```text
caller RTSP/WHEP or WHIP publication
  -> Mvision MediaMTX ingress path
       -> internal RTSP -> DeepStream -> frame JSON
       -> MediaMTX fMP4 recorder
            -> segment-complete hook
                 -> recording ingestion
                      -> PostgreSQL segment row
                      -> persistent volume and optional MinIO object
```

The recorder stores source video before Mvision OSD. Annotated recording is not
part of this contract.

## Session Configuration

```json
{
  "recording": {
    "enabled": true,
    "format": "fmp4",
    "segmentDuration": "15m",
    "retention": "7d"
  }
}
```

Initial rules:

- `enabled` defaults to false;
- only `fmp4` is supported;
- production segment duration defaults to 15 minutes;
- test deployments may use shorter durations;
- duration and retention bounds are returned by capabilities;
- recording and annotated output can be enabled independently.

## MediaMTX Path Configuration

The Session Controller includes recording fields when provisioning the ingress
path:

```text
record: true
recordFormat: fmp4
recordPath: /recordings/{opaqueGenerationPath}/%Y-%m-%d_%H-%M-%S-%f
recordSegmentDuration: 15m
runOnRecordSegmentComplete: internal completion notifier
```

The exact property names are pinned to the deployed MediaMTX version and verified
against its Control API schema. Callers never submit this payload.

The recording root uses opaque IDs and never includes source credentials,
person names, camera display names, or locations.

## Segment Completion

MediaMTX invokes the internal completion notifier with path, segment path, and
actual duration. The notification is a hint and may be duplicated or missed.

The ingestion operation is idempotent:

1. Validate that the path belongs to a known session generation.
2. Resolve the segment path beneath the configured recording root.
3. Wait until MediaMTX has closed the file.
4. Probe codec, dimensions, actual start, duration, and decodability.
5. Compute size and SHA-256.
6. Create or update the PostgreSQL segment row.
7. Optionally upload the completed fMP4 to existing MinIO storage.
8. Mark the segment `READY` only after its selected durable storage target is
   complete.
9. Remove local staging only when retention policy and durable state allow it.

A periodic reconciliation scan processes completed files whose hook was missed
and repairs rows stuck in an intermediate state.

## Segment Model

`live_recording_segment` contains:

- segment ID;
- session ID and generation;
- camera ID and location snapshot;
- opaque MediaMTX ingress path ID;
- actual start/end UTC and duration;
- codec, width, height, and container;
- local persistent path or MinIO bucket/object key;
- byte size and checksum;
- `DISCOVERED`, `INGESTING`, `READY`, `FAILED`, or `DELETED` state;
- stable failure code;
- created, completed, finalized, and retention timestamps.

One session may have an open segment not yet visible as `READY`. The API never
returns a partially written file as complete.

## API

```text
GET /api/v1/live/sessions/{sessionId}/recordings
GET /api/v1/live/recordings/{segmentId}
GET /api/v1/live/recordings/{segmentId}/content
```

List response:

```json
{
  "sessionId": "uuid",
  "segments": [
    {
      "segmentId": "uuid",
      "generation": 2,
      "state": "READY",
      "start": "2026-07-23T10:00:00.000Z",
      "end": "2026-07-23T10:15:00.400Z",
      "durationSeconds": 900.4,
      "format": "fmp4",
      "codec": "h264",
      "width": 1920,
      "height": 1080,
      "sizeBytes": 481002331,
      "contentUrl": "/api/v1/live/recordings/uuid/content"
    }
  ],
  "nextCursor": null
}
```

The API reports actual segment times. It does not assume that every file is
exactly 900 seconds because keyframes, disconnects, or stop can close a segment
early or late.

## Relationship To Frame JSON

Frame JSON and recording share the same MediaMTX ingress path but have independent
lifecycle and storage.

The initial API may return overlapping recording segment IDs for a UTC query. It
does not claim an exact sample index for a frame result. Consumers must not infer
an exact frame from nominal FPS.

If exact recording-sample evidence becomes a product requirement, it is added as
a later versioned sidecar/index feature without changing the basic segment model.

## Failure Isolation

- Recording path provisioning failure marks recording failed and may leave JSON
  processing active according to session policy.
- A full staging disk rejects new recording work before overwriting completed
  evidence.
- A completion-hook failure is recoverable by reconciliation.
- MinIO outage retains completed staging files within disk policy and retries.
- A corrupt segment becomes `FAILED`; no valid-looking content URL is returned.
- Source reconnect may close the current segment early and start another.
- Session stop finalizes the open segment before path deletion when possible.
- Recording failure never changes face identity or frame JSON content.

## Retention

Retention is segment-manifest driven and idempotent:

1. mark the segment pending deletion;
2. remove selected durable object/file;
3. verify absence;
4. mark `DELETED` while retaining bounded business metadata.

Partially uploaded objects and orphan local files are reconciled by checksum and
segment state. Production volumes are never reset as a repair mechanism.

## Observability

Low-cardinality metrics include:

- recording state totals;
- open/completed/failed segment counts;
- actual segment duration and byte-size histograms;
- completion-to-ready latency;
- staging bytes and high-watermark state;
- ingestion, upload, checksum, and reconciliation outcomes by stable reason.

Session IDs, camera IDs, file paths, object keys, and timestamps are not metric
labels.

## Stable Errors

- `LIVE_RECORDING_FORMAT_UNSUPPORTED`;
- `LIVE_RECORDING_PATH_FAILED`;
- `LIVE_RECORDING_DISK_FULL`;
- `LIVE_RECORDING_SEGMENT_INVALID`;
- `LIVE_RECORDING_INGEST_FAILED`;
- `LIVE_RECORDING_STORAGE_UNAVAILABLE`;
- `LIVE_RECORDING_NOT_READY`;
- `LIVE_RECORDING_EXPIRED`.

## Acceptance

### Fast Gate

- use 15-second fMP4 segments with deterministic H.264 input;
- verify completion hook, duplicate hook, and missed-hook reconciliation;
- verify source reconnect and session stop create valid early segments;
- verify temporary storage failure retains recoverable staging;
- verify every `READY` segment checksum and decode;
- verify JSON continues during recording ingestion and failure.

### Production-Duration Gate

- run for at least 16 minutes with a real 15-minute segment duration;
- observe one natural rollover and at least two valid segment files;
- verify actual start/end/duration, checksums, API listing, and content access;
- restart MediaMTX and recording ingestion, then verify desired path and segment
  inventory recover;
- verify retention deletes only expired completed segments;
- verify no secret, name, face ID, embedding, or raw source URI enters a path,
  object key, manifest, metric label, or log.
