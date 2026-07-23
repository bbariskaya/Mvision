import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.infrastructure.database.models import VideoJob
from app.infrastructure.video.native_runner import (
    NativeVideoCancelledError,
    NativeVideoFailedError,
    NativeVideoRunner,
    NativeVideoTimeoutError,
)
from app.infrastructure.video.protocol import VideoCompleted, VideoProgress


def _job() -> VideoJob:
    now = datetime.now(UTC)
    return VideoJob(
        job_id="019f8000-0000-7000-8000-000000000001",
        process_id="019f8000-0000-7000-8000-000000000002",
        status="processing",
        stage="starting",
        progress_percent=0,
        attempt_count=1,
        max_attempts=3,
        available_at=now,
        source_bucket="videos",
        source_object_key="videos/019f8000-0000-7000-8000-000000000001/source",
        source_content_type="video/mp4",
        source_size=5,
        source_sha256="0" * 64,
        source_retention_until=now + timedelta(days=7),
        container_format="mp4",
        video_codec="h264",
        duration_seconds=1,
        fps=25,
        width=640,
        height=480,
        total_frames=25,
        processed_frames=0,
        sampling={"everyNFrames": 5},
    )


def _executable(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body)
    path.chmod(path.stat().st_mode | 0o111)
    return path


@pytest.mark.asyncio
async def test_runner_streams_events_until_completed(tmp_path: Path):
    executable = _executable(
        tmp_path / "events.py",
        """
import msgpack, struct, sys
for payload in (
    {"protocol_version": 1, "event_type": "progress", "decoded_frame": 5,
     "processed_frames": 1, "total_frames": 25, "progress_percent": 20.0},
    {"protocol_version": 1, "event_type": "completed", "decoded_frames": 25,
     "processed_frames": 5, "track_count": 0},
):
    data = msgpack.packb(payload, use_bin_type=True)
    sys.stdout.buffer.write(struct.pack("!I", len(data)) + data)
    sys.stdout.buffer.flush()
""",
    )
    settings = Settings(_env_file=None, video_native_executable=str(executable))
    events = []

    result = await NativeVideoRunner(settings).run(
        _job(),
        tmp_path / "input.mp4",
        events.append,
        lambda: False,
    )

    assert isinstance(events[0], VideoProgress)
    assert result == VideoCompleted(25, 5, 0)


@pytest.mark.asyncio
async def test_runner_terminates_when_cancellation_is_requested(tmp_path: Path):
    executable = _executable(
        tmp_path / "sleep.py",
        """
import time
while True:
    time.sleep(1)
""",
    )
    settings = Settings(_env_file=None, video_native_executable=str(executable))
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    with pytest.raises(NativeVideoCancelledError):
        await NativeVideoRunner(settings, poll_seconds=0.02).run(
            _job(),
            tmp_path / "input.mp4",
            lambda event: None,
            cancelled,
        )


@pytest.mark.asyncio
async def test_runner_rejects_success_without_completed_event(tmp_path: Path):
    executable = _executable(tmp_path / "empty.py", "pass\n")
    settings = Settings(_env_file=None, video_native_executable=str(executable))

    with pytest.raises(RuntimeError, match="without a completed event"):
        await NativeVideoRunner(settings).run(
            _job(),
            tmp_path / "input.mp4",
            lambda event: None,
            lambda: False,
        )


@pytest.mark.asyncio
async def test_runner_preserves_native_failed_event_code(tmp_path: Path):
    executable = _executable(
        tmp_path / "failed.py",
        """
import msgpack, struct, sys
payload = {"protocol_version": 1, "event_type": "failed",
           "error_code": "VIDEO_DECODE_FAILED", "message": "decode failed"}
data = msgpack.packb(payload, use_bin_type=True)
sys.stdout.buffer.write(struct.pack("!I", len(data)) + data)
sys.stdout.buffer.flush()
""",
    )
    settings = Settings(_env_file=None, video_native_executable=str(executable))

    with pytest.raises(NativeVideoFailedError) as exc:
        await NativeVideoRunner(settings).run(
            _job(), tmp_path / "input.mp4", lambda event: None, lambda: False
        )

    assert exc.value.error_code == "VIDEO_DECODE_FAILED"


@pytest.mark.asyncio
async def test_runner_raises_stable_timeout_error(tmp_path: Path):
    executable = _executable(
        tmp_path / "timeout.py",
        """
import time
time.sleep(5)
""",
    )
    settings = Settings(
        _env_file=None,
        video_native_executable=str(executable),
        video_job_timeout_seconds=1,
    )

    with pytest.raises(NativeVideoTimeoutError) as exc:
        await NativeVideoRunner(settings, poll_seconds=0.02).run(
            _job(), tmp_path / "input.mp4", lambda event: None, lambda: False
        )

    assert exc.value.error_code == "VIDEO_PROCESSING_TIMEOUT"


def test_fake_executable_is_runnable(tmp_path: Path):
    executable = _executable(tmp_path / "ok.py", "pass\n")
    assert os.access(executable, os.X_OK)
