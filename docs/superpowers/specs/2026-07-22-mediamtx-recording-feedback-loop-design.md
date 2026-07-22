# MediaMTX Recording Feedback-Loop Design

**Status:** Superseded by `2026-07-22-mediamtx-recording-realtime-appearance-design.md`  
**Date:** 2026-07-22  
**Scope:** Record a provider RTSP feed inside Mvision and align detection JSON with exact recorded frames.

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

The provider serves one camera as a live RTSP stream. Its own recordings are not
an input to this contract. Mvision ingests the provider stream once, records it
in nominal 15-minute segments, and runs inference from the same canonical
ingest. A consumer must be able to apply Mvision's identity, score, landmark,
and bounding-box JSON to the exact Mvision recording frame, including after an
inference restart or an upstream reconnect.

The primary acceptance condition is an exact canonical-frame join, not merely
that wall clocks look close. A completed recording plus its matching JSON must
reproduce detections on the identical canonical source frame with no nearest-
frame guess and no bounding-box coordinate drift.

## 2. Locked Assumptions

- The provider contract contains only a live RTSP URL and source credentials.
- Provider-side recordings and recording metadata are not required.
- The team controls the complete Mvision ingest, recording, inference, and
  segment-inventory deployment.
- Both hosts can use a healthy NTP service.
- Mvision retains original recording paths, exact frame indexes, and manifests.
- Production segments are nominally 15 minutes; test segments may be shorter.
- MediaMTX records fMP4 unless a separate compatibility requirement selects
  MPEG-TS.
- The existing `LiveObservation.timestamp_ns = frame->buf_pts` value is not an
  absolute UTC timestamp and cannot be the sole alignment key.
- A local analyzer frame counter is diagnostic only. It is not assumed to equal
  a frame number produced by an independent recording decoder.
- Exact alignment uses Mvision's canonical frame identity. UTC is retained for
  audit and cross-system diagnosis, not used as a nearest-frame fallback.

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

## 4. Canonical Ingest And Recorder Contract

Mvision opens one upstream RTSP session and splits the parsed H.264 access-unit
stream before recording and decoding:

```text
provider RTSP
  -> RTP depay
  -> H.264 parse
  -> canonical access-unit identity
  -> tee
       -> recording mux/15-minute segment + exact frame sidecar
       -> decode/DeepStream/inference + detection JSON
```

The recording branch preserves the provider's encoded access units whenever
codec/container compatibility permits. Re-encoding is allowed only when
required and must still happen after canonical frame identity is assigned.

Each video access unit receives a stable identity composed of:

```text
canonical_frame_id = timing_epoch + extended_source_timestamp + access_unit_ordinal
```

The exact binary representation is selected during implementation, but it must
remain unique across RTP wraparound, duplicate PTS values, reconnects, and
process restarts. Both branches carry the same identity. The recorder writes an
exact sidecar entry for every muxed video sample and the inference branch emits
the identity with every detection.

Mvision controls segment rollover. A nominal 15-minute boundary may move to a
safe keyframe, and an upstream interruption may close a segment early. The
recorder's actual sample index and manifest are authoritative. NTP-synchronized
UTC and RTCP Sender Reports remain required for audit, latency, and operational
correlation, but exact overlay matching does not depend on wall-clock equality.

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
  "format": "fmp4",
  "timingEpoch": 7,
  "firstCanonicalFrameId": "7:88473312001:0",
  "lastCanonicalFrameId": "7:89823341999:0",
  "frameIndexPath": "recordings/camera-1/segment.frame-index.jsonl"
}
```

The segment is publishable only after the video, manifest, and exact frame index
are durably finalized. The inventory verifies that every indexed sample exists
in the recording, every canonical frame ID is unique, sample order is monotonic
within its timing epoch, and probed media duration agrees with the indexed
sample range. A recording without its manifest and exact frame index is not
considered alignable.

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
  "timingEpoch": 7,
  "canonicalFrameId": "7:88474249801:0",
  "sourceTimeUtc": "2026-07-22T14:30:10.420000Z",
  "streamPtsNs": 10420000000,
  "receivedAtUtc": "2026-07-22T14:30:10.511000Z",
  "timeBasis": "rtcp_ntp",
  "alignmentState": "exact_frame",
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

- `canonicalFrameId` is the only key used for exact recording-frame matching.
- `timingEpoch` changes whenever upstream timing continuity cannot be proven.
- `sourceTimeUtc` supports audit, cross-system correlation, and human queries.
- `streamPtsNs` supports ordering and diagnostics but is not global time.
- `receivedAtUtc - sourceTimeUtc` is ingest latency, not segment offset.
- `timeBasis` is `rtcp_ntp` when absolute source time is available. A missing
  RTCP mapping does not invalidate an otherwise exact canonical-frame join.
- `alignmentState=exact_frame` is allowed only after the finalized recorder
  index contains the event's canonical frame ID.
- Geometry is expressed in original stream pixels and carries source dimensions.
- Reconnects create a new analyzer generation but do not reset source UTC.

## 7. Exact Matching Algorithm

The finalized frame index is a unique map:

```text
canonical_frame_id -> segment_id, video_sample_index, sample_pts, sample_dts
```

The overlay consumer performs an exact key lookup. It decodes the indexed video
sample and applies all detections carrying that canonical frame ID. It never
chooses the closest timestamp, calculates a frame number from nominal FPS, or
uses wall-clock tolerance to hide a missing frame.

Segment ownership is decided by the recorder when the sample is muxed. An event
at a segment boundary therefore maps to exactly one segment and sample index;
there is no independently calculated boundary rule in the overlay consumer.

UTC half-open ranges remain in the manifest for API queries and audit:

```text
segment.start_utc <= event.source_time_utc < segment.end_utc_exclusive
```

They are a consistency check, not the frame join. If the exact index does not
contain the event's canonical frame ID, the event is marked `unaligned` with a
machine-readable reason. It is never attached to another frame.

## 8. Late Join And Reconnect Behavior

- Starting inference after recording has begun is valid because both branches
  retain canonical frame identity independent of inference start time.
- Missing RTCP/NTP mapping can delay absolute UTC publication but does not
  force an approximate frame match.
- An inference-only restart does not interrupt the recording branch.
- An upstream reconnect starts a new timing epoch and closes or fences the
  affected segment according to recorder policy.
- A new run/generation preserves fencing and identity semantics. Events on each
  side of an upstream reconnect resolve through their own timing epoch and
  recorder segment/index.
- RTCP mapping discontinuity, clock step, or excessive drift invalidates trusted
  source UTC until remapping, but cannot change an exact canonical-frame join.

## 9. Feedback-Loop Acceptance Harness

Production uses 15-minute segments. Automated acceptance uses 15-second
segments to exercise the same boundaries quickly.

The source fixture contains:

- a deterministic moving face or face fixture;
- a burned-in UTC timestamp and monotonically increasing source frame marker;
- deterministic ground-truth bounding boxes;
- stable H.264 cadence and periodic IDR frames.

Test sequence:

1. Start a local MediaMTX fixture that represents the provider's RTSP server.
2. Start Mvision's canonical ingest and recording branch.
3. Enable inference several seconds after recording starts and collect
   schema-v2 JSON.
4. Restart inference without stopping recording, then force an upstream RTSP
   disconnect/reconnect.
5. Continue through at least one recording boundary.
6. Wait for segment-completion manifests.
7. Resolve every event through the exact canonical-frame index.
8. Decode the exact indexed recording sample and render the JSON geometry.
9. Compare the result with fixture ground truth and burned-in source markers.

Strict acceptance:

- 100% of aligned events select the correct recording segment and sample index;
- selected canonical frame differs from ground truth by exactly zero frames;
- no cumulative offset growth over the full test window;
- bbox intersection-over-union meets the detector fixture threshold;
- landmark coordinates remain within source-pixel tolerance;
- late join does not rebase source UTC;
- reconnect does not create a persistent timing offset;
- events around a segment boundary select the correct side of the boundary;
- missing RTCP/NTP mapping is reported as degraded absolute-time quality but
  cannot cause a different canonical frame to be selected;
- recording restart or early segment closure uses manifest duration correctly.

The acceptance artifact includes segment manifests, JSON, overlay video, raw
timing deltas, frame-error distribution, bbox IoU distribution, configuration
hashes, and software versions. It contains no embeddings.

## 10. Failure And Recovery Policy

| Condition | Required behavior |
|---|---|
| NTP unhealthy or host offset exceeds policy | Degrade absolute-time quality; preserve exact frame identity |
| RTCP Sender Report not observed yet | Omit trusted source UTC; never substitute receive UTC |
| Source timestamp jumps | Close/fence the current segment and start a new timing epoch |
| Segment finalization delayed | Retain event pending exact index publication |
| Canonical frame absent from finalized index | Keep event unresolved with `canonical_frame_not_recorded` |
| Duplicate canonical frame ID | Fail segment publication and raise an integrity error |
| Recording missing manifest/index | Mark recording metadata insufficient |
| Variable frame rate | Use exact sample index; do not infer frame from nominal FPS |

## 11. Observability

Required low-cardinality metrics include:

- aligned and unaligned event counts by enum reason;
- RTCP mapping age and absolute-time quality histograms;
- exact frame-index join success/failure counts;
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

1. provider-like MediaMTX RTSP fixture profile;
2. single canonical ingest with recording and inference branches;
3. collision-safe canonical access-unit/frame identity propagation;
4. exact per-segment frame index and immutable manifest persistence;
5. RTCP/NTP source-time extraction for audit and correlation;
6. schema-v2 protocol, persistence, and API migration;
7. exact-index recording overlay resolver;
8. deterministic late-inference/reconnect/boundary acceptance harness;
9. deployment clock/integrity health checks and operational runbook.
