import asyncio
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class VideoProbeError(RuntimeError):
    def __init__(self, message: str, code: str = "VIDEO_INVALID"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VideoMetadata:
    container: str
    codec: str
    duration_seconds: float
    fps: float
    width: int
    height: int
    total_frames: int
    rotation_degrees: int


def _fraction(value: object) -> float:
    if not isinstance(value, str) or "/" not in value:
        return 0.0
    numerator, denominator = value.split("/", 1)
    try:
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else 0.0
    except ValueError:
        return 0.0


def _rotation(stream: dict[str, Any]) -> int:
    value: object = (stream.get("tags") or {}).get("rotate", 0)
    for item in stream.get("side_data_list") or []:
        if "rotation" in item:
            value = item["rotation"]
            break
    if not isinstance(value, (str, int, float)):
        return 0
    try:
        return int(round(float(value))) % 360
    except (TypeError, ValueError):
        return 0


def _container(format_name: object) -> str:
    names = {
        value.strip().lower() for value in str(format_name or "").split(",") if value.strip()
    }
    for preferred in ("mp4", "mov", "avi", "matroska"):
        if preferred in names:
            return preferred
    return sorted(names)[0] if names else ""


def parse_probe_payload(payload: bytes) -> VideoMetadata:
    try:
        document = json.loads(payload)
        streams = document.get("streams") or []
        stream = next(item for item in streams if item.get("codec_type") == "video")
        format_data = document.get("format") or {}
        duration = float(format_data.get("duration") or stream.get("duration") or 0)
        fps = _fraction(stream.get("avg_frame_rate")) or _fraction(stream.get("r_frame_rate"))
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        rotation = _rotation(stream)
        frame_value = stream.get("nb_frames")
        try:
            total_frames = int(frame_value)
        except (TypeError, ValueError):
            total_frames = int(round(duration * fps))
        container = _container(format_data.get("format_name"))
        codec = str(stream.get("codec_name") or "").lower()
    except (json.JSONDecodeError, StopIteration, TypeError, ValueError) as exc:
        raise VideoProbeError("Video metadata is invalid") from exc

    if (
        not container
        or not codec
        or not math.isfinite(duration)
        or duration <= 0
        or not math.isfinite(fps)
        or fps <= 0
        or width <= 0
        or height <= 0
        or total_frames <= 0
    ):
        raise VideoProbeError("Video metadata is incomplete")
    if rotation in {90, 270}:
        width, height = height, width
    return VideoMetadata(
        container=container,
        codec=codec,
        duration_seconds=duration,
        fps=fps,
        width=width,
        height=height,
        total_frames=total_frames,
        rotation_degrees=rotation,
    )


async def probe_video(
    path: Path,
    timeout_seconds: float,
    command: tuple[str, ...] = ("ffprobe",),
) -> VideoMetadata:
    process = await asyncio.create_subprocess_exec(
        *command,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise VideoProbeError("Video probe timed out", "VIDEO_PROBE_TIMEOUT") from exc
    if process.returncode != 0:
        diagnostic = stderr.decode(errors="replace").strip()[:512]
        raise VideoProbeError(f"Video probe failed: {diagnostic}")
    return parse_probe_payload(stdout)
