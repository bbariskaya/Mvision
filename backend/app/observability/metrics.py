import threading
import weakref
from dataclasses import dataclass

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.metrics import MetricWrapperBase

from app.observability.semantic import METRIC_LABEL_VALUES

REQUIRED_METRIC_NAMES = frozenset(
    {
        "mvision_live_worker_up",
        "mvision_live_runtime_state",
        "mvision_live_frames_total",
        "mvision_live_frame_age_seconds",
        "mvision_live_reconnects_total",
        "mvision_live_active_tracks",
        "mvision_live_tracked_objects_total",
        "mvision_live_eligible_objects_total",
        "mvision_live_embeddings_total",
        "mvision_live_missing_embeddings_total",
        "mvision_live_embedding_cosine_samples_total",
        "mvision_live_quality_rejections_total",
        "mvision_live_protocol_queue_depth",
        "mvision_live_protocol_dropped_total",
        "mvision_live_identity_decisions_total",
        "mvision_live_events_total",
        "mvision_live_event_suppressions_total",
        "mvision_live_output_frames_total",
        "mvision_live_websocket_dropped_total",
        "mvision_telemetry_queue_depth",
        "mvision_telemetry_dropped_total",
        "mvision_telemetry_export_failures_total",
        "mvision_native_operation_duration_seconds",
        "mvision_live_trace_sampling_total",
    }
)


@dataclass(frozen=True)
class _Definition:
    name: str
    kind: type[MetricWrapperBase]
    documentation: str
    labels: tuple[str, ...] = ()


_DEFINITIONS = {
    "worker_up": _Definition("mvision_live_worker_up", Gauge, "Live worker availability."),
    "runtime_state": _Definition(
        "mvision_live_runtime_state", Gauge, "Current live runtime state.", ("state",)
    ),
    "frames_total": _Definition(
        "mvision_live_frames_total", Counter, "Decoded live frames."
    ),
    "frame_age_seconds": _Definition(
        "mvision_live_frame_age_seconds", Gauge, "Age of the latest frame in seconds."
    ),
    "reconnects_total": _Definition(
        "mvision_live_reconnects_total", Counter, "Live source reconnect attempts."
    ),
    "active_tracks": _Definition(
        "mvision_live_active_tracks", Gauge, "Currently active tracks."
    ),
    "tracked_objects_total": _Definition(
        "mvision_live_tracked_objects_total", Counter, "Tracked live objects."
    ),
    "eligible_objects_total": _Definition(
        "mvision_live_eligible_objects_total", Counter, "Embedding-eligible live objects."
    ),
    "embeddings_total": _Definition(
        "mvision_live_embeddings_total", Counter, "Produced face embeddings."
    ),
    "missing_embeddings_total": _Definition(
        "mvision_live_missing_embeddings_total", Counter, "Missing face embeddings."
    ),
    "embedding_cosine_samples_total": _Definition(
        "mvision_live_embedding_cosine_samples_total",
        Counter,
        "Consecutive embedding cosine samples.",
    ),
    "quality_rejections_total": _Definition(
        "mvision_live_quality_rejections_total",
        Counter,
        "Rejected face evidence.",
        ("reason",),
    ),
    "protocol_queue_depth": _Definition(
        "mvision_live_protocol_queue_depth",
        Gauge,
        "Current protocol queue depth.",
        ("queue_type",),
    ),
    "protocol_dropped_total": _Definition(
        "mvision_live_protocol_dropped_total",
        Counter,
        "Dropped protocol messages.",
        ("type",),
    ),
    "identity_decisions_total": _Definition(
        "mvision_live_identity_decisions_total",
        Counter,
        "Identity decisions.",
        ("outcome",),
    ),
    "events_total": _Definition(
        "mvision_live_events_total", Counter, "Committed live events.", ("event_type",)
    ),
    "event_suppressions_total": _Definition(
        "mvision_live_event_suppressions_total",
        Counter,
        "Suppressed live events.",
        ("reason",),
    ),
    "output_frames_total": _Definition(
        "mvision_live_output_frames_total", Counter, "Annotated output frames."
    ),
    "websocket_dropped_total": _Definition(
        "mvision_live_websocket_dropped_total", Counter, "Dropped websocket messages."
    ),
    "telemetry_queue_depth": _Definition(
        "mvision_telemetry_queue_depth", Gauge, "Telemetry queue depth.", ("signal",)
    ),
    "telemetry_dropped_total": _Definition(
        "mvision_telemetry_dropped_total",
        Counter,
        "Dropped telemetry records.",
        ("signal", "reason"),
    ),
    "telemetry_export_failures_total": _Definition(
        "mvision_telemetry_export_failures_total",
        Counter,
        "Telemetry export failures.",
        ("signal",),
    ),
    "native_operation_duration_seconds": _Definition(
        "mvision_native_operation_duration_seconds",
        Histogram,
        "Native operation duration in seconds.",
        ("operation", "status"),
    ),
    "trace_sampling_total": _Definition(
        "mvision_live_trace_sampling_total",
        Counter,
        "Live trace sampling decisions.",
        ("decision", "reason"),
    ),
    "dependency_duration_seconds": _Definition(
        "mvision_dependency_duration_seconds",
        Histogram,
        "Dependency operation duration in seconds.",
        ("dependency", "outcome"),
    ),
}


class MvisionMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry
        self._metrics: dict[str, MetricWrapperBase] = {}
        for key, definition in _DEFINITIONS.items():
            metric = definition.kind(
                definition.name,
                definition.documentation,
                definition.labels,
                registry=registry,
            )
            self._metrics[key] = metric
            if definition.labels:
                metric.labels(*("other" for _ in definition.labels))

    @staticmethod
    def _labels(key: str, supplied: dict[str, str]) -> dict[str, str]:
        expected = _DEFINITIONS[key].labels
        if set(supplied) != set(expected):
            raise ValueError("METRIC_LABELS_INVALID")
        return {
            name: value if value in METRIC_LABEL_VALUES[name] else "other"
            for name, value in supplied.items()
        }

    def _child(self, key: str, labels: dict[str, str]) -> MetricWrapperBase:
        if key not in self._metrics:
            raise KeyError("METRIC_NOT_REGISTERED")
        normalized = self._labels(key, labels)
        return self._metrics[key].labels(**normalized) if normalized else self._metrics[key]

    def increment(self, key: str, amount: float = 1, **labels: str) -> None:
        metric = self._child(key, labels)
        if not isinstance(metric, Counter):
            raise TypeError("METRIC_NOT_COUNTER")
        metric.inc(amount)

    def set(self, key: str, value: float, **labels: str) -> None:
        metric = self._child(key, labels)
        if not isinstance(metric, Gauge):
            raise TypeError("METRIC_NOT_GAUGE")
        metric.set(value)

    def observe(self, key: str, value: float, **labels: str) -> None:
        metric = self._child(key, labels)
        if not isinstance(metric, Histogram):
            raise TypeError("METRIC_NOT_HISTOGRAM")
        metric.observe(value)

    def render_metrics(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


_REGISTRIES: weakref.WeakKeyDictionary[CollectorRegistry, MvisionMetrics] = (
    weakref.WeakKeyDictionary()
)
_REGISTRY_LOCK = threading.Lock()


def create_metrics(registry: CollectorRegistry | None = None) -> MvisionMetrics:
    selected = registry or CollectorRegistry()
    with _REGISTRY_LOCK:
        metrics = _REGISTRIES.get(selected)
        if metrics is None:
            metrics = MvisionMetrics(selected)
            _REGISTRIES[selected] = metrics
        return metrics
