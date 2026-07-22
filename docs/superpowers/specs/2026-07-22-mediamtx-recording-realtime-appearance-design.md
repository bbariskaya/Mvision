# MediaMTX Recording And Realtime Appearance Design

**Status:** Draft for user review  
**Phase:** Live Analytics Platform Phase 3
**Supersedes:** `2026-07-22-mediamtx-recording-feedback-loop-design.md`

## Goal

Produce durable realtime person appearance histories and independently retain
15-minute timestamped recordings that can prove exact source samples. Recording
and annotated video are not the primary product result.

## Architecture

```text
External RTSP
  -> generation-scoped MediaMTX ingress
       -> relayed RTSP -> live GPU worker -> identity/appearance
       -> fMP4 recorder -> completion hook -> ingestion worker
                                           -> MinIO video/index
                                           -> PostgreSQL manifest/evidence
```

The Session Controller provisions and removes MediaMTX paths through its
internal-only Control API. MediaMTX opens the upstream source once. The GPU
worker consumes the credential-free internal relay.

## MediaMTX Path Contract

Each generation receives an unguessable internal path. Configuration includes:

- source URL and credentials from encrypted source state;
- `useAbsoluteTimestamp: true`;
- recording according to SessionSpec;
- `fmp4` format;
- 15-minute production segment duration;
- bounded part size and staging retention;
- internal segment-completion hook.

MediaMTX Control and Playback APIs bind only the internal network. Source URLs
must not appear in API audit payloads or logs.

## Time Contract

MediaMTX routes RTSP absolute timestamps through RTCP sender reports. The worker
must prove that installed GStreamer/DeepStream exposes this reference mapping.

Each retained observation contains:

```text
source_time_utc
source_media_time_numerator / denominator
source_timestamp_ordinal
stream_pts_ns
received_at_utc
time_basis
time_quality
timing_epoch
```

Floating-point timestamps are forbidden as exact keys. Reconnect or unproven
timestamp continuity increments the timing epoch.

Exact evidence key:

```text
timing_epoch + normalized source media time + duplicate-time ordinal
```

Absolute UTC supports human/audit queries. Exact matching occurs in the rational
media timescale.

## Segment Completion And Ingestion

The hook is an idempotent notification, not proof that durable ingestion is
complete.

Ingestion steps:

1. Validate generation, MediaMTX path, staging root, and completed-file state.
2. Query Playback API timespans for authoritative segment start and duration.
3. Parse the fMP4 ISO-BMFF sample table.
4. Enumerate exact video sample index, PTS, DTS, duration, timescale, keyframe,
   normalized source time, and duplicate-time ordinal.
5. Validate monotonicity, uniqueness, media duration, and decodability.
6. Compute video and index SHA-256 values.
7. Upload the video and compressed immutable index to MinIO.
8. Finalize the PostgreSQL manifest and pending evidence links transactionally.
9. Delete staging data only after durable readiness and retention policy allow.

## Storage Model

PostgreSQL `live_recording_segment` stores:

- segment/session/generation/source IDs;
- location snapshot and timing epoch;
- start/end UTC and duration;
- media timescale and sample count;
- MinIO video/index object keys and checksums;
- state and stable failure code;
- created/finalized timestamps.

MinIO owns:

```text
live-recordings/{sessionId}/{generation}/{segmentId}/video.mp4
live-recordings/{sessionId}/{generation}/{segmentId}/sample-index.zst
```

Dynamic names, people, credentials, and raw source URIs never enter object keys.

## Realtime Appearance Aggregation

An appearance is keyed by global face identity, source, location snapshot,
session generation, timing epoch, local track, and logical identity epoch.

State:

```text
PENDING_IDENTITY -> OPEN -> CLOSED
```

- Late confirmation backdates to the earliest trusted quality-gated observation.
- Track expiry, confirmed identity switch, session stop, or timing discontinuity
  closes the raw interval.
- Segment rollover does not close it.
- Raw intervals are immutable after closure.
- Query-only presentation merging uses the configured gap and preserves raw data.
- Total duration sums raw intervals and excludes gaps.

## Global Anonymous Identity

The live matcher searches active known and anonymous gallery samples. Existing
identity wins must satisfy absolute threshold, top-2 margin, support, and quality
policy.

New anonymous creation requires:

- temporally diverse minimum evidence;
- sufficient dwell and quality;
- no accepted gallery match;
- final gallery recheck under identity-level fencing;
- successful PostgreSQL identity/sample state;
- successful MinIO sample upload;
- successful Qdrant vector upsert;
- activation only after all required storage steps pass.

The first result snapshot is `new_anonymous`; later results are `anonymous`.
Enrollment preserves `faceId`.

## Evidence Resolution

Realtime intervals exist independently from finalized recordings. Their start
and end evidence begin `pending`.

When a segment becomes ready, the resolver performs exact key lookup and stores:

- segment ID;
- exact video sample index;
- sample PTS/DTS;
- index checksum/version.

Success becomes `exact`. Failure becomes `unaligned` with a stable reason such as
`timing_untrusted`, `segment_missing`, `sample_not_found`, or `index_invalid`.
Nearest-frame fallback is forbidden.

## Recovery And Reconciliation

- duplicate completion hooks are idempotent;
- a periodic reconciler discovers missed hooks;
- MinIO outage retains local staging and retries within disk policy;
- partial/orphan uploads are reconciled by manifest state and checksum;
- timestamp drift closes/fences the segment and starts a new timing epoch;
- worker restart never stops recording and never invents uncertain duration;
- disk high-watermark rejects new recording work without overwriting evidence.

## API Results

Primary endpoints return appearance intervals and total durations. Recording
endpoints return segment/evidence metadata and bounded download access. Per-frame
detections are separately paginated and retained according to SessionSpec.

## Fast Acceptance

Use a provider-like MediaMTX fixture and 15-second segments. The H.264 fixture
contains burned source UTC, monotonic frame markers, deterministic boxes, known
and new-anonymous people, entry/exit/re-entry, overlap, no-face periods, and IDR
frames.

Exercise:

- late inference join;
- inference restart while recording continues;
- upstream disconnect/reconnect;
- segment boundary;
- duplicate hook;
- temporary MinIO failure;
- exact evidence resolution.

## Production-Duration Acceptance

Run the same contract for at least 16 minutes with real 15-minute segments and
observe one natural rollover plus two finalized segment artifacts.

PASS requires:

- correct known and global-anonymous face IDs;
- correct first/last UTC and interval totals;
- no absent time included in duration;
- no segment-boundary interval split;
- correct timing-epoch fencing;
- correct segment and exact sample index for every aligned event;
- zero-frame difference against burned fixture marker;
- idempotent hook/retry behavior;
- durable video/index/manifest after restart;
- no secret, embedding, name, or image data in metrics/manifests/index keys;
- no annotated video dependency for JSON/appearance correctness.
