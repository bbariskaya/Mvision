from app.infrastructure.database.models import (
    LiveConnector,
    LiveSession,
    LiveSessionGeneration,
    LiveSessionRun,
)


def _constraints(model: type) -> str:
    return " ".join(
        str(item.sqltext) for item in model.__table__.constraints if hasattr(item, "sqltext")
    )


def test_live_session_models_have_generation_and_state_constraints() -> None:
    assert LiveSession.__tablename__ == "live_session"
    assert "current_generation >= 1" in _constraints(LiveSession)
    generation_constraints = _constraints(LiveSessionGeneration)
    assert "generation >= 1" in generation_constraints
    assert "rtspPull" in generation_constraints
    assert "whipPush" in generation_constraints
    assert "WAITING_FOR_SOURCE" in generation_constraints
    assert "provisioning" in generation_constraints


def test_live_session_run_and_connector_models_are_separate_from_legacy_camera() -> None:
    assert LiveSessionRun.__tablename__ == "live_session_run"
    assert {column.name for column in LiveSessionRun.__table__.columns} >= {
        "generation_id",
        "runtime_attempt",
        "worker_id",
        "lease_token",
        "lease_expires_at",
    }
    assert "webhook" in _constraints(LiveConnector)
    assert "kafka" in _constraints(LiveConnector)
