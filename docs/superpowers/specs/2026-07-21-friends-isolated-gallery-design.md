# Friends Isolated Gallery Design

## Goal

Process and annotate `test_videos/Friends.mp4` using only identities enrolled from
`friends_chars/Friends/Train`. The existing 10k-person gallery must never participate in candidate
search, persistence, or anonymous identity creation for this workflow.

## Isolation Boundary

The Friends workflow uses new logical stores inside the existing infrastructure containers:

- PostgreSQL database: `mergenvision_friends`
- MinIO face bucket: `mergenvision-friends-faces`
- MinIO video bucket: `mergenvision-friends-videos`
- Qdrant collection: `friends_arcface_r50_v1`

No data is copied from the production PostgreSQL database, MinIO buckets, or Qdrant collection.
The main services retain their current configuration.

## Services

A Compose override adds:

- `friends-api` on host port `8001`, configured only for the Friends logical stores. It shares the
  existing read-only GPU image-worker socket volume so dataset enrollment follows the production
  detector, alignment, and ArcFace path.
- `friends-video-worker-0`, pinned to GPU 0 and configured only for the Friends logical stores. It
  runs the same native video pipeline and tracklet-voting implementation as the main video worker.

The Friends API and worker use distinct service names and do not replace the main API or workers.

## Provisioning

An idempotent provisioning script will:

1. Create `mergenvision_friends` when absent.
2. Apply the current Alembic migration head to that database.
3. Create both Friends MinIO buckets when absent.
4. Create and index `friends_arcface_r50_v1` when absent.

Provisioning must reject production store names and must not delete or recreate existing stores.

## Dataset Import

An import script scans exactly six directories: `Chandler`, `Joey`, `Monica`, `Phoebe`, `Rachel`,
and `Ross`. Labels map to Matthew Perry, Matt LeBlanc, Courteney Cox, Lisa Kudrow, Jennifer Aniston,
and David Schwimmer.

The importer sends JPEG files to the Friends API. It creates one identity per class and reuses that
identity ID for later accepted images. Zero-face and multiple-face images are recorded as rejected;
they are not fatal. PNG files are excluded unless converted to JPEG by an explicit future change.
Re-running the importer first discovers the class identity by exact actor name and adds only samples
whose SHA-256 is not already present for that identity.

## Video Processing

`Friends.mp4` is uploaded to the Friends API at 2 sampled frames per second. The Friends video
worker queries only `friends_arcface_r50_v1`. Tracklet voting executes as a read-only first pass for
all canonical tracks before any unmatched anonymous identity is persisted.

The acceptance run records job status, track labels, confidences, source tracklet counts, and
representative timestamps. Any test-generated anonymous identities are retained only if the final
annotation needs an anonymous label; failed or superseded-run identities are soft-deleted.

## Annotation

After representative-frame inspection, the existing annotation tool renders:

`test_videos/Friends.friends-only.annotated.mp4`

Labels use actor names for verified known tracks and `Unknown` for unresolved tracks. No incorrect
known label is rendered to improve apparent recall. The output must preserve source resolution,
duration, audio, and frame timing.

## Verification

- Friends PostgreSQL identity/sample counts include only imported cast data and current test output.
- Friends Qdrant point count equals active Friends samples.
- Production PostgreSQL, MinIO, and Qdrant counts remain unchanged by provisioning and processing.
- Dataset import reports accepted/rejected counts per class.
- The video job completes and all persisted matches reference Friends identities.
- Representative frames are visually inspected before annotation acceptance.
- `ffprobe` confirms 1920x1080, approximately 278.036 seconds, H.264 video, and retained audio.
- Python tests, native aggregation tests, Compose validation, and `git diff --check` pass.
