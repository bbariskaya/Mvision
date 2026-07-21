# Friends Balanced Recognition Design

## Goal

Produce a corrected every-frame Friends annotation without forcing guest actors or weak detections into one of the six enrolled cast identities.

## Decision

The Friends-only stack will use:

- `RECOGNITION_THRESHOLD=0.78`
- `ANONYMOUS_THRESHOLD=0.78`
- `VIDEO_TRACK_RECONCILIATION_THRESHOLD=0.95`
- `VIDEO_TRACK_VOTE_CANDIDATE_FLOOR=0.70`
- the existing two-vote consensus, `0.05` ambiguity margin, and `0.60` support ratio

These values are isolated to `docker-compose.friends.yml`. Production settings do not change.

## Rationale

Corrected cast tracklets empirically score from the upper `0.70`s through the `0.90`s. A `0.78` strong-match threshold accepts useful single-track evidence while retaining `Unknown` for weaker detections and most unrelated faces. Candidates down to `0.70` remain available only for multi-track consensus.

The previous `0.90` reconciliation threshold merged different characters into long ambiguous canonical tracks. Complete-link reconciliation at `0.95` requires every source tracklet in a canonical track to remain highly similar, reducing cross-character merges without disabling reconciliation entirely.

## Data Flow

1. Detect and align faces on every source frame.
2. Aggregate observations by native tracker ID.
3. Reconcile only source tracks whose pairwise cosine is at least `0.95` and whose detections do not overlap.
4. Accept a single source vote at `0.78` or stronger.
5. Accept scores from `0.70` to `0.78` only through the existing consensus and ambiguity checks.
6. Leave weak or conflicting tracks `Unknown`.

## Validation

- Delete only anonymous identities created by superseded Friends jobs.
- Run all 6,665 source frames again.
- Confirm all six enrolled identities remain active and character-named.
- Inspect per-label track and detection counts, confidence distribution, and representative timestamps.
- Render only from the corrected job.
- Probe the final MP4 for 6,665 video frames, 1920x1080 H.264 video, retained AAC audio, and source duration.

K-best representative selection, brightness, pose, alignment, and quality gates are explicitly deferred.
