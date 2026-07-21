import argparse
from pathlib import Path

import httpx

IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png"}


def import_dataset(
    root: Path,
    api_url: str,
    client: httpx.Client,
    *,
    holdout_last: bool = False,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for actor_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        images = sorted(
            path for path in actor_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
        )
        if holdout_last:
            images = images[:-1]
        face_id: str | None = None
        accepted = 0
        for image in images:
            data = {"name": actor_dir.name}
            if face_id is not None:
                data["faceId"] = face_id
            media_type = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
            response = client.post(
                f"{api_url.rstrip('/')}/api/v1/faces/enroll",
                data=data,
                files={"image": (image.name, image.read_bytes(), media_type)},
            )
            response.raise_for_status()
            faces = response.json().get("faces", [])
            if len(faces) != 1:
                raise RuntimeError(f"Expected one enrolled face in {image}, got {len(faces)}")
            face_id = faces[0]["faceId"]
            accepted += 1
        if accepted == 0:
            raise RuntimeError(f"No images enrolled for {actor_dir.name}")
        counts[actor_dir.name] = accepted
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--api-url", default="http://localhost:8001")
    parser.add_argument("--holdout-last", action="store_true")
    args = parser.parse_args()
    with httpx.Client(timeout=60.0) as client:
        counts = import_dataset(
            args.root,
            args.api_url,
            client,
            holdout_last=args.holdout_last,
        )
    print(" ".join(f"{actor}={count}" for actor, count in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
