import asyncio
import datetime
from types import SimpleNamespace

import pytest

from app.infrastructure.media.mediamtx_client import MediaMtxError
from app.services.mediamtx_reconciliation_service import (
    MediaMtxReconciliationService,
)


class _Media:
    def __init__(self):
        self.config = {}
        self.active = {}
        self.added = []
        self.replaced = []
        self.deleted = []

    async def get_config_path(self, name):
        return self.config.get(name)

    async def add_path(self, name, config):
        self.added.append((name, config))
        self.config[name] = {"name": name, **config}

    async def replace_path(self, name, config):
        self.replaced.append((name, config))
        self.config[name] = {"name": name, **config}

    async def delete_path(self, name):
        self.deleted.append(name)
        self.config.pop(name, None)

    async def get_active_path(self, name):
        return self.active.get(name)

    async def list_config_paths(self):
        return list(self.config.values())


class _Repo:
    def __init__(self, generations):
        self.generations = generations
        self.states = []

    async def list_reconcilable(self, session):
        return self.generations

    async def set_media_state(self, session, generation_id, state, error_code=None):
        self.states.append((generation_id, state, error_code))


class _Cipher:
    def decrypt_secret(self, ciphertext):
        return {"cipher-rtsp": "rtsp://user:secret@camera/live"}[ciphertext]


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        pass


def _generation(**overrides):
    values = {
        "generation_id": "generation-1",
        "source_type": "rtspPull",
        "source_ciphertext": "cipher-rtsp",
        "ingress_path": "ingress/opaque-one",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_reconcile_adds_missing_path_and_marks_waiting() -> None:
    media = _Media()
    repo = _Repo([_generation()])
    service = MediaMtxReconciliationService(media, repo, _Cipher(), session_factory=_Session)

    result = await service.reconcile()

    assert media.added == [
        (
            "ingress/opaque-one",
            {
                "source": "rtsp://user:secret@camera/live",
                "rtspTransport": "tcp",
            },
        )
    ]
    assert repo.states == [("generation-1", "waiting", None)]
    assert result.added == 1


@pytest.mark.asyncio
async def test_reconcile_replaces_drift_and_uses_online_readiness() -> None:
    media = _Media()
    media.config["ingress/opaque-one"] = {
        "name": "ingress/opaque-one",
        "source": "rtsp://wrong/live",
        "rtspTransport": "udp",
    }
    media.active["ingress/opaque-one"] = {"online": True, "ready": False}
    repo = _Repo([_generation()])
    service = MediaMtxReconciliationService(media, repo, _Cipher(), session_factory=_Session)

    result = await service.reconcile()

    assert len(media.replaced) == 1
    assert repo.states == [("generation-1", "ready", None)]
    assert result.ready == 1


@pytest.mark.asyncio
async def test_stale_owned_path_is_deleted_only_after_grace() -> None:
    media = _Media()
    media.config["ingress/stale"] = {
        "name": "ingress/stale",
        "source": "publisher",
    }
    repo = _Repo([])
    now = datetime.datetime(2026, 7, 23, tzinfo=datetime.UTC)
    service = MediaMtxReconciliationService(
        media,
        repo,
        _Cipher(),
        session_factory=_Session,
        stale_grace_seconds=30,
        clock=lambda: now,
    )

    await service.reconcile()
    assert media.deleted == []

    now += datetime.timedelta(seconds=31)
    result = await service.reconcile()

    assert media.deleted == ["ingress/stale"]
    assert result.deleted == 1


@pytest.mark.asyncio
async def test_reconcile_never_deletes_paths_outside_owned_prefix() -> None:
    media = _Media()
    media.config["customer/path"] = {"name": "customer/path", "source": "publisher"}
    service = MediaMtxReconciliationService(
        media, _Repo([]), _Cipher(), session_factory=_Session, stale_grace_seconds=0
    )

    await service.reconcile()

    assert media.deleted == []


@pytest.mark.asyncio
async def test_control_api_outage_preserves_generation_failure_state() -> None:
    class _UnavailableMedia(_Media):
        async def get_config_path(self, name):
            raise MediaMtxError("MEDIAMTX_UNAVAILABLE")

        async def list_config_paths(self):
            raise MediaMtxError("MEDIAMTX_UNAVAILABLE")

    repo = _Repo([_generation()])
    service = MediaMtxReconciliationService(
        _UnavailableMedia(), repo, _Cipher(), session_factory=_Session
    )

    result = await service.reconcile()

    assert result.failed == 1
    assert repo.states == [("generation-1", "failed", "LIVE_MEDIA_PATH_FAILED")]


@pytest.mark.asyncio
async def test_reconciliation_cycles_do_not_overlap() -> None:
    class _ConcurrencyProbeMedia(_Media):
        def __init__(self):
            super().__init__()
            self.active_calls = 0
            self.maximum_active_calls = 0

        async def get_config_path(self, name):
            self.active_calls += 1
            self.maximum_active_calls = max(self.maximum_active_calls, self.active_calls)
            await asyncio.sleep(0)
            self.active_calls -= 1
            return await super().get_config_path(name)

    media = _ConcurrencyProbeMedia()
    service = MediaMtxReconciliationService(
        media, _Repo([_generation()]), _Cipher(), session_factory=_Session
    )

    await asyncio.gather(service.reconcile(), service.reconcile())

    assert media.maximum_active_calls == 1
