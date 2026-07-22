import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.infrastructure.live.native_runner import (
    LiveCommandQueue,
    NativeLiveRunner,
    NativeLiveRunnerError,
)
from app.infrastructure.live.protocol import (
    IdentityAssignment,
    ProtocolHeader,
    StartCommand,
    StopCommand,
    StoppedEvent,
)

CAMERA_ID = "019b0000-0000-7000-8000-000000000001"
RUN_ID = "019b0000-0000-7000-8000-000000000002"
TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
SECRET_URI = "rtsp://admin:secret@camera.invalid/live"


def _header(message_type: str, sequence: int) -> ProtocolHeader:
    return ProtocolHeader(
        1, message_type, CAMERA_ID, RUN_ID, 1, sequence, TRACEPARENT, None
    )


def _start() -> StartCommand:
    return StartCommand(
        _header("start", 1),
        SECRET_URI,
        0,
        "pgie.txt",
        "preprocess.txt",
        "sgie.txt",
        "tracker.yml",
        "/live/camera",
        5400,
        8554,
        200,
        10,
        -1,
        5_000_000_000,
    )


def _stop(sequence: int = 2) -> StopCommand:
    return StopCommand(_header("stop", sequence), "operator", 2_000_000_000)


def _assignment(tracker_id: int, revision: int) -> IdentityAssignment:
    return IdentityAssignment(
        _header("identity_assignment", revision + 1),
        tracker_id,
        revision,
        1,
        "unknown",
        None,
        None,
        None,
        None,
        None,
        revision,
    )


def _executable(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body)
    path.chmod(path.stat().st_mode | 0o111)
    return path


def _settings(executable: Path) -> Settings:
    return Settings(
        _env_file=None,
        live_native_executable=str(executable),
        live_worker_gpu_id=3,
    )


def _worker_script(record_path: Path, *, read_command: bool = False) -> str:
    command_read = "read_frame()" if read_command else "None"
    return f"""
import json, msgpack, struct, sys

def read_frame():
    size = struct.unpack("!I", sys.stdin.buffer.read(4))[0]
    return msgpack.unpackb(sys.stdin.buffer.read(size), raw=False)

def emit(message_type, sequence, **fields):
    payload = {{
        "protocol_version": 1,
        "message_type": message_type,
        "camera_id": "{CAMERA_ID}",
        "run_id": "{RUN_ID}",
        "generation": 1,
        "sequence": sequence,
        "traceparent": "{TRACEPARENT}",
        "tracestate": None,
        **fields,
    }}
    data = msgpack.packb(payload, use_bin_type=True)
    sys.stdout.buffer.write(struct.pack("!I", len(data)) + data)
    sys.stdout.buffer.flush()

start = read_frame()
with open({str(record_path)!r}, "w") as output:
    json.dump({{"argv": sys.argv, "start": start}}, output)
emit("hello", 10, build_id="test", gstreamer_version="1.24", deepstream_version="9")
{command_read}
emit("stopped", 11, decoded_frames=2, emitted_evidence=1, dropped_events=0,
     clean_shutdown=True, reason="operator")
"""


@pytest.mark.asyncio
async def test_runner_uses_secret_free_argv_and_streams_ordered_events(
    tmp_path: Path,
) -> None:
    record_path = tmp_path / "record.json"
    executable = _executable(
        tmp_path / "worker.py", _worker_script(record_path)
    )
    events = []

    result = await NativeLiveRunner(_settings(executable)).run(
        _start(), events.append, LiveCommandQueue(8)
    )

    record = json.loads(record_path.read_text())
    assert record["argv"] == [str(executable), "3"]
    assert record["start"]["uri"] == SECRET_URI
    assert [event.header.sequence for event in events] == [10, 11]
    assert result == events[-1]
    assert isinstance(result, StoppedEvent)


def test_command_queue_coalesces_assignments_by_tracker_and_revision() -> None:
    commands = LiveCommandQueue(2)

    assert commands.put_nowait(_assignment(7, 1))
    assert commands.put_nowait(_assignment(7, 3))
    assert not commands.put_nowait(_assignment(7, 2))
    assert commands.put_nowait(_assignment(8, 1))

    assert commands.get_nowait() == _assignment(7, 3)
    assert commands.get_nowait() == _assignment(8, 1)


@pytest.mark.asyncio
async def test_stop_command_interrupts_event_wait(tmp_path: Path) -> None:
    executable = _executable(
        tmp_path / "worker.py", _worker_script(tmp_path / "record.json", read_command=True)
    )
    commands = LiveCommandQueue(2)
    commands.put_nowait(_stop())

    result = await NativeLiveRunner(_settings(executable)).run(
        _start(), lambda event: None, commands
    )

    assert result.clean_shutdown


@pytest.mark.asyncio
async def test_stderr_is_redacted_and_nonzero_exit_is_sanitized(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    executable = _executable(
        tmp_path / "worker.py",
        f'import sys\nsys.stderr.write("failed {SECRET_URI}\\n")\nsys.exit(7)\n',
    )

    with pytest.raises(NativeLiveRunnerError) as raised:
        await NativeLiveRunner(_settings(executable)).run(
            _start(), lambda event: None, LiveCommandQueue(2)
        )

    assert raised.value.error_code == "LIVE_PIPELINE_ERROR"
    assert SECRET_URI not in str(raised.value)
    assert SECRET_URI not in caplog.text
    assert "Native live worker diagnostic" in caplog.text


@pytest.mark.asyncio
async def test_zero_exit_without_stopped_event_is_failure(tmp_path: Path) -> None:
    executable = _executable(tmp_path / "worker.py", "pass\n")

    with pytest.raises(NativeLiveRunnerError, match="without a stopped event"):
        await NativeLiveRunner(_settings(executable)).run(
            replace(_start(), uri="rtsp://camera.invalid/live"),
            lambda event: None,
            LiveCommandQueue(2),
        )
