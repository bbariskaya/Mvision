import asyncio
import inspect
import logging
import struct
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable

from app.config import Settings
from app.infrastructure.live.protocol import (
    HEADER_SIZE,
    MAX_FRAME_BYTES,
    DecodeContext,
    IdentityAssignment,
    LiveMessage,
    StartCommand,
    StopCommand,
    StoppedEvent,
    encode_message,
)
from app.infrastructure.live.uri_cipher import redact_live_text

logger = logging.getLogger(__name__)

EventHandler = Callable[[LiveMessage], Awaitable[None] | None]
LiveCommand = IdentityAssignment | StopCommand


class NativeLiveRunnerError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        super().__init__(redact_live_text(message))


class LiveCommandQueue:
    def __init__(self, assignment_capacity: int):
        if assignment_capacity < 1:
            raise ValueError("LIVE_COMMAND_CAPACITY_INVALID")
        self._assignment_capacity = assignment_capacity
        self._controls: deque[StopCommand] = deque()
        self._assignments: OrderedDict[int, IdentityAssignment] = OrderedDict()
        self._available = asyncio.Event()

    def put_nowait(self, command: LiveCommand) -> bool:
        if isinstance(command, StopCommand):
            self._controls.append(command)
            self._available.set()
            return True
        previous = self._assignments.get(command.tracker_id)
        if previous is not None:
            if command.assignment_revision <= previous.assignment_revision:
                return False
            self._assignments[command.tracker_id] = command
            self._available.set()
            return True
        if len(self._assignments) >= self._assignment_capacity:
            self._assignments.popitem(last=False)
        self._assignments[command.tracker_id] = command
        self._available.set()
        return True

    def get_nowait(self) -> LiveCommand:
        if self._controls:
            return self._controls.popleft()
        if self._assignments:
            _, command = self._assignments.popitem(last=False)
            return command
        raise asyncio.QueueEmpty

    async def get(self) -> LiveCommand:
        while True:
            try:
                return self.get_nowait()
            except asyncio.QueueEmpty:
                self._available.clear()
                await self._available.wait()


class NativeLiveRunner:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def run(
        self,
        start: StartCommand,
        on_event: EventHandler,
        commands: LiveCommandQueue,
    ) -> StoppedEvent:
        process = await asyncio.create_subprocess_exec(
            self._settings.live_native_executable,
            str(self._settings.live_worker_gpu_id),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            await self._terminate(process)
            raise NativeLiveRunnerError("LIVE_PIPELINE_ERROR", "Native pipes unavailable")

        process.stdin.write(encode_message(start))
        await process.stdin.drain()
        stderr_task = asyncio.create_task(self._drain_stderr(process.stderr))
        writer_task = asyncio.create_task(self._write_commands(process.stdin, commands))
        reader_task = asyncio.create_task(
            self._read_events(process.stdout, start, on_event)
        )
        try:
            stopped = await reader_task
            return_code = await process.wait()
            if return_code != 0:
                raise NativeLiveRunnerError(
                    "LIVE_PIPELINE_ERROR",
                    f"Native live worker exited with code {return_code}",
                )
            if stopped is None:
                raise NativeLiveRunnerError(
                    "LIVE_PIPELINE_ERROR",
                    "Native live worker exited without a stopped event",
                )
            return stopped
        except NativeLiveRunnerError:
            raise
        except Exception as exc:
            raise NativeLiveRunnerError("LIVE_PIPELINE_ERROR", str(exc)) from exc
        finally:
            writer_task.cancel()
            await asyncio.gather(writer_task, return_exceptions=True)
            if process.returncode is None:
                await self._terminate(process)
            await stderr_task

    @staticmethod
    async def _read_events(
        stdout: asyncio.StreamReader,
        start: StartCommand,
        on_event: EventHandler,
    ) -> StoppedEvent | None:
        context = DecodeContext(
            start.header.camera_id, start.header.run_id, start.header.generation
        )
        previous_sequence = -1
        stopped = None
        while True:
            try:
                header = await stdout.readexactly(HEADER_SIZE)
            except asyncio.IncompleteReadError as exc:
                if not exc.partial:
                    return stopped
                raise ValueError("TRUNCATED_FRAME") from exc
            frame_size = struct.unpack("!I", header)[0]
            if frame_size > MAX_FRAME_BYTES:
                raise ValueError("FRAME_TOO_LARGE")
            try:
                body = await stdout.readexactly(frame_size)
            except asyncio.IncompleteReadError as exc:
                raise ValueError("TRUNCATED_FRAME") from exc
            event = context.decode(header + body)
            if event.header.sequence <= previous_sequence:
                raise ValueError("OUT_OF_ORDER_SEQUENCE")
            previous_sequence = event.header.sequence
            result = on_event(event)
            if inspect.isawaitable(result):
                await result
            if isinstance(event, StoppedEvent):
                stopped = event

    @staticmethod
    async def _write_commands(
        stdin: asyncio.StreamWriter, commands: LiveCommandQueue
    ) -> None:
        while True:
            command = await commands.get()
            stdin.write(encode_message(command))
            await stdin.drain()

    @staticmethod
    async def _drain_stderr(stderr: asyncio.StreamReader) -> None:
        while line := await stderr.readline():
            text = redact_live_text(line.decode("utf-8", errors="replace").rstrip())
            if text:
                logger.warning("Native live worker: %s", text)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
