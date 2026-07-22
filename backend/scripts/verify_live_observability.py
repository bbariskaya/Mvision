import argparse
import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

ERROR_CODE = "OBSERVABILITY_SMOKE_TEST"
FAILURE_CODE = "OBSERVABILITY_ACCEPTANCE_FAILED"
MAX_RESPONSE_BYTES = 1024 * 1024
TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class AcceptanceError(RuntimeError):
    pass


def _fail() -> AcceptanceError:
    return AcceptanceError(FAILURE_CODE)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail()
    return value


def prometheus_scalar(payload: object) -> float:
    root = _mapping(payload)
    data = _mapping(root.get("data"))
    result_type = data.get("resultType")
    result = data.get("result")
    if result_type == "scalar" and isinstance(result, list) and len(result) == 2:
        raw_value = result[1]
    elif result_type == "vector" and isinstance(result, list) and result:
        sample = _mapping(result[0])
        value = sample.get("value")
        if not isinstance(value, list) or len(value) != 2:
            raise _fail()
        raw_value = value[1]
    else:
        raise _fail()
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise _fail() from exc
    if not math.isfinite(parsed):
        raise _fail()
    return parsed


def tempo_has_trace(payload: object, trace_id: str) -> bool:
    if not TRACE_ID_PATTERN.fullmatch(trace_id):
        return False
    try:
        traces = _mapping(payload).get("traces")
        if not isinstance(traces, list):
            return False
        return any(
            isinstance(item, Mapping)
            and str(item.get("traceID", "")).lower() == trace_id
            for item in traces
        )
    except (AcceptanceError, TypeError, ValueError):
        return False


def loki_has_trace(payload: object, trace_id: str) -> bool:
    if not TRACE_ID_PATTERN.fullmatch(trace_id):
        return False
    try:
        results = _mapping(_mapping(payload).get("data")).get("result")
        if not isinstance(results, list):
            return False
        for stream in results:
            result = _mapping(stream)
            metadata = result.get("stream")
            if isinstance(metadata, Mapping) and str(
                metadata.get("trace_id", "")
            ).lower() == trace_id:
                return True
            values = result.get("values")
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, list) or len(value) < 2:
                    continue
                metadata = value[2] if len(value) > 2 else None
                if isinstance(metadata, Mapping) and str(
                    metadata.get("trace_id", "")
                ).lower() == trace_id:
                    return True
                if trace_id in str(value[1]).lower():
                    return True
        return False
    except (AcceptanceError, TypeError, ValueError):
        return False


def dashboard_has_panels(payload: object, required: set[str]) -> bool:
    try:
        dashboard = _mapping(_mapping(payload).get("dashboard"))
        pending = dashboard.get("panels")
        if not isinstance(pending, list):
            return False
        titles: set[str] = set()
        stack = list(pending)
        while stack:
            panel = stack.pop()
            if not isinstance(panel, Mapping):
                continue
            title = panel.get("title")
            if isinstance(title, str):
                titles.add(title)
            children = panel.get("panels")
            if isinstance(children, list):
                stack.extend(children)
        return required <= titles
    except (AcceptanceError, TypeError, ValueError):
        return False


def _fetch_json(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
) -> object:
    try:
        with client.stream("GET", url, params=params) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise _fail()
        return json.loads(body)
    except AcceptanceError:
        raise
    except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _fail() from exc


def wait_for_signal(
    probe: Callable[[], bool],
    *,
    attempts: int = 16,
    interval_seconds: float = 2.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    bounded_attempts = max(attempts, 1)
    for attempt in range(bounded_attempts):
        if probe():
            return True
        if attempt + 1 < bounded_attempts:
            sleeper(interval_seconds)
    return False


def _verify(client: httpx.Client, grafana_url: str, trace_id: str) -> None:
    base = grafana_url.rstrip("/")
    dashboard = _fetch_json(
        client, f"{base}/api/dashboards/uid/mvision-live-operations"
    )
    if not dashboard_has_panels(
        dashboard,
        {"Embedding Coverage", "Recent Error Traces", "Correlated Live Logs"},
    ):
        raise _fail()
    print("PASS dashboard")

    prometheus = _fetch_json(
        client,
        f"{base}/api/datasources/proxy/uid/prometheus/api/v1/query",
        params={
            "query": 'sum(rate(mvision_live_frames_total{job="mvision-live-worker"}[1m]))'
        },
    )
    if prometheus_scalar(prometheus) <= 0:
        raise _fail()
    print("PASS prometheus")

    def tempo_ready() -> bool:
        payload = _fetch_json(
            client,
            f"{base}/api/datasources/proxy/uid/tempo/api/search",
            params={
                "q": (
                    '{ resource.service.name = "mvision-live-worker" '
                    f'&& span.error_code = "{ERROR_CODE}" }}'
                ),
                "limit": "20",
            },
        )
        return tempo_has_trace(payload, trace_id)

    if not wait_for_signal(tempo_ready):
        raise _fail()
    print("PASS tempo")

    def loki_ready() -> bool:
        payload = _fetch_json(
            client,
            f"{base}/api/datasources/proxy/uid/loki/loki/api/v1/query_range",
            params={
                "query": (
                    '{service_name="mvision-live-worker"} '
                    f'| trace_id=`{trace_id}`'
                ),
                "direction": "backward",
                "limit": "100",
            },
        )
        return loki_has_trace(payload, trace_id)

    if not wait_for_signal(loki_ready):
        raise _fail()
    print("PASS loki")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify live LGTM observability signals.")
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--grafana-url", default="http://127.0.0.1:3001")
    args = parser.parse_args()

    trace_id = args.trace_id.lower()
    username = os.getenv("GRAFANA_USER", "admin")
    password = os.getenv("GRAFANA_PASSWORD")
    if not TRACE_ID_PATTERN.fullmatch(trace_id) or not password:
        print(FAILURE_CODE)
        return 1

    try:
        with httpx.Client(
            auth=httpx.BasicAuth(username, password),
            timeout=5.0,
        ) as client:
            _verify(client, args.grafana_url, trace_id)
    except AcceptanceError:
        print(FAILURE_CODE)
        return 1
    print(f"PASS trace_id={trace_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
