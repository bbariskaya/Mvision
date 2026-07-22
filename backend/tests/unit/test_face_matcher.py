from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.face_matcher import FaceMatcher


class _Qdrant:
    def __init__(self):
        self.search_batch_calls = 0

    async def search(self, *_args, **_kwargs):
        return [
            {"sample_id": "sample-1", "score": 0.75, "payload": {"face_id": "face-1"}},
            {"sample_id": "sample-2", "score": 0.65, "payload": {"face_id": "face-2"}},
        ]

    async def search_batch(self, vectors, *_args, **_kwargs):
        self.search_batch_calls += 1
        return [await self.search() for _vector in vectors]


class _Identities:
    async def get_active_by_id(self, _session, face_id):
        if face_id == "face-1":
            return SimpleNamespace(face_id=face_id, lifecycle_status="known")
        return None


@pytest.mark.asyncio
async def test_candidates_return_active_identities_above_floor(monkeypatch):
    @asynccontextmanager
    async def session_factory():
        yield object()

    monkeypatch.setattr("app.services.face_matcher.AsyncSessionLocal", session_factory)
    matcher = FaceMatcher(Settings(), _Identities(), _Qdrant())

    candidates = await matcher.candidates([1.0] + [0.0] * 511, minimum_score=0.7)

    assert [(item.identity.face_id, item.sample_id, item.score) for item in candidates] == [
        ("face-1", "sample-1", 0.75)
    ]


@pytest.mark.asyncio
async def test_candidates_batch_uses_one_vector_store_request(monkeypatch):
    @asynccontextmanager
    async def session_factory():
        yield object()

    monkeypatch.setattr("app.services.face_matcher.AsyncSessionLocal", session_factory)
    qdrant = _Qdrant()
    matcher = FaceMatcher(Settings(), _Identities(), qdrant)

    candidates = await matcher.candidates_batch(
        [[1.0] + [0.0] * 511, [0.0, 1.0] + [0.0] * 510], minimum_score=0.7
    )

    assert qdrant.search_batch_calls == 1
    assert [[item.identity.face_id for item in group] for group in candidates] == [
        ["face-1"],
        ["face-1"],
    ]
