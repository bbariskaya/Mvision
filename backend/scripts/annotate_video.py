"""Render persisted video recognition detections into an annotated MP4."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _escape_text(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def build_ass(result: dict[str, Any]) -> tuple[str, int]:
    video = result["video"]
    width = int(video["width"])
    height = int(video["height"])
    duration = float(video["duration"])
    effective_fps = float(video["sampling"].get("effectiveFramesPerSecond") or 1.0)
    half_window = 0.5 / max(effective_fps, 0.01)
    style_format = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    default_style = (
        "Style: Default,DejaVu Sans,24,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,2,0,7,0,0,0,1"
    )
    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            style_format,
            default_style,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            "",
        ]
    )
    events: list[str] = []
    for person_index, person in enumerate(result["persons"], start=1):
        known = person["status"] == "known"
        color = "00FF00" if known else "008CFF"
        name = person["name"] if known else "Unknown"
        for detection in person["detections"]:
            timestamp = float(detection["timestamp"])
            start = _ass_time(max(0.0, timestamp - half_window))
            end = _ass_time(min(duration, timestamp + half_window))
            box = detection["boundingBox"]
            x = max(0, min(width - 1, round(float(box["x"]))))
            y = max(0, min(height - 1, round(float(box["y"]))))
            box_width = max(1, min(width - x, round(float(box["width"]))))
            box_height = max(1, min(height - y, round(float(box["height"]))))
            label = _escape_text(
                f'{name} | cos {float(person["confidence"]):.3f} | '
                f'det {float(detection["confidence"]):.3f}'
            )
            drawing = (
                f"{{\\an7\\pos({x},{y})\\p1\\bord3\\shad0"
                f"\\1a&HFF&\\3c&H{color}&}}"
                f"m 0 0 l {box_width} 0 l {box_width} {box_height} l 0 {box_height} l 0 0"
            )
            label_y = max(0, y - 30)
            text = (
                f"{{\\an7\\pos({x},{label_y})\\p0\\bord2\\shad0"
                f"\\1c&HFFFFFF&\\3c&H{color}&}}{label}"
            )
            events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{drawing}")
            events.append(f"Dialogue: 1,{start},{end},Default,,0,0,0,,{text}")
            for landmark in detection.get("landmarks", []):
                landmark_x = max(0, min(width - 1, round(float(landmark["x"]))))
                landmark_y = max(0, min(height - 1, round(float(landmark["y"]))))
                dot = (
                    f"{{\\an5\\pos({landmark_x},{landmark_y})\\p1\\bord0\\shad0"
                    f"\\1c&H{color}&}}m -3 -3 l 3 -3 l 3 3 l -3 3 l -3 -3"
                )
                events.append(f"Dialogue: 2,{start},{end},Default,,0,0,0,,{dot}")
    return header + "\n".join(events) + "\n", len(events)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--encoder", default="h264_nvenc")
    args = parser.parse_args()

    result_url = f"{args.api_url}/api/v1/videos/jobs/{args.job_id}/result"
    with urllib.request.urlopen(result_url, timeout=30) as response:
        result = json.load(response)
    if result.get("status") != "completed":
        raise RuntimeError("Video recognition result is not completed")

    ass_content, event_count = build_ass(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mvision-annotation-") as temp_dir:
        subtitle_path = Path(temp_dir) / "detections.ass"
        subtitle_path.write_text(ass_content, encoding="utf-8")
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(args.input),
            "-vf",
            f"ass={subtitle_path}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            args.encoder,
            "-preset",
            "p4",
            "-cq",
            "20",
            "-b:v",
            "0",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(args.output),
        ]
        subprocess.run(command, check=True)
    print(
        f"output={args.output} persons={len(result['persons'])} overlay_events={event_count}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
