# Live Per-Frame Recognition Design

## Status

Approved by the user on 2026-07-22. This design supersedes only the immutable
live-label and fixed OSD cosine behavior in
`2026-07-21-single-camera-livestream-design.md`. Durable event deduplication,
quality gates, absolute threshold, top-2 margin, and tracker expiry remain.

## Problem

The live pipeline runs detector and ArcFace inference on every frame because
`sample_every_n` is 1. Detector confidence therefore changes per frame. The OSD
cosine does not: Python caches the first accepted `IdentityAssignment`, and
`LiveOsdState` renders that assignment's decision-time score forever.

This is misleading. Closing an eye, changing pose, or partially occluding the
face must change the displayed cosine. A wrong first label must also not remain
attached to a reused or drifting tracker until expiry.

## Required Behavior

- Render the cosine between the current frame's ArcFace embedding and the
  currently assigned identity reference embedding on every eligible frame.
- Use three-frame hysteresis for label state:
  - three consecutive scores at or above the recognition threshold show the
    assigned name;
  - three consecutive scores below the threshold show `Unknown`;
  - an isolated contrary frame does not change the label.
- Continue gallery re-evaluation every five eligible frames.
- A different named candidate may replace the current identity only after
  three consecutive five-frame evaluations pass both the absolute threshold
  and top-2 margin.
- Track expiry clears the label, reference embedding, score, and all streaks.
- Do not persist or notify on per-frame score changes. Durable events represent
  identity transitions, not display telemetry.

## Architecture

### Python Control Plane

`LiveIdentityService` continues to own named-gallery matching, threshold,
top-2 margin, logical identity epochs, and sustained candidate switching.

The first-decision `LiveEventService._assignments` cache is removed. Durable
deduplication remains the responsibility of the database unique key and event
cooldowns; neither mechanism may be used as an OSD score source. Identity
transition state lives in `LiveIdentityService`, where it can be reevaluated.

When a named candidate is accepted, Python retrieves the matched sample through
the existing `QdrantAdapter.get(sample_id)` call. The returned 512-float vector
is validated as finite, normalized, and exactly 512 dimensions before use.

`IdentityAssignment` gains an optional `reference_embedding`. Known
assignments require it; Unknown reset assignments omit it. Python sends a fresh
assignment when the identity changes or a new epoch starts. Per-frame scores do
not travel back through PostgreSQL or Qdrant.

Gallery re-evaluation consumes one quality-gated observation every five
eligible frames per tracker. It maintains a candidate face ID and consecutive
win count. Three wins switch identity. Three evaluations without an acceptable
candidate reset the track to Unknown. A later three-win candidate can assign a
name again on the same native tracker through a higher logical epoch.

### Framed Protocol

The Python and C++ MessagePack codecs add `reference_embedding` to
`identity_assignment`. Validation rules are identical in both languages:

- Known: named face ID, display name, match score, and exactly 512 finite
  floats are required.
- Unknown: no face ID, display name, match score, or reference embedding.
- Stale generation, epoch, and revision fencing remains unchanged.

The vector is biometric data. It is sent only over the existing child stdin
pipe. It must never appear in argv, stdout events, logs, metrics, database rows,
or error text. Native state overwrites and releases the vector on reset,
replacement, expiry, and shutdown.

Keeping the active normalized reference vector in native memory is not a score
cache: the vector is immutable comparison input, while the displayed cosine is
recomputed from the new ArcFace output on every eligible frame. Querying Qdrant
or PostgreSQL from every frame is explicitly forbidden.

### Native Data Plane

ArcFace continues to run on every frame. For each tracked object with a valid
embedding, native code computes a dot product against that track's normalized
reference embedding. The result is clamped to `[-1, 1]` and stored as the
current frame score.

The pipeline explicitly configures SGIE reinference for every tracked frame
instead of relying on the DeepStream default classifier cache. Acceptance must
show embedding coverage advancing with decoded frames and at least two distinct
current-frame embeddings while the face pose changes. This prevents a cached
first embedding from producing a convincingly dynamic detector score beside a
false constant recognition score.

`LiveOsdState` separates assigned identity from visible state:

- assigned identity: current face ID, name, epoch, reference embedding;
- visible state: Known or Unknown after three-frame hysteresis;
- current score: replaced on every eligible frame.

The label becomes `<name> cos=<current> det=<current>` while the Known streak is
active, and `Unknown cos=<current> det=<current>` after three low frames. Before
a reference exists, the existing `Pending det=<current>` label remains.

The OSD calculation is local CPU work over 512 floats and does not perform I/O,
Qdrant calls, allocations, or blocking operations in the pad probe.

## Identity Switching

Per-frame hysteresis answers only whether the currently assigned identity still
matches the current face. It cannot select a different gallery identity.

Every five eligible frames, Python performs the gallery decision. A different
candidate must win three consecutive evaluations with the existing absolute
threshold and top-2 margin. On confirmation Python sends:

1. an Unknown reset at a higher identity epoch;
2. a Known assignment in that epoch with the new reference embedding.

This removes permanent immutability without permitting a one-frame
Rachel-to-Monica switch. Candidate or tracker expiry resets the streak.

## Failure Handling

- Missing, malformed, non-finite, or non-normalized reference vectors reject
  the assignment without changing current state.
- Qdrant retrieval failure leaves the current label state intact and records a
  bounded sanitized error; no incomplete Known assignment is sent.
- A missing current-frame embedding leaves the previous visible label but omits
  cosine advancement for that frame.
- Queue coalescing may replace older assignments only within the same tracker;
  generation, epoch, and revision ordering remains authoritative.

## Tests

### Python

- Cross-language protocol parity for Known and Unknown reference embeddings.
- Reject wrong dimension, NaN, infinity, and malformed Known/Unknown payloads.
- Retrieve the matched Qdrant vector without exposing it in logs or events.
- Require three consecutive candidate wins before switching.
- Reset to Unknown after three rejected five-frame evaluations.
- Preserve durable event deduplication during score-only updates.

### C++

- Per-frame cosine changes when the current embedding changes.
- SGIE reinference configuration and counters prove embeddings are produced
  after the first frame of a track.
- Exact cosine and clamp behavior for normalized 512-float vectors.
- Three high frames transition Unknown to Known.
- Three low frames transition Known to Unknown.
- One contrary frame does not flicker the label.
- New epoch replaces identity only through Unknown reset then Known assignment.
- Expiry and shutdown remove reference embedding and score.

### Live Acceptance

- With `Baris` assigned, eye closure and pose changes visibly change cosine
  while detector confidence continues changing independently.
- Three consecutive below-threshold frames show Unknown.
- Three consecutive above-threshold frames restore Baris.
- A second unregistered person becomes Unknown within three frames.
- A registered replacement requires three gallery evaluations before switch.
- Annotated RTSP decodes five frames without errors and a stalled viewer does
  not block inference.

## Non-Goals

- Persisting every frame score.
- Lowering recognition thresholds to force a match.
- Removing top-2 margin or quality gates.
- Cross-camera ReID.
- Repairing the deferred Phase 2 Rachel-to-Monica historical result flow.
