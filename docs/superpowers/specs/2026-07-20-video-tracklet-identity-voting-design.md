# Video Tracklet Identity Voting Design

## Goal

Resolve a canonical video track from its source tracklet embeddings instead of relying on one
averaged canonical embedding. This must recover identities whose individual appearances match the
gallery while rejecting tracks with conflicting or weak evidence.

## Scope

- Reuse the existing native `VideoTrackOutput` embedding for each source tracker ID.
- Keep canonical track reconciliation and the public API schema unchanged.
- Preserve known and anonymous identity lifecycle behavior.
- Add no database migration and make no native protocol change.

Per-detection embedding transport and a general identity-merge API are outside this change.

## Architecture

`VideoTrackingService` will retain a source template for every raw tracklet merged into a
`CanonicalVideoTrack`. A source template contains the normalized embedding, detection count, and
best detector confidence.

`VideoIdentityVotingService` will resolve one canonical track. For each source template it queries
active, model-compatible gallery candidates. Multiple samples belonging to the same identity are
collapsed to that identity's best score for the template. The service then aggregates support by
identity and returns either one winning `FaceMatch` or no match.

`VideoResultService` remains responsible for overlap blocking, anonymous creation, immutable result
snapshots, and persistence. It will call the voter instead of matching the canonical centroid.

## Voting Rules

Each source template contributes at most one vote to an identity. Its weight is bounded by
`1 + log1p(detection_count)` so sustained tracks have more influence without overwhelming several
independent appearances.

The voter accepts a winner by either route:

1. Strong single: at least one source template reaches the configured strong threshold.
2. Consensus: at least two source templates select the same identity above the candidate floor.

Both routes require the winner to exceed the runner-up by the configured score margin. Consensus
also requires the winner to hold a majority of eligible weighted support. If these invariants are
not met, the track is unmatched.

Known and anonymous identities use their existing lifecycle-specific thresholds for the
strong-single route. The lower candidate floor only admits evidence into consensus; it never
authorizes a single weak match.

The returned confidence is the weighted mean of supporting scores. The returned sample ID is from
the winner's highest-scoring supporting template.

## Configuration

Add video-specific settings with conservative defaults:

- `VIDEO_TRACK_VOTE_CANDIDATE_FLOOR=0.70`
- `VIDEO_TRACK_VOTE_MIN_COUNT=2`
- `VIDEO_TRACK_VOTE_MIN_MARGIN=0.05`
- `VIDEO_TRACK_VOTE_MIN_SUPPORT_RATIO=0.60`

The existing `RECOGNITION_THRESHOLD` and `ANONYMOUS_THRESHOLD` remain the strong-single thresholds.

## Data Flow

1. Native worker emits raw tracklets with one normalized representative embedding each.
2. `VideoTrackingService` reconciles tracklets and retains their source templates.
3. The voter queries candidates for each template and groups results by identity.
4. The voter applies strong-single or consensus acceptance and ambiguity rejection.
5. `VideoResultService` applies the existing temporal overlap guard.
6. A winner is persisted as known/anonymous; otherwise the existing new-anonymous path runs.

## Failure Handling

- An invalid source embedding is excluded during reconciliation as it is today.
- A gallery query failure fails the video job rather than silently creating false anonymous data.
- A candidate whose identity is missing or inactive is ignored.
- No eligible votes, a tied result, insufficient support, or insufficient margin returns no match.

## Testing

Unit tests will cover:

- A canonical centroid misses while two source tracklets agree on the correct identity.
- One strong source tracklet is accepted when all other tracklets are inconclusive.
- One weak source match is rejected.
- Two identities with insufficient score margin are rejected.
- Multiple gallery samples for one identity count as one vote per source template.
- Detection weighting is bounded and cannot replace the minimum independent vote count.
- Known and anonymous lifecycle thresholds remain distinct.
- Existing overlap blocking prevents one identity from labeling simultaneous tracks.
- Unmatched tracks still create exactly one anonymous identity and sample.

The real Friends video remains the acceptance fixture: after gallery enrollment, cast labels must be
visually checked on representative frames before an annotated artifact is accepted.

## Success Criteria

- No canonical identity decision depends solely on the averaged canonical embedding.
- Short appearances can resolve through one strong match.
- Weaker appearances require independent agreement and a clear runner-up margin.
- Existing API response and persistence contracts remain compatible.
- Unit, integration, native, and real-video validation pass without active test-identity pollution.
