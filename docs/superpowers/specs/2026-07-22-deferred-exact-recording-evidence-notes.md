# Deferred Exact Recording Evidence Notes

**Status:** Deferred, not a current roadmap prerequisite
**Revised:** 2026-07-23

## Trigger

Implement this work only if a consumer must map a frame JSON event to one exact
sample in a retained recording with zero-frame ambiguity. Normal live frame JSON,
appearance summaries, 15-minute recording, and annotated output do not require
it.

## Why It Is Deferred

The approved initial product needs:

- bbox/landmark JSON for every processed frame;
- optional first/last/duration summaries;
- independent 15-minute recordings;
- optional annotated viewing.

An RTCP-NTP clock model, canonical access-unit identity, immutable per-sample
sidecar, MP4 sample-table parser, and exact evidence resolver add significant
complexity without being necessary for those outputs.

## Future Contract Seam

If activated, add a versioned optional frame reference:

```json
{
  "recordingEvidence": {
    "state": "exact",
    "segmentId": "uuid",
    "sampleIndex": 1842,
    "canonicalFrameId": "epoch:source-time:ordinal"
  }
}
```

The feature must preserve separate values for source UTC, stream PTS, Mvision
observed UTC, timing epoch, and exact source media time. It must never find a
recording frame by nominal FPS or nearest wall-clock timestamp while claiming an
exact match.

## Required Future Evidence

- canonical identity assigned before recording/inference split;
- same identity propagated to frame JSON and recording sample index;
- collision handling for reconnect, timestamp wrap, and duplicate timestamps;
- immutable sidecar checksum and segment manifest;
- zero-frame fixture validation across late join, restart, reconnect, and segment
  rollover;
- no fallback from missing exact evidence to an approximate match.

This work is independent from OpenTelemetry completion and is not blocked on or
made mandatory by the observability roadmap.
