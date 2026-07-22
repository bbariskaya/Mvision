import pytest

from scripts.verify_live_observability import (
    AcceptanceError,
    dashboard_has_panels,
    loki_has_trace,
    prometheus_scalar,
    tempo_has_trace,
    wait_for_signal,
)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def test_acceptance_parsers_find_live_signals_without_response_text() -> None:
    prometheus = {
        "status": "success",
        "data": {"resultType": "vector", "result": [{"value": [1, "29.97"]}]},
    }
    tempo = {"traces": [{"traceID": TRACE_ID, "rootServiceName": "mvision-live-worker"}]}
    loki = {
        "status": "success",
        "data": {
            "result": [
                {
                    "stream": {"service_name": "mvision-live-worker"},
                    "values": [["1", "Observability smoke test", {"trace_id": TRACE_ID}]],
                }
            ]
        },
    }
    dashboard = {
        "dashboard": {
            "panels": [
                {"title": "Embedding Coverage"},
                {"title": "Recent Error Traces"},
                {"title": "Correlated Live Logs"},
            ]
        }
    }

    assert prometheus_scalar(prometheus) == pytest.approx(29.97)
    assert tempo_has_trace(tempo, TRACE_ID)
    assert loki_has_trace(loki, TRACE_ID)
    assert dashboard_has_panels(
        dashboard,
        {"Embedding Coverage", "Recent Error Traces", "Correlated Live Logs"},
    )


def test_acceptance_parsers_reject_missing_or_malformed_signals() -> None:
    assert not tempo_has_trace({"traces": []}, TRACE_ID)
    assert not loki_has_trace({"status": "success", "data": {"result": []}}, TRACE_ID)
    assert not dashboard_has_panels(
        {"dashboard": {"panels": []}}, {"Recent Error Traces"}
    )
    with pytest.raises(AcceptanceError, match="OBSERVABILITY_ACCEPTANCE_FAILED"):
        prometheus_scalar({"status": "success", "data": {"result": []}})


def test_loki_parser_accepts_structured_metadata_merged_into_stream_map() -> None:
    payload = {
        "status": "success",
        "data": {
            "result": [
                {
                    "stream": {
                        "service_name": "mvision-live-worker",
                        "trace_id": TRACE_ID,
                    },
                    "values": [["1", "Observability smoke test"]],
                }
            ]
        },
    }

    assert loki_has_trace(payload, TRACE_ID)


def test_wait_for_signal_is_bounded_and_stops_after_success() -> None:
    outcomes = iter((False, False, True))
    sleeps: list[float] = []

    assert wait_for_signal(
        lambda: next(outcomes),
        attempts=4,
        interval_seconds=0.25,
        sleeper=sleeps.append,
    )
    assert sleeps == [0.25, 0.25]
