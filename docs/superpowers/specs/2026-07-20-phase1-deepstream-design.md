# Phase 1 DeepStream Face Recognition Design

## 1. Objective

Implement `requirements/ProjectRequirements.md` as an API-only, GPU-first face recognition
service. Phase 1 accepts one encoded image per recognition request, detects every face, assigns
each face a persistent global `faceId`, distinguishes `known`, `anonymous`, and
`new_anonymous`, persists identity evidence, and provides process/history traceability.

The production data plane uses persistent NVIDIA DeepStream 9.0 pipelines. Video upload and
live stream behavior are not implemented in Phase 1. The detector, alignment, recognizer,
embedding space, gallery, and global `faceId` semantics must remain reusable by those later
input adapters.

## 2. Scope

### In scope

- All behavior in `requirements/ProjectRequirements.md`.
- Image recognition, enrollment, identity query/update/delete, and history APIs.
- Multiple face samples per identity, including sample listing and deletion.
- Persistent PostgreSQL, MinIO, and Qdrant data.
- Three persistent DeepStream GPU workers, one per installed Quadro RTX 8000.
- Dockerized deployment with environment-driven configuration.
- An internal labeled-directory bulk enrollment and throughput benchmark utility.

### Out of scope

- Video upload endpoints, video jobs, sampling, tracking, and aggregation.
- RTSP, webcam, live stream, camera lifecycle, and alerting.
- User interface.
- Public dataset-management or bulk-enrollment product endpoints.
- CPU inference, decode, alignment, or encoding fallback.

## 3. Requirement Traceability

| Requirement | Design behavior |
|---|---|
| 1. Image input | One encoded image per recognition request; validate size, media type, decodeability, empty/corrupt input; no-face is success. |
| 2. Detection | Detect all faces independently and return original-image bounding boxes. |
| 3. Recognition | Every detected face receives a persistent `faceId`; thresholded matching returns `known`, `anonymous`, or `new_anonymous`. |
| 4. Unknown storage | Unmatched faces are persisted without PII and are recognized under the same `faceId` later; enrollment preserves that ID. |
| 5. Record management | Enroll, query, update, soft-delete identities, retain multiple samples, and list/delete individual samples. |
| 6. Process tracking | Generate a unique UUIDv7 `processId` at the API boundary and return it in structured responses. |
| 7. Logging | Persist timestamp, operation, face count, face IDs, and status snapshots; auxiliary event failure does not invalidate a committed primary result. |
| 8. History | Query face appearances by process/time and retrieve process details/results. |
| 9. API behavior | API-only, versioned contracts, consistent responses, and sanitized distinguishable errors. |
| 10. Endpoints | Implement the required face/process endpoints under `/api/v1`, plus explicit sample-management endpoints. |
| 11. Result content | Return process ID, face count, and per-face ID, status, name, metadata, bbox, and confidence. |
| 12. Docker | Buildable Dockerfile/Compose, automatic startup, environment configuration, and persistent volumes. |

## 4. Architecture

The existing three-layer boundary remains fixed:

```text
Presentation (router + controller)
    -> Service (workflow and identity lifecycle)
        -> Infrastructure (PostgreSQL, MinIO, Qdrant, native GPU client)
```

The FastAPI process is the control plane. Native C++ DeepStream workers are the data plane.
Workers are long-lived; an API request never creates or tears down a pipeline. Each worker owns
one CUDA device, DeepStream pipeline, TensorRT execution resources, and bounded input/output
queues.

```text
FastAPI / internal bulk utility
            |
        scheduler
      /     |     \
 GPU 0    GPU 1    GPU 2
 worker   worker   worker
      \     |     /
     compact results
            |
 identity lifecycle + persistence
            |
 PostgreSQL / MinIO / Qdrant
```

Scheduling uses bounded queues and backpressure. Bulk traffic may fill larger batches; normal
API traffic uses a bounded wait so throughput optimization cannot cause unbounded request
latency. Batch sizes are benchmark outputs, not hard-coded assumptions.

## 5. Canonical DeepStream Data Plane

```text
encoded JPEG
-> nvjpegdec (NVMM RGB surface)
-> nvvideoconvert as required by nvstreammux
-> nvstreammux (CUDA device memory, dynamic micro-batch)
-> nvinfer PGIE: YOLOv8-Face TensorRT
-> custom GPU output decode, confidence filter, NMS, bbox, five landmarks
-> nvdspreprocess custom C++/CUDA library: five-point similarity alignment
-> nvinfer SGIE: ArcFace R50 TensorRT on canonical 112x112 faces
-> GPU-normalized 512-D embedding
-> GPU JPEG encoding of accepted aligned 112x112 evidence
-> compact output boundary
```

DeepStream system libraries are not patched. Landmark-aware alignment uses the official
`nvdspreprocess` custom-library extension point. Python DeepStream bindings are not used in the
production data plane.

Only the following cross the GPU/CPU boundary:

- Original-coordinate bbox, five landmarks, detector score, and rejection/quality metadata.
- Finite L2-normalized 512-D embedding.
- GPU-encoded aligned-face JPEG bytes.

Full decoded images, detector tensors, alignment tensors, ArcFace input tensors, and
unnormalized embeddings do not cross the boundary.

Phase 1 declares JPEG as the supported production image format. Empty, corrupt, mislabeled,
or unsupported input is rejected with a structured client error. Additional formats require a
separately verified NVIDIA GPU decoder path and do not receive a silent CPU fallback.

## 6. Model Gates

YOLOv8-Face remains a candidate until the following are source- and runtime-verified:

- Artifact SHA-256, provenance, and acceptable model/license terms.
- Input name, dtype, NCHW layout, fixed processing resolution, and batch dimensions.
- All output names, shapes, dtypes, DFL/stride behavior, confidence formula, and NMS behavior.
- Exact five-landmark order and original-coordinate reverse mapping.
- TensorRT batch-1/batch-N parity and no-face/one-face/multi-face evidence.

The current ArcFace artifact must be frozen by SHA-256. Its graph already contains
`(input - 127.5) / 128` preprocessing and output `LpNormalization`; production code must not
apply conflicting duplicate preprocessing. Exact channel order, template order, interpolation,
pixel-center behavior, and embedding parity are runtime gates.

TensorRT engines are built and benchmarked in a DeepStream 9.0/TensorRT 10.16-compatible
development container. Generated engines are device/runtime-specific artifacts and are not
committed to Git.

## 7. Identity and Sample Lifecycle

Persistent identity state is `anonymous` or `known`. `new_anonymous` exists only in the
immutable result of the first request that creates an unmatched identity.

```text
unmatched observation -> create anonymous identity/sample -> result new_anonymous
same person again     -> same faceId                    -> result anonymous
enroll anonymous      -> preserve faceId + add name     -> state/result known
known person again    -> same faceId + name/metadata    -> result known
```

Known identities have a display `name` and optional metadata in addition to their technical
`faceId`. Anonymous identities have `name = null` and empty metadata. Name/metadata changes do
not rewrite historical recognition snapshots.

Enrollment supports:

- New image plus name/metadata to create a known identity.
- Existing anonymous `faceId` plus name/metadata to promote it while preserving `faceId`.
- New image sample for an existing known identity.

Every enrollment/sample image must contain exactly one face. Zero faces returns
`FACE_NOT_FOUND`; multiple faces returns `MULTIPLE_FACES_NOT_ALLOWED`.

Identity deletion is soft/inactive and retains history. Sample deletion makes the sample
inactive, removes it from matching, and reconciles its Qdrant/MinIO resources. An identity with
no active samples remains queryable for lifecycle/history but cannot produce a new recognition
match.

## 8. Storage Ownership and Consistency

- PostgreSQL is the business source of truth for identities, sample lifecycle, processes,
  results, and events.
- MinIO stores canonical aligned 112x112 JPEG evidence at
  `faces/{faceId}/{sampleId}/aligned` with `image/jpeg` content type.
- Qdrant stores one 512-D cosine vector per active sample. Point ID equals `sampleId`; payload
  contains only technical allowlisted fields.

Creating a sample follows:

```text
PostgreSQL identity + pending sample
-> MinIO aligned evidence upload
-> PostgreSQL sample blob_ready
-> Qdrant vector upsert
-> PostgreSQL sample active/indexed
-> immutable result + process completion
```

IDs and object keys are deterministic for retries. Partial failure creates a sanitized event
and leaves a reconcilable lifecycle state. A newly created anonymous face is not reported as a
successful `faceId` if its required sample cannot be persisted.

## 9. API Contract

Canonical endpoints:

```text
POST   /api/v1/faces/recognize
POST   /api/v1/faces/enroll
POST   /api/v1/faces/{faceId}/samples
GET    /api/v1/faces/{faceId}/samples
DELETE /api/v1/faces/{faceId}/samples/{sampleId}
GET    /api/v1/faces/{faceId}
PATCH  /api/v1/faces/{faceId}
DELETE /api/v1/faces/{faceId}
GET    /api/v1/faces/{faceId}/history
GET    /api/v1/processes/{processId}
```

Request contracts are explicit:

- `POST /faces/recognize` is multipart with exactly one required `image` part.
- `POST /faces/enroll` is multipart with required `name`, optional JSON `metadata`, optional
  `faceId`, and optional `image`. A new known identity requires `image` and no `faceId`.
  Promoting an existing anonymous identity requires `faceId`; `image` is optional and, when
  present, becomes an additional accepted sample. The named `faceId` must exist, be active, and
  be anonymous unless the operation is an idempotent retry.
- `POST /faces/{faceId}/samples` is multipart with exactly one required `image` part and adds a
  sample to an active known identity.
- `PATCH /faces/{faceId}` is JSON with at least one of `name` or `metadata`.
- Identity and sample deletes are idempotent soft/inactive lifecycle operations. Deleting a
  sample also removes its matching vector and canonical evidence through the reconciliation
  workflow; historical process snapshots remain intact.

All image fields enforce configured byte-size limits before decode. Enrollment and sample
addition enforce the exactly-one-face rule after decode/detection.

Recognition success:

```json
{
  "processId": "<uuidv7>",
  "faceCount": 1,
  "faces": [
    {
      "faceId": "<uuidv7>",
      "status": "known",
      "name": "Jennifer Aniston",
      "metadata": {},
      "boundingBox": {"x": 0, "y": 0, "width": 0, "height": 0},
      "confidence": 0.94
    }
  ]
}
```

No-face is HTTP success with `faceCount = 0` and `faces = []`. Every request obtains a UUIDv7
`processId` at the boundary. Success and standardized error responses include it whenever an
HTTP response can be produced. Errors expose a stable code and sanitized message, never SQL,
paths, secrets, native stack traces, or raw exceptions.

The public `confidence` field is recognition similarity for the selected identity/sample, not
detector confidence. A newly created anonymous identity has no prior match and returns `0.0`.
Detector confidence remains in the immutable internal result for diagnostics and audit.

## 10. Internal Bulk Enrollment

Bulk enrollment is an internal CLI/acceptance utility, not a public product endpoint. It reads
a labeled directory such as `root/person_name/image.jpg`, creates one known identity per label,
and submits image descriptors to the same persistent workers and persistence workflow used by
the API. Dataset labels never appear in MinIO object keys or Qdrant payloads.

Compute and persistence use separate bounded queues so storage latency does not idle GPU
workers until backpressure is required. PostgreSQL operations, MinIO uploads, and Qdrant
upserts use safe micro-batches while preserving each sample's explicit cross-store lifecycle.

## 11. Performance Strategy

There is no unproven fixed FPS acceptance target. Optimize for the highest sustainable
throughput on the installed three-GPU host while preserving semantics and durability.

Report three metrics separately:

1. GPU hot-path throughput: decode through normalized embedding.
2. Compute-plus-evidence throughput: includes GPU aligned-face encoding and compact transfer.
3. Durable end-to-end throughput: includes PostgreSQL, MinIO, and Qdrant completion.

Benchmark detector, recognizer, mux, encoder, queue, and persistence micro-batch sizes rather
than assuming 256 is optimal. Record latency percentiles, throughput, GPU utilization/memory,
queue depth, failure count, and exact model/engine/runtime hashes. Interactive and bulk traffic
may use separate measured batching policies while sharing identical models and preprocessing.

## 12. Error Handling

- Empty/corrupt/unsupported input is a structured client error.
- Valid no-face input is successful.
- Enrollment with zero or multiple faces is a structured client error.
- CUDA, TensorRT, DeepStream, context, stream, and OOM failures are systemic failures and never
  trigger CPU fallback.
- One malformed input may be rejected independently; systemic batch failure fails closed.
- Auxiliary event-log failure does not invalidate an already committed primary recognition
  result, but process/result queryability remains mandatory.

## 13. Verification and Acceptance

Acceptance uses real PostgreSQL, MinIO, Qdrant, DeepStream, TensorRT, and GPUs. Required cases:

- Empty, corrupt, unsupported, and valid no-face images.
- Real one-face and multi-face detection with original-coordinate bboxes.
- First unseen face `new_anonymous`; repeat is `anonymous` with the same `faceId`.
- Anonymous enrollment becomes `known` with the same `faceId` and display name.
- New known enrollment and additional sample enrollment require exactly one face.
- Mixed known/anonymous multi-face recognition.
- Identity query/update/delete and sample add/list/delete.
- Face history and immutable process detail retrieval.
- 512-D finite normalized embeddings and batch-1/batch-N semantic parity.
- Cross-store failure, retry idempotency, reconciliation, and restart persistence.
- Three-worker throughput benchmark with separate GPU-only and durable metrics.
- Repeated startup/shutdown without segfault; bounded synchronization and GPU memory return.
- Docker image build and Compose startup without manual post-start steps.

No mock, skipped test, engine build, engine deserialize, or `nvidia-smi` process listing alone is
sufficient evidence for a GPU or production PASS.
