import pytest

from app.config import Settings
from tests.integration import conftest as integration_fixtures


def test_integration_stores_reject_production_names() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://mergen:mergen@postgres:5432/mergenvision",
        qdrant_collection="face_samples_arcface_r50_webface_v1",
        minio_bucket_faces="mergenvision-faces",
        minio_bucket_videos="mergenvision-videos",
    )

    with pytest.raises(RuntimeError, match="isolated test stores"):
        integration_fixtures.require_isolated_settings(settings)


def test_integration_stores_accept_test_names() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://mergen:mergen@postgres:5432/mergenvision_test",
        qdrant_collection="face_samples_test",
        minio_bucket_faces="mergenvision-faces-test",
        minio_bucket_videos="mergenvision-videos-test",
    )

    integration_fixtures.require_isolated_settings(settings)
