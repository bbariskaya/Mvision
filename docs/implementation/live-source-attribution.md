# Livestream Source Attribution and Adaptation Ledger

## Purpose

This ledger freezes the upstream evidence used by the Mvision single-camera
livestream implementation. A reference is not a product requirement or proof
that a pattern works in Mvision. Every adopted pattern must pass the local test
and runtime gate named below.

Classification:

- `ADAPT`: license permits use, but Mvision reimplements the bounded pattern
  against its own contracts and tests.
- `ORACLE_ONLY`: behavior is inspected for comparison; no source is copied.
- `OFFICIAL_SKELETON`: official sample supplies API/topology guidance while
  Mvision owns lifecycle, security, persistence and tests.

## Frozen References

### Abdirayimov multi-stream-face-recognition

- Repository: https://github.com/Abdirayimov/multi-stream-face-recognition
- Checkout: `fc885546f2c56de5e989dac38c39b97ca7d2ad31`
- Repository license: MIT
- Classification: `ADAPT`
- Inspected areas: multi-source pipeline, probe chain, source add/remove,
  batched face encoding, threshold and top-2 margin documentation/source.
- Used findings: pipeline backpressure must be explicit; identity decisions
  need an absolute score and winner/runner margin; evidence should be batched
  or bounded rather than synchronously dispatched per object.
- Rejected findings: per-frame recognition work in the probe, FAISS gallery,
  source teardown without locally proven mux request-pad release, incomplete
  track confirmation behavior.
- Local gates: Tasks 5-9 protocol/queue/lifecycle tests and Task 11 reuse of
  `VideoIdentityVotingService`.

### Limitless AI Enhanced Surveillance System

- Repository: https://github.com/Limitless-Blue/AI_Enhanced_Surveillance_System
- Checkout: `48058b6dae1ef87fb4edd16db54926447f9621af`
- Repository license: Apache-2.0
- Classification: `ADAPT`
- Inspected areas: camera API/tasks, live stream loop, face quality checks,
  DeepSORT buffer, detection cooldown and review policy.
- Used findings: explicit camera start/stop lifecycle, bounded temporal face
  evidence, cooldown against event storms, face-size/sharpness/confidence as
  shadow-calibration candidates.
- Rejected findings: `cv2.VideoCapture`, Redis/Celery/Mongo architecture,
  Python/CPU inference hot path, fixed deployment thresholds, unverified
  DeepSORT embedding averaging.
- Local gates: Tasks 4, 6, 11 and 15.

### wjli699 DeepStream Multi-Stream Video Intelligence Pipeline

- Repository: https://github.com/wjli699/DeepStream-Multi-Stream-Video-Intelligence-Pipeline
- Branch: `feat/phase3-reid`
- Checkout: `001500fabc2784f1e2754cf6d45de37173f51aac`
- Repository license: no root license found at the frozen checkout
- Classification: `ORACLE_ONLY`
- Inspected areas: PGIE/tracker/SGIE order, tensor metadata extraction,
  embedding diagnostics, ZeroMQ publisher high-water mark/non-blocking send,
  tracker and OSD assignment.
- Used findings: SGIE metadata coverage and norm must be measured; delivery
  from a probe must be non-blocking and bounded; track assignment must be
  immutable after confirmation.
- Rejected findings: source copying, body-ReID model/gallery, first-embedding
  global identity, unverified `network-type=100`, removal of
  `operate-on-gie-id`, `secondary-reinfer-interval=1`, and NvDCF dummy mode.
- Local gates: Tasks 6-9 and the Task 7 one-variable-at-a-time A/B test.

### Ocel Labs Osprey

- Repository: https://github.com/Ocel-Labs/Osprey
- Checkout: `b1d81e870ebc9203522c3b60bb5e42fe1098cdea`
- Repository license: Apache-2.0
- Classification: `ADAPT`
- Inspected areas: source-bin factory, stream records/spot manager, lock
  discipline, `nvurisrcbin` reconnect settings, readiness and per-stream RTSP
  output topology.
- Used findings: source ownership has explicit records/states; slot allocation
  and lifecycle mutation need one lock owner; readiness comes from the media
  pipeline rather than API intent.
- Rejected findings: URI in public API/log surfaces, hosted exporter/model hub,
  two-container Unix-FD topology for the first milestone, dynamic multi-source
  batching, teardown without local leak evidence.
- Local gates: Tasks 4, 7, 8, 12 and 15.

### Ha-Meem AI Surveillance

- Repository: https://github.com/iam-ajmunna/ha_meem_ai_surveillance
- Checkout: `00081489369bb6bd150f47f04aa8d92b081af7ad`
- Repository license: no root license found at the frozen checkout
- Classification: `ORACLE_ONLY`
- Inspected areas: C++/Python DeepStream pipelines, temporal recognition,
  quality aggregation, calibration scripts, tracker expiry, snapshot/event
  path.
- Used findings: quality thresholds are camera-specific; collect percentile
  distributions in shadow mode; time/quality-weight evidence and expire stale
  tracks deterministically.
- Rejected findings: source copying, fixed camera thresholds, Python FAISS,
  OpenCV/crop work and storage calls in or near a pad probe.
- Local gates: Tasks 6, 11 and 15.

### NVIDIA DeepStream Python Apps RTSP In/Out

- Repository: https://github.com/NVIDIA-AI-IOT/deepstream_python_apps
- Application: `apps/deepstream-rtsp-in-rtsp-out`
- Checkout: `8ad0349ed7a496fae35ebb21c350641727070b89`
- Repository license: Apache-2.0
- Classification: `OFFICIAL_SKELETON`
- Inspected areas: DeepStream 9 RTSP input/output sample, H.264 RTP/UDP bridge,
  GstRtspServer mount, RTSP timestamp option, runtime source delete sample.
- Used findings: official element order/caps for H.264 RTP output,
  GstRtspServer media factory, source timestamp precondition, `flush_stop` and
  requested-pad release during source removal.
- Rejected findings: Python/PyDS as the Mvision production engine and
  sample-level lifecycle, identity, persistence, health or credential handling.
- Local gates: Tasks 1, 8, 12 and 15.

## Task 1 Installed Runtime Evidence

Runtime inspection target: pinned Mvision DeepStream 9 worker container.

Verified factories:

```text
nvurisrcbin
nvvideoconvert
nvstreammux
nvinfer
nvtracker
nvdspreprocess
nvdsosd
nvv4l2h264enc
h264parse
rtph264pay
udpsink
```

Verified versions:

```text
GStreamer: 1.24.2
DeepStream nvurisrcbin plugin: 9.0.0
GstRtspServer pkg-config: 1.24.2
```

Verified `nvurisrcbin` properties:

| Property | Type | Installed default |
|---|---|---|
| `uri` | `gchararray` | `NULL` |
| `latency` | `guint` | `100` ms |
| `drop-on-latency` | `gboolean` | `TRUE` |
| `rtsp-reconnect-interval` | `guint` | `0` seconds |
| `rtsp-reconnect-attempts` | `gint` | `-1` |

Observed non-blocking scanner warnings concern optional plugins with missing
`libmjpegutils`, Triton server, Rivermax, DVD, DTS and related libraries. None
of the required factories above failed to load. Packet 3 must repeat the check
before real pipeline acceptance and treat a required-plugin warning as fatal.

## Task 6A Trace Context Evidence

- Specification: https://www.w3.org/TR/trace-context/
- Classification: `OFFICIAL_SKELETON`; wire grammar and validity rules only,
  with no source copied.
- Used findings: lowercase version `00` trace-parent layout, 16-byte non-zero
  trace ID, 8-byte non-zero parent ID, one-byte flags, bounded trace-state and
  context propagation across process boundaries.
- Local adaptation: strict Python/C++ MessagePack header validation and echo;
  bounded semantic native-operation records are converted to spans by Python.
- Rejected behavior: direct C++ OTLP export, arbitrary baggage/attributes,
  dynamic telemetry labels and per-frame/detection/embedding spans.
- Local gates: Task 6A malformed-frame tests, native `-Werror` build and full
  cross-language golden parity (`49 passed`).

OpenTelemetry Collector, Python SDK, Prometheus, Loki, Tempo and Grafana exact
release artifacts, licenses and image digests are intentionally frozen in Task
13A/14 immediately before adding those dependencies. Design behavior was
reviewed from official project documentation listed in
`docs/superpowers/specs/2026-07-21-opentelemetry-observability-design.md`.
