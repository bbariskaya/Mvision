import asyncio
import math
import sys
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.infrastructure.database.repositories import FaceIdentityRepository
from app.infrastructure.gpu.worker_pool import GpuWorkerPool
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter
from app.services.face_matcher import FaceMatcher


async def main(image_path: Path) -> None:
    settings = Settings()
    pool = GpuWorkerPool(settings.gpu_socket_paths)
    matcher = FaceMatcher(settings, FaceIdentityRepository(), QdrantAdapter(settings))
    result = await pool.process(image_path.read_bytes(), str(uuid4()))
    for index, face in enumerate(result.faces):
        candidates = await matcher.candidates(list(face.embedding), minimum_score=0.0)
        print(
            {
                "index": index,
                "box": [round(value, 1) for value in (face.x, face.y, face.width, face.height)],
                "detector": round(face.detector_confidence, 4),
                "embedding_norm": round(math.sqrt(sum(value * value for value in face.embedding)), 6),
                "landmarks": [round(value, 1) for value in face.landmarks_xy],
                "candidates": [
                    {"name": candidate.identity.name, "score": round(candidate.score, 4)}
                    for candidate in candidates[:5]
                    if candidate.identity.lifecycle_status == "known"
                ],
            }
        )


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
