import json
import os
from pathlib import Path

import yaml

ROOT = Path(os.getenv("MVISION_REPO_ROOT", Path(__file__).resolve().parents[3]))
CONFIG = ROOT / "configs" / "observability"

EXPECTED_DIGESTS = {
    "otel-collector": "sha256:4eb842091c796156d4d3c994eb22ba793590f5723719dbf6b8436cb4dfc17f48",
    "prometheus": "sha256:0e698e35e50d1ddc2d11a4a55b089fe62eb71358a5c204dfafd21bdf8ffe04b8",
    "loki": "sha256:d14b3a2c419b72fe27cd094c017863bd37a5ea9ac7d72f35bcd25f5bd081dc47",
    "tempo": "sha256:3ecd1da98d89d49ea7ba3b0b283487e06f09ca3d9422a61fdde310f93b3e6e4d",
    "grafana": "sha256:6ea068891652aa6a65ca9065c26b89de939653803c836426970305c11fd00534",
}


def _yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def test_observability_compose_is_digest_pinned_internal_and_isolated() -> None:
    compose = _yaml(ROOT / "docker-compose.observability.yml")
    services = compose["services"]
    for service, digest in EXPECTED_DIGESTS.items():
        assert services[service]["image"].endswith(f"@{digest}")
        assert services[service].get("healthcheck")
    for service in ("otel-collector", "prometheus", "loki", "tempo"):
        assert "ports" not in services[service]
        assert services[service].get("expose")
    assert services["grafana"]["environment"]["GF_SECURITY_ADMIN_PASSWORD"] == (
        "${GRAFANA_ADMIN_PASSWORD}"
    )
    volumes = set(compose["volumes"])
    assert {
        "otel_data",
        "prometheus_data",
        "loki_data",
        "tempo_data",
        "grafana_data",
    } <= volumes
    assert not volumes & {"postgres_data", "qdrant_data", "minio_data"}


def test_collector_has_bounded_privacy_first_pipelines_and_tail_sampling() -> None:
    collector = _yaml(CONFIG / "otel-collector.yml")
    assert set(collector["receivers"]["otlp"]["protocols"]) == {"grpc", "http"}
    processors = collector["processors"]
    assert processors["memory_limiter"]["limit_mib"] > 0
    assert processors["batch"]["send_batch_max_size"] <= processors["memory_limiter"][
        "limit_mib"
    ] * 10
    policies = processors["tail_sampling"]["policies"]
    assert {policy["name"] for policy in policies} == {
        "errors",
        "reconnects",
        "slow-operations",
        "ordinary-success-10-percent",
    }
    assert next(
        policy for policy in policies if policy["name"] == "ordinary-success-10-percent"
    )["probabilistic"]["sampling_percentage"] == 10
    for pipeline in collector["service"]["pipelines"].values():
        configured = pipeline.get("processors", [])
        if "batch" in configured:
            assert configured.index("memory_limiter") < configured.index("batch")
    for exporter in ("otlp_grpc/tempo", "otlp_http/loki"):
        queue = collector["exporters"][exporter]["sending_queue"]
        assert queue["enabled"] is True
        assert 0 < queue["queue_size"] <= 4096
        assert collector["exporters"][exporter]["retry_on_failure"]["enabled"] is True
    assert collector["exporters"]["otlp_http/loki"]["endpoint"] == (
        "http://loki:3100/otlp"
    )
    actions = collector["processors"]["attributes/privacy"]["actions"]
    deleted = {action["key"] for action in actions if action["action"] == "delete"}
    assert {"url.full", "server.address", "db.statement", "enduser.id"} <= deleted


def test_retention_and_scrape_contracts() -> None:
    prometheus = _yaml(CONFIG / "prometheus.yml")
    targets = {
        target
        for job in prometheus["scrape_configs"]
        for item in job["static_configs"]
        for target in item["targets"]
    }
    assert {
        "mvision-live-api:8000",
        "mvision-live-worker:9464",
        "otel-collector:8888",
        "otel-collector:8889",
        "loki:3100",
        "tempo:3200",
    } <= targets
    loki = _yaml(CONFIG / "loki.yml")
    assert loki["compactor"]["retention_enabled"] is True
    assert loki["limits_config"]["retention_period"] == "168h"
    tempo = _yaml(CONFIG / "tempo.yml")
    assert tempo["overrides"]["defaults"]["compaction"]["block_retention"] == "168h"
    compose = _yaml(ROOT / "docker-compose.observability.yml")
    assert "--storage.tsdb.retention.time=15d" in compose["services"]["prometheus"][
        "command"
    ]


def test_live_compose_delivers_no_literal_secret_and_internal_metrics_only() -> None:
    compose = _yaml(ROOT / "docker-compose.live.yml")
    worker = compose["services"]["live-worker-0"]
    assert worker["command"] == ["python3", "-m", "app.worker.live_worker_main"]
    assert worker["environment"]["LIVE_URI_ENCRYPTION_KEYS"] == (
        "${LIVE_URI_ENCRYPTION_KEYS}"
    )
    assert worker["environment"]["LIVE_URI_FINGERPRINT_KEY"] == (
        "${LIVE_URI_FINGERPRINT_KEY}"
    )
    assert worker["expose"] == ["9464"]
    assert worker["ports"] == ["8554:8554"]
    assert worker["deploy"]["resources"]["reservations"]["devices"][0][
        "device_ids"
    ] == ["0"]


def test_grafana_datasources_dashboards_and_alerts_are_fully_provisioned() -> None:
    grafana = CONFIG / "grafana"
    datasources = _yaml(grafana / "provisioning/datasources/mvision.yml")
    by_uid = {item["uid"]: item for item in datasources["datasources"]}
    assert set(by_uid) == {"prometheus", "loki", "tempo"}
    assert by_uid["tempo"]["jsonData"]["serviceMap"]["datasourceUid"] == "prometheus"
    assert by_uid["tempo"]["jsonData"]["tracesToLogsV2"]["datasourceUid"] == "loki"
    assert by_uid["tempo"]["jsonData"]["tracesToMetrics"]["datasourceUid"] == (
        "prometheus"
    )
    assert by_uid["loki"]["jsonData"]["derivedFields"][0]["datasourceUid"] == "tempo"

    expected = {
        "mvision-live-operations": "Live Camera Operations",
        "mvision-recognition-quality": "Recognition Quality",
        "mvision-protocol-backpressure": "Protocol Backpressure",
        "mvision-dependencies": "Dependency Health",
        "mvision-telemetry-health": "Telemetry Health",
    }
    found = {}
    for path in (grafana / "dashboards").glob("*.json"):
        dashboard = json.loads(path.read_text())
        found[dashboard["uid"]] = dashboard["title"]
        assert dashboard["panels"]
        assert all(panel.get("targets") for panel in dashboard["panels"])
        serialized = json.dumps(dashboard).lower()
        for prohibited in ("camera_id", "run_id", "track_id", "face_id", "rtsp"):
            assert prohibited not in serialized
    assert found == expected

    live = json.loads(
        (grafana / "dashboards/live-camera-operations.json").read_text()
    )
    panels = {panel["title"]: panel for panel in live["panels"]}
    assert live["version"] == 3
    assert {
        "Worker Up",
        "Runtime State",
        "Current FPS",
        "Face Load / 100 Frames",
        "Embedding Coverage",
        "Pipeline Throughput",
        "Recognition Yield",
        "Missing Embeddings",
        "Native Operation p95",
        "Reconnects (5m)",
        "Protocol Drops (5m)",
        "Telemetry Failures (5m)",
        "Recent Error Traces",
        "Correlated Live Logs",
    } == set(panels)
    assert panels["Recent Error Traces"]["datasource"]["uid"] == "tempo"
    assert panels["Correlated Live Logs"]["datasource"]["uid"] == "loki"
    assert "status = error" in panels["Recent Error Traces"]["targets"][0]["query"]
    assert "trace_id" in panels["Correlated Live Logs"]["targets"][0]["expr"]
    assert "mvision_live_tracked_objects_total" in panels[
        "Face Load / 100 Frames"
    ]["targets"][0]["expr"]
    assert "Events and Output" not in panels

    alerts = _yaml(grafana / "provisioning/alerting/mvision-live.yml")
    rules = [rule for group in alerts["groups"] for rule in group["rules"]]
    assert len(rules) == 9
    assert {rule["uid"] for rule in rules} == {
        "live-worker-down",
        "live-no-frames",
        "live-stale-frame",
        "live-reconnect-storm",
        "live-missing-embeddings",
        "live-queue-pressure",
        "live-dropped-events",
        "telemetry-export-failures",
        "dependency-high-latency",
    }
