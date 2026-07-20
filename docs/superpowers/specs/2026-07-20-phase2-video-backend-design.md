# Phase 2 Video Recognition Backend Design

## Status

Approved on 2026-07-20. The implementation scope is the complete backend in
`requirements/videorequirements.md`. UI work and live RTSP/camera support are excluded.

## Goals

- Accept an uploaded video and return a durable asynchronous job immediately.
- Validate, retain, retrieve, and eventually expire source videos.
- Keep decode, detector inference, tracking, face alignment, and ArcFace inference on the
  NVIDIA DeepStream GPU path.
- Return one result per unique person rather than one result per frame.
- Preserve every sampled detection needed to draw bounding boxes on the original video.
- Reuse the existing known, anonymous, and new-anonymous identity lifecycle.
- Preserve process logging and make face-to-video appearances queryable.
- Keep the design compatible with a future live-source worker without implementing Phase 3.

## Non-Goals

- No frontend or annotated-video renderer.
- No RTSP, webcam, camera lifecycle, WebSocket event stream, or alerts.
- No cross-camera re-identification.
- No Redis or Celery dependency in this phase.
- No replacement of the existing image recognition endpoints or GPU workers.

## Research Conclusions

The reference implementations establish the following reusable patterns:

- `zhouyuchong/face-recognition-deepstream` validates the order detector, tracker,
  recognizer and reads SGIE tensor metadata from the associated object metadata.
- NVIDIA DeepStream documents that secondary `NvDsInferTensorMeta` is attached to
  `NvDsObjectMeta.obj_user_meta_list`, while `NvDsObjectMeta.object_id` carries the tracker ID.
- The previous `MergenVisionPhase2v2` implementation provides useful job leasing,
  idempotent persistence, track reconciliation, and retention patterns. Its custom TensorRT
  inference runtime will not be copied because this project requires DeepStream on the GPU
  hot path.
- The Celery reference is operationally valid, but a PostgreSQL queue avoids adding Redis and
  still provides durable claims, leases, retries, cancellation, and restart recovery.

## Architecture

The API is the control plane. Dedicated GPU video workers are the data plane.

```text
Client
  -> FastAPI upload and ffprobe validation
  -> MinIO source object
  -> PostgreSQL video_job (pending)
  -> GPU video worker claims job with a lease
  -> Native DeepStream file pipeline
  -> Native track summary protocol
  -> Python reconciliation and Qdrant identity resolution
  -> PostgreSQL video_track and recognition_result
  -> completed job/result API
```

One `video-worker-N` container runs per GPU with concurrency one by default. This isolates
long-running videos from API processes and from the existing low-latency image worker socket.
Concurrency and worker count remain environment-configurable.

## Upload and Validation

`POST /api/v1/videos/recognize` accepts multipart form data:

| Field | Type | Meaning |
|---|---|---|
| `video` | file | Required source video. |
| `samplingMode` | enum | `every_frame`, `every_n_frames`, or `frames_per_second`. |
| `everyNFrames` | integer | Required only for `every_n_frames`. |
| `framesPerSecond` | float | Required only for `frames_per_second`. |

If no sampling fields are supplied, the configured default target FPS is used.

The API performs these steps before returning `202 Accepted`:

1. Create a `video_recognize` process record so validation failures remain traceable.
2. Stream the request into a bounded temporary file while calculating SHA-256.
3. Reject an empty file or a file exceeding the configured byte limit.
4. Run `ffprobe` with a configured timeout.
5. Validate container, video codec, duration, dimensions, FPS, and non-zero frame count.
6. Upload to MinIO at `videos/{jobId}/source` and verify object size.
7. Create a pending `video_job` linked to the process and return its URLs.

MIME type and filename extension are advisory. The probed media stream is authoritative.
Temporary files and partially uploaded objects are removed best-effort on failure. Cleanup
failures are logged but do not replace the original error.

## DeepStream GPU Worker

The native C++ pipeline for one uploaded file is:

```text
uridecodebin / NVDEC
  -> nvvideoconvert (NVMM)
  -> nvstreammux
  -> nvinfer PGIE (YOLOv8-Face plus five landmarks)
  -> nvtracker (NvDCF)
  -> tracker sampling probe
  -> nvdspreprocess (five-point GPU Umeyama alignment)
  -> nvinfer SGIE (ArcFace R50)
  -> result probe
  -> fakesink
```

The pipeline uses the existing detector parser, TensorRT engines, alignment CUDA kernel, and
DeepStream inference configuration. Video-specific config changes are separate files so image
worker batch settings are not changed.

### Metadata Association

The video path must not correlate embeddings by raw callback row order. The SGIE result probe
walks each frame's object list and reads `NVDSINFER_TENSOR_OUTPUT_META` from that object's
`obj_user_meta_list`. The tuple below is therefore the stable observation key:

```text
(source_id, frame_num, object_id, detection_ordinal)
```

This avoids the batch-row association defect previously observed in image gallery generation.

### Sampling

The tracker receives every decoded frame. Detector inference frequency is reduced with PGIE
`interval`:

- `every_frame`: interval `0`.
- `every_n_frames=N`: interval `N - 1`.
- `frames_per_second=X`: derive an effective integer N from probed nominal FPS, then use
  interval `N - 1`.

The tracker-source probe removes objects from non-sampled frames before preprocessing. This
keeps tracking continuity while preventing ArcFace work and result collection on skipped
frames. The response reports both requested and effective sampling settings.

`processedFrames` means sampled frames subjected to detector/recognizer result collection.
`totalFrames` remains the source frame count.

### Coordinates and Rotation

The pipeline normalizes container rotation before inference. `nvstreammux` is configured with
the display dimensions reported by validation. DeepStream detector metadata is therefore in
display-space coordinates. If a configured processing-size cap causes downscaling or padding,
the worker applies the recorded scale and padding transform before emitting a bounding box.

Every API bounding box uses original display coordinates:

```json
{"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
```

Coordinates are clamped to video bounds.

### Native Output Protocol

The native executable writes length-prefixed MessagePack events to stdout and diagnostics to
stderr. It reuses the existing framing convention but has a video-specific protocol version.

Event types are:

- `progress`: decoded frame, processed frame count, total frame count, and progress percent.
- `track`: raw tracker ID, representative normalized embedding, first/last PTS, and sampled
  detections.
- `completed`: source metadata and aggregate counters.
- `failed`: stable error code and sanitized diagnostic.

Each detection contains frame number, PTS seconds, original-coordinate bbox, detector
confidence, and embedding confidence. Full video frames never cross the process boundary.

## Tracking and Aggregation

The native worker groups observations by `NvDsObjectMeta.object_id` into raw tracklets. At EOS,
the Python service reconciles fragmented tracklets into canonical tracks.

Two tracklets can merge only when:

- Their time intervals do not overlap.
- Their normalized representative embeddings meet the configured reconciliation threshold.
- The merge does not violate a same-frame cannot-link constraint.

The representative embedding is the L2-normalized mean of valid, high-quality embeddings.
The representative detection is the highest-quality observation, with deterministic ties by
earlier frame number and detection ordinal.

Appearance intervals split whenever the gap between sampled observations exceeds the
configured maximum gap. For each canonical track the service computes:

- `firstSeen` and `lastSeen` from PTS.
- `totalDuration` as the sum of appearance interval durations.
- `appearances` with start/end PTS and frame numbers.
- `detections` for every sampled observation.

An empty video result is successful with `personCount=0`.

## Identity Resolution

Identity resolution runs once per canonical track, not once per frame.

1. Query Qdrant for top candidates with the canonical normalized embedding.
2. Apply the existing known/anonymous thresholds and active-identity checks.
3. Prevent two temporally overlapping tracks from receiving the same face ID.
4. Return `known` for a known match and `anonymous` for an existing anonymous match.
5. Create one durable anonymous identity and sample for an unmatched track, returning
   `new_anonymous` for that job.

For a newly anonymous track, the worker extracts only the representative source frame as JPEG
evidence. This bounded evidence operation is outside the inference hot path. The canonical
video embedding is persisted to Qdrant and the existing sample lifecycle is reused.

One `recognition_result` row is also created per canonical track so process queries remain
consistent with image recognition.

## Persistence Model

The migration is additive and must preserve all Phase 1 records.

### Existing Tables

`process_record` changes:

- Permit process type `video_recognize`.
- Permit status `cancelled`.
- Add non-null `details JSONB` with `{}` as the default for video metadata and counters.

### `video_job`

Core columns:

- `job_id`, `process_id`, and worker lease fields.
- `status`: `pending`, `processing`, `cancelling`, `cancelled`, `completed`, or `failed`.
- `stage`, `progress_percent`, `attempt_count`, `max_attempts`, and `error_code`.
- MinIO bucket/key, content type, size, SHA-256, and retention timestamps.
- Duration, FPS numerator/denominator, dimensions, total frames, and processed frames.
- Requested and effective sampling configuration.
- Cancellation, creation, start, update, completion, and cancellation timestamps.

Indexes cover status/availability, lease expiry, process ID, retention expiry, and creation
time.

### `video_track`

One row represents one canonical person in one job:

- `track_id`, `job_id`, `track_ordinal`, and source tracker IDs.
- `face_id` and linked `recognition_result_id`.
- Status, name, metadata, and identity version snapshots.
- Match confidence and threshold snapshot.
- First/last frame and PTS, total duration, and detection count.
- `appearances JSONB` and `detections JSONB`.
- Optional representative sample ID.

Indexes cover job ID, face ID, and `(face_id, first_seen)` for appearance history. Reprocessing
is idempotent: partial tracks for the job are replaced transactionally before finalization.

## Durable Queue and Worker Lifecycle

Workers claim jobs with PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED`. A claim writes worker
ID, lease token, lease expiration, attempt count, processing status, and start time in one
transaction.

The worker renews its lease while native processing is alive. An expired lease makes a job
eligible for retry unless its maximum attempts are exhausted. Result finalization verifies the
lease token so a stale worker cannot overwrite a newer attempt.

Progress updates are throttled by frame count and time to avoid excessive writes. Process-event
logging is best-effort and cannot change a successful job into a failed job.

## Cancellation

`DELETE /api/v1/videos/jobs/{jobId}` requests cancellation; it does not erase audit data.

- A pending job becomes `cancelled` immediately.
- A processing job becomes `cancelling` and sets `cancellation_requested=true`.
- The worker sends SIGTERM to the native child.
- The native signal handler stops its GLib loop and sets the pipeline to `GST_STATE_NULL`.
- The worker marks the job and process `cancelled` and removes partial track rows.
- Repeated cancellation is idempotent.

## Retention

The source object has a configured `retention_until`. Each worker periodically claims a bounded
batch of expired objects, deletes them from MinIO, and records `source_deleted_at`.

Job metadata, result tracks, process logs, and anonymous identities are retained. Source video
retrieval returns `410 Gone` after retention cleanup. Cleanup errors are retried and do not
affect completed recognition results.

## API Contracts

### Submit

`POST /api/v1/videos/recognize` returns `202`:

```json
{
  "jobId": "uuid",
  "processId": "uuid",
  "status": "pending",
  "statusUrl": "/api/v1/videos/jobs/uuid",
  "resultUrl": "/api/v1/videos/jobs/uuid/result"
}
```

### Status

`GET /api/v1/videos/jobs/{jobId}` returns status, stage, progress, cancellation state, source
metadata, sampling configuration, counters, timestamps, and sanitized error details.

### Result

`GET /api/v1/videos/jobs/{jobId}/result` returns `409 JOB_NOT_COMPLETED` until completed. A
completed response follows the person-based shape in `videorequirements.md`, including video
metadata, person count, tracks, appearance intervals, and every sampled bbox.

### Source Video

`GET /api/v1/videos/jobs/{jobId}/video` streams the retained source with its content type and
range support. It returns `410 VIDEO_EXPIRED` after retention and `404` for an unknown job.

### Appearance History

`GET /api/v1/faces/{faceId}/appearances` returns jobs, source availability, first/last seen,
appearance intervals, and track IDs, ordered newest first.

### Errors

Stable error codes include:

- `VIDEO_TOO_LARGE`
- `VIDEO_EMPTY`
- `VIDEO_UNSUPPORTED_CONTAINER`
- `VIDEO_UNSUPPORTED_CODEC`
- `VIDEO_INVALID`
- `VIDEO_DURATION_EXCEEDED`
- `VIDEO_PROBE_TIMEOUT`
- `VIDEO_PROCESSING_TIMEOUT`
- `VIDEO_PIPELINE_ERROR`
- `JOB_NOT_FOUND`
- `JOB_NOT_COMPLETED`
- `VIDEO_EXPIRED`

Errors use the existing structured service-error response and include `processId` when a
process record exists.

## Configuration

All operational values are environment-configurable:

- `VIDEO_MAX_UPLOAD_BYTES`
- `VIDEO_MAX_DURATION_SECONDS`
- `VIDEO_ALLOWED_CONTAINERS`
- `VIDEO_ALLOWED_CODECS`
- `VIDEO_RETENTION_SECONDS`
- `VIDEO_MINIO_PREFIX`
- `VIDEO_DEFAULT_SAMPLING_MODE`
- `VIDEO_DEFAULT_FRAMES_PER_SECOND`
- `VIDEO_MAX_CONCURRENT_JOBS`
- `VIDEO_JOB_TIMEOUT_SECONDS`
- `VIDEO_JOB_LEASE_SECONDS`
- `VIDEO_JOB_MAX_ATTEMPTS`
- `VIDEO_PROGRESS_UPDATE_INTERVAL_SECONDS`
- `VIDEO_TRACK_RECONCILIATION_THRESHOLD`
- `VIDEO_APPEARANCE_MAX_GAP_SECONDS`
- `VIDEO_WORKER_POLL_SECONDS`
- `VIDEO_WORKER_GPU_ID`
- `VIDEO_TRACKER_CONFIG_PATH`
- `VIDEO_PGIE_CONFIG_PATH`
- `VIDEO_PREPROCESS_CONFIG_PATH`
- `VIDEO_SGIE_CONFIG_PATH`

Defaults are production-safe and documented in `.env.example` and Docker Compose.

## Deployment

Docker Compose adds `video-worker-0`, `video-worker-1`, and `video-worker-2`. Each is pinned to
one GPU, mounts model/config files, and connects to PostgreSQL, MinIO, and Qdrant. Source and
result durability comes from existing named volumes; no existing volume is recreated.

The API image adds `ffprobe`. The DeepStream worker image adds the backend Python package and
the native video executable while reusing the Phase 1 native libraries and engines.

## Verification Strategy

### Python Tests

- Upload size, empty input, probe timeout, format, codec, duration, and sampling validation.
- API contracts for submit, status, result, cancellation, source retrieval, and appearances.
- Job claim, lease renewal, stale lease retry, max-attempt failure, and stale-worker rejection.
- Track reconciliation, cannot-link behavior, deterministic representative selection, and
  appearance interval construction.
- Known, existing anonymous, and new-anonymous identity outcomes.
- Idempotent result persistence and no-face completion.
- Retention cleanup and `410 Gone` behavior.

### Native Tests

- MessagePack protocol round trips and malformed-frame rejection.
- Sample-frame selection and original-coordinate bbox transforms.
- Object tensor metadata remains associated with tracker ID and frame number.
- Track accumulation, normalized representative embedding, EOS flush, and cancellation.

### GPU Integration Tests

- Build and start all Compose services without resetting volumes.
- Process the local Friends sample through real NVDEC, PGIE, NvDCF, GPU alignment, SGIE, and
  EOS.
- Assert increasing progress, completed status, stable track IDs, normalized embeddings,
  original-coordinate boxes, and a retrievable result.
- Cancel a long-running job and verify native shutdown plus durable cancelled state.
- Restart a worker during a job and verify lease-based recovery.

## Acceptance Criteria

The implementation is complete when all required endpoints and persistence paths pass their
tests, the real GPU smoke video completes through the DeepStream chain, no-face and cancellation
cases behave as specified, source retention is enforced, and existing image recognition data
and endpoints continue to work without a volume reset.
