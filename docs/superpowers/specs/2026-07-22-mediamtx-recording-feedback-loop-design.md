# MediaMTX Recording Feedback-Loop Design

**Status:** Approved future-phase design; observability prerequisite not started  
**Date:** 2026-07-22  
**Scope:** Align live RTSP detection JSON with MediaMTX recordings at frame-level accuracy.

## 0. Phase Order And Prerequisite

This is not the next implementation phase. The required phase order is:

1. complete OpenTelemetry and LGTM observability;
2. then implement the MediaMTX recording feedback loop described here.

The prerequisite is governed by
`docs/superpowers/specs/2026-07-21-opentelemetry-observability-design.md` and
includes Python OpenTelemetry logs and traces, low-cardinality metrics,
Collector Contrib, Prometheus, Loki, Tempo, Grafana provisioning and
correlation, telemetry privacy/cardinality, fault isolation, retention, and
enabled-versus-disabled overhead acceptance.

MediaMTX implementation planning must not begin until that observability phase
has passed its applicable acceptance gates. The feedback-loop phase then reuses
the established telemetry pipeline for clock health, RTCP mapping quality,
manifest delivery, alignment failures, and acceptance evidence.

## 1. Objective

MediaMTX serves one camera as a live RTSP stream and records the same stream in
nominal 15-minute segments. Mvision consumes the live RTSP stream and produces
identity, score, landmark, and bounding-box JSON. A consumer must be able to
apply that JSON to the corresponding recorded segment and render every result
on the same source frame, including when Mvision connects late or reconnects.

The primary acceptance condition is not merely that wall clocks look close. A
completed recording plus its matching JSON must reproduce the live detections
within one decoded frame of the source and without bounding-box coordinate
drift.

## 2. Locked Assumptions

- The team controls the MediaMTX and Mvision deployments.
- Both hosts can use a healthy NTP service.
- MediaMTX can expose its Playback API and recording-completion hook.
- Original recording paths and segment manifests are retained.
- Production segments are nominally 15 minutes; test segments may be shorter.
- MediaMTX records fMP4 unless a separate compatibility requirement selects
  MPEG-TS.
- The existing `LiveObservation.timestamp_ns = frame->buf_pts` value is not an
  absolute UTC timestamp and cannot be the sole alignment key.
- A local analyzer frame counter is diagnostic only. It is not assumed to equal
  a frame number produced by an independent recording decoder.
- If an absolute source-time mapping is unavailable or untrusted, Mvision does
  not guess a segment or offset.

## 3. Time Domains

The implementation must keep these values separate:

| Value | Meaning | Alignment role |
|---|---|---|
| RTP timestamp | Codec clock value carried by RTP; H.264 commonly uses 90 kHz | Input to RTCP mapping |
| RTCP NTP time | Absolute reference paired with an RTP timestamp in Sender Reports | Authoritative source UTC basis |
| Stream PTS | Presentation time exposed by GStreamer, represented in nanoseconds | Ordering and diagnostics |
| Receive UTC | Time the analyzer received/processed the frame | Latency diagnostics only |
| Segment start UTC | Absolute start represented by the MediaMTX recording inventory | Segment selection and offset |

The authoritative frame time is derived from MediaMTX's RTCP Sender Report
mapping, conceptually:

```text
source_time_utc = reference_ntp_utc
                + (frame_rtp_timestamp - reference_rtp_timestamp) / clock_rate
```

The implementation may use GStreamer reference-timestamp metadata or an
equivalent RTCP-aware mechanism, but it must prove that the resulting value is
source UTC. Calling `system_clock::now()` when a decoded frame reaches the
analyzer is not an acceptable substitute.

## 4. MediaMTX Contract

The production configuration uses the MediaMTX host clock as the absolute time
authority for the routed stream. Both MediaMTX and Mvision hosts must be NTP
synced.

```yaml
pathDefaults:
  record: yes
  recordFormat: fmp4
  recordPartDuration: 1s
  recordSegmentDuration: 15m
  recordPath: ./recordings/%path/%Y-%m-%dT%H-%M-%S-%f%z
  useAbsoluteTimestamp: false
```

`recordSegmentDuration` is a minimum duration and segment closure can follow a
keyframe or happen early when a publisher stops. The recorded manifest, not the
configured nominal duration, is authoritative.

The deployment enables:

- MediaMTX Playback `/list` access for recording timespans;
- `runOnRecordSegmentComplete` delivery of `MTX_PATH`, `MTX_SEGMENT_PATH`, and
  `MTX_SEGMENT_DURATION` to the segment inventory service;
- retention of the original timestamp-bearing recording path;
- clock-health monitoring on the MediaMTX and Mvision hosts.

`useAbsoluteTimestamp=false` is intentional. MediaMTX replaces potentially
untrusted publisher absolute timestamps with its synchronized host time and
routes the RTP-to-NTP relation to RTSP readers. If a future camera-time use case
requires `useAbsoluteTimestamp=true`, camera clock quality becomes an explicit
deployment gate and requires a separate calibration run.

## 5. Segment Manifest

Each completed segment produces an immutable manifest:

```json
{
  "schemaVersion": 1,
  "segmentId": "camera-1:2026-07-22T14:30:00.000000Z",
  "streamPath": "camera-1",
  "recordingPath": "recordings/camera-1/2026-07-22T14-30-00-000000+0000.mp4",
  "startUtc": "2026-07-22T14:30:00.000000Z",
  "durationNs": 900033333333,
  "endUtcExclusive": "2026-07-22T14:45:00.033333333Z",
  "format": "fmp4"
}
```

The segment inventory validates that path-derived start time, Playback API
timespan, hook duration, and probed media duration are mutually consistent
within a configured frame-sized tolerance. A renamed recording without its
manifest or original timestamp-bearing path is not considered alignable.

## 6. Detection JSON Contract

The next phase replaces ambiguous live timestamps with an explicit source-time
contract. Field names can be adapted to the final API envelope, but their
semantics are fixed.

```json
{
  "schemaVersion": 2,
  "cameraId": "camera-1",
  "runId": "019f...",
  "generation": 3,
  "sourceTimeUtc": "2026-07-22T14:30:10.420000Z",
  "streamPtsNs": 10420000000,
  "receivedAtUtc": "2026-07-22T14:30:10.511000Z",
  "timeBasis": "rtcp_ntp",
  "timeUncertaintyNs": 16666667,
  "alignmentState": "aligned",
  "trackId": "42",
  "identityEpoch": 1,
  "identityState": "known",
  "faceId": "019f...",
  "name": "Baris",
  "cosine": 0.742,
  "detectorConfidence": 0.913,
  "frameWidth": 640,
  "frameHeight": 480,
  "bbox": {"x": 390.0, "y": 96.0, "width": 130.0, "height": 195.0},
  "landmarks": [
    {"x": 431.0, "y": 151.0},
    {"x": 476.0, "y": 152.0},
    {"x": 454.0, "y": 177.0},
    {"x": 438.0, "y": 205.0},
    {"x": 474.0, "y": 205.0}
  ]
}
```

Rules:

- `sourceTimeUtc` is the only event time used for segment selection.
- `streamPtsNs` supports ordering and diagnostics but is not global time.
- `receivedAtUtc - sourceTimeUtc` is ingest latency, not segment offset.
- `timeBasis` is `rtcp_ntp` for an aligned event; receive-clock fallbacks must
  use a different value and cannot claim `alignmentState=aligned`.
- `timeUncertaintyNs` records the known timestamp uncertainty and must not
  exceed one source-frame duration for strict acceptance.
- Geometry is expressed in original stream pixels and carries source dimensions.
- Reconnects create a new analyzer generation but do not reset source UTC.

## 7. Matching Algorithm

Segments use half-open intervals:

```text
segment.start_utc <= event.source_time_utc < segment.end_utc_exclusive
```

For the selected segment:

```text
segment_offset_ns = event.source_time_utc - segment.start_utc
```

The overlay consumer seeks using media timestamps and chooses the closest
decoded frame within the declared uncertainty. It must not calculate a frame
number as `offset * nominal_fps` for variable-frame-rate content. Events at an
exact boundary belong to the segment starting at that boundary.

If no segment contains the event, multiple manifests overlap, timestamp
uncertainty exceeds policy, or clocks fail health checks, the event is marked
`unaligned` with a machine-readable reason. It is not silently attached to the
nearest segment.

## 8. Late Join And Reconnect Behavior

- Connecting after a recording has started is valid because the frame carries
  source UTC independent of analyzer start time.
- The first event after connection remains pending until a valid RTCP/NTP
  mapping exists.
- Reconnect may reset local PTS or tracker state. It must not reset source UTC.
- A new run/generation preserves fencing and identity semantics while allowing
  events before and after reconnect to map into one recording segment.
- RTCP mapping discontinuity, clock step, or excessive drift invalidates
  alignment until a stable reference is re-established.

## 9. Feedback-Loop Acceptance Harness

Production uses 15-minute segments. Automated acceptance uses 15-second
segments to exercise the same boundaries quickly.

The source fixture contains:

- a deterministic moving face or face fixture;
- a burned-in UTC timestamp and monotonically increasing source frame marker;
- deterministic ground-truth bounding boxes;
- stable H.264 cadence and periodic IDR frames.

Test sequence:

1. Start NTP-synchronized MediaMTX with recording, Playback API, and completion
   hook enabled.
2. Publish the deterministic fixture before Mvision connects.
3. Connect Mvision several seconds late and collect schema-v2 JSON.
4. Force an RTSP disconnect/reconnect inside a segment.
5. Continue through at least one recording boundary.
6. Wait for segment-completion manifests.
7. Resolve every aligned event to a segment and media offset.
8. Decode the selected recording frame and render the JSON geometry.
9. Compare the result with fixture ground truth and burned-in source markers.

Strict acceptance:

- 100% of aligned events select the correct recording segment;
- selected frame differs from ground truth by at most one decoded source frame;
- no cumulative offset growth over the full test window;
- bbox intersection-over-union meets the detector fixture threshold;
- landmark coordinates remain within source-pixel tolerance;
- late join does not rebase source UTC;
- reconnect does not create a persistent timing offset;
- events around a segment boundary select the correct side of the boundary;
- missing RTCP/NTP mapping produces `unaligned`, never a guessed alignment;
- recording restart or early segment closure uses manifest duration correctly.

The acceptance artifact includes segment manifests, JSON, overlay video, raw
timing deltas, frame-error distribution, bbox IoU distribution, configuration
hashes, and software versions. It contains no embeddings.

## 10. Failure And Recovery Policy

| Condition | Required behavior |
|---|---|
| NTP unhealthy or host offset exceeds policy | Stop claiming aligned output |
| RTCP Sender Report not observed yet | Buffer bounded pending metadata or emit unaligned; do not use receive UTC as source UTC |
| Source timestamp jumps | Start a new timing epoch and require stable remapping |
| Segment hook delayed | Retain event; resolve after manifest arrives |
| Segment missing | Keep event unresolved with `segment_not_found` |
| Overlapping manifests | Reject automatic selection with `segment_overlap` |
| Recording renamed without manifest | Mark recording metadata insufficient |
| Variable frame rate | Seek by media timestamp; do not infer frame from nominal FPS |

## 11. Observability

Required low-cardinality metrics include:

- aligned and unaligned event counts by enum reason;
- RTCP mapping age and uncertainty histograms;
- MediaMTX-to-Mvision clock-offset health;
- manifest delivery delay;
- segment match latency;
- frame-alignment error distribution from acceptance runs;
- reconnect and timing-epoch reset counts.

Camera IDs, person names, face IDs, recording paths, raw timestamps, images,
landmarks, and embeddings must not become metric labels.

## 12. Scope Boundaries

This design does not implement:

- multi-camera clock correlation;
- cross-camera identity tracking;
- modification of recorded video content;
- camera-origin absolute time with unsynchronized camera clocks;
- alignment based only on receive time, file modification time, or nominal FPS;
- embedding or image data in segment manifests.

## 13. Next-Phase Deliverables

After the observability prerequisite passes, the MediaMTX implementation plan
must cover:

1. MediaMTX recording/playback/hook test profile;
2. segment inventory and immutable manifest persistence;
3. RTCP/NTP source-time extraction in the native live pipeline;
4. schema-v2 protocol, persistence, and API migration;
5. timestamp quality and failure-state handling;
6. recording overlay resolver;
7. deterministic late-join/reconnect/boundary acceptance harness;
8. deployment clock-health checks and operational runbook.
