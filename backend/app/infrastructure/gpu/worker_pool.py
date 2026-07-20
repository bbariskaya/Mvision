import asyncio
import itertools
import socket
import struct
import threading

from app.infrastructure.gpu.contracts import ImageRequest, ImageResult
from app.infrastructure.gpu.protocol import (
    HEADER_SIZE,
    MAX_FRAME_BYTES,
    decode_result,
    encode_request,
)


class GpuWorkerError(RuntimeError):
    pass


def _read_exact(stream: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.recv(size - len(data))
        if not chunk:
            raise GpuWorkerError("GPU worker closed the socket")
        data.extend(chunk)
    return bytes(data)


class GpuWorkerPool:
    def __init__(self, socket_paths: list[str], timeout_seconds: float = 120.0):
        if not socket_paths:
            raise ValueError("At least one GPU worker socket is required")
        self._paths = tuple(socket_paths)
        self._timeout = timeout_seconds
        self._counter = itertools.count()
        self._counter_lock = threading.Lock()

    def _next_path(self) -> str:
        with self._counter_lock:
            return self._paths[next(self._counter) % len(self._paths)]

    def _process_sync(self, encoded_jpeg: bytes, request_id: str) -> ImageResult:
        path = self._next_path()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(self._timeout)
                stream.connect(path)
                stream.sendall(struct.pack("!I", 1))
                request = ImageRequest(request_id=request_id, encoded_jpeg=encoded_jpeg)
                stream.sendall(encode_request(request))
                header = _read_exact(stream, HEADER_SIZE)
                payload_size = struct.unpack("!I", header)[0]
                if payload_size > MAX_FRAME_BYTES:
                    raise GpuWorkerError("GPU worker response is too large")
                result = decode_result(header + _read_exact(stream, payload_size))
        except (OSError, TimeoutError, ValueError) as exc:
            raise GpuWorkerError(f"GPU worker unavailable: {exc}") from exc
        if result.request_id != request_id:
            raise GpuWorkerError("GPU worker returned a mismatched request ID")
        if result.status != "OK":
            raise GpuWorkerError(result.error_code or "GPU worker failed")
        return result

    async def process(self, encoded_jpeg: bytes, request_id: str) -> ImageResult:
        return await asyncio.to_thread(self._process_sync, encoded_jpeg, request_id)
