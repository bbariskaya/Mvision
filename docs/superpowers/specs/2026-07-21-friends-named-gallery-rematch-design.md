# Friends Named-Gallery Rematch Design

## Goal

Produce a trustworthy 100-frame Friends annotation by rebuilding the isolated Friends gallery and assigning each video track to the highest-scoring named cast identity when its cosine score is at least 0.60.

## Matching Rule

- Only active identities with `lifecycle_status=known` may compete for a cast label.
- For each source template, compare eligible samples from all six known identities.
- Discard candidates below cosine 0.60.
- When multiple known identities pass, select the highest-scoring candidate and aggregate its support through the existing track vote mechanism.
- Anonymous identities never outrank or suppress a known candidate.
- For each template, the highest named candidate at or above 0.60 receives the vote. The track winner is the identity with the strongest weighted vote support, with weighted cosine as the tie-breaker.
- A track remains `Unknown` only when no known identity reaches 0.60. Margin and minimum-consensus rules must not reject an otherwise valid named winner.
- The displayed cosine is the score supporting the final decision. A rejected nearest-known score must be preserved for `Unknown`; unavailable scores must not be represented as measured zero.

## Clean Rebuild

- Remove Friends-only recognition results, tracks, video jobs, anonymous identities, samples, vectors, and test video objects.
- Remove and re-enroll the six known cast identities from `friends_chars/Friends/Train` through the Friends API.
- Do not modify production stores or the non-Friends API, Qdrant collection, MinIO buckets, or database.
- Verify exactly six active known identities, zero active anonymous identities before the run, 297 active samples, and matching Qdrant point count.

## Deployment

- Configure Friends recognition and vote candidate floor to 0.60.
- Keep the native embedding-row/object association fix.
- Mount current backend application code into the Friends video worker so the final native frame count is persisted.
- Recreate Friends API and Friends video worker, then inspect live container code/config rather than assuming deployment succeeded.

## Validation

- Run unit tests for named-only candidate selection, highest-score selection, rejected-score preservation, and final processed-frame persistence.
- Submit `Friends_100f.mp4` with every-frame sampling.
- Require `totalFrames=100` and `processedFrames=100` from the status API.
- Render `Friends_100f.annotated.mp4` and inspect representative frames across the entire clip.
- Every rendered detection must include its bounding box, resolved cast name or `Unknown`, detector score, cosine confidence score, and all five face-alignment landmarks.
- Verify boxes and landmarks belong to their faces and labels match visible cast members.
- If labels remain wrong, compare per-object embeddings, nearest named candidates, sample provenance, alignment crops, and gallery class membership to identify the root cause. Do not compensate by changing thresholds again.
- Do not run the full 6665-frame video until the 100-frame result passes.

## Safety

- All cleanup is restricted to `mergenvision_friends`, `friends_arcface_r50_v1`, `mergenvision-friends-faces`, and `mergenvision-friends-videos`.
- Capture Friends-only counts before and after cleanup and enrollment.
- Use supported API/service deletion paths where available so PostgreSQL, Qdrant, and MinIO stay consistent.
