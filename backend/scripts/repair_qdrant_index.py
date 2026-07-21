"""Rebuild Qdrant points from durable PostgreSQL and MinIO face samples."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any

import psycopg
from minio import Minio
from qdrant_client import QdrantClient, models

from app.infrastructure.gpu.worker_pool import GpuWorkerPool


@dataclass(frozen=True)
class Sample:
    sample_id: str
    face_id: str
    object_key: str
    embedding_model_version: str
    preprocess_version: str


def require_single_face(result: Any, request_id: str) -> list[float]:
    if result.request_id != request_id:
        raise RuntimeError("GPU worker returned a mismatched request ID")
    if result.status != "OK":
        raise RuntimeError(result.error_code or "GPU worker failed")
    if len(result.faces) != 1:
        raise RuntimeError(f"Expected one face, received {len(result.faces)}")
    return list(result.faces[0].embedding)


def load_samples(database_url: str, limit: int | None) -> list[Sample]:
    query = """
        SELECT sample_id::text, face_id::text, object_key,
               embedding_model_version, preprocess_version
        FROM face_sample
        WHERE is_active IS TRUE AND lifecycle_state = 'active'
        ORDER BY sample_id
    """
    sync_url = database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(sync_url) as connection, connection.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchmany(limit) if limit is not None else cursor.fetchall()
    return [Sample(*row) for row in rows]


def read_object(client: Minio, bucket: str, object_key: str) -> bytes:
    response = client.get_object(bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


async def embed_samples(
    samples: list[Sample],
    minio: Minio,
    bucket: str,
    workers: GpuWorkerPool,
    concurrency: int,
) -> tuple[list[tuple[Sample, list[float]]], list[tuple[Sample, str]]]:
    semaphore = asyncio.Semaphore(concurrency)
    completed = 0

    async def embed(sample: Sample) -> tuple[Sample, list[float]]:
        nonlocal completed
        async with semaphore:
            image = await asyncio.to_thread(read_object, minio, bucket, sample.object_key)
            result = await workers.process(image, sample.sample_id)
            vector = require_single_face(result, sample.sample_id)
            completed += 1
            if completed % 100 == 0 or completed == len(samples):
                print(f"embedded={completed}/{len(samples)}", flush=True)
            return sample, vector

    results = await asyncio.gather(*(embed(sample) for sample in samples), return_exceptions=True)
    successful: list[tuple[Sample, list[float]]] = []
    failed: list[tuple[Sample, str]] = []
    for sample, result in zip(samples, results, strict=True):
        if isinstance(result, BaseException):
            failed.append((sample, str(result)))
        else:
            successful.append(result)
    return successful, failed


def upsert_points(
    client: QdrantClient,
    collection: str,
    embeddings: list[tuple[Sample, list[float]]],
    batch_size: int,
) -> None:
    for offset in range(0, len(embeddings), batch_size):
        batch = embeddings[offset : offset + batch_size]
        points = [
            models.PointStruct(
                id=sample.sample_id,
                vector=vector,
                payload={
                    "sample_id": sample.sample_id,
                    "face_id": sample.face_id,
                    "active": True,
                    "embedding_model_version": sample.embedding_model_version,
                    "preprocess_version": sample.preprocess_version,
                },
            )
            for sample, vector in batch
        ]
        client.upsert(collection_name=collection, points=points, wait=True)
        print(f"upserted={min(offset + len(batch), len(embeddings))}/{len(embeddings)}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default="postgresql+psycopg://mergen:mergen@postgres:5432/mergenvision",
    )
    parser.add_argument("--minio-endpoint", default="minio:9000")
    parser.add_argument("--minio-access-key", default="minioadmin")
    parser.add_argument("--minio-secret-key", default="minioadmin")
    parser.add_argument("--bucket", default="mergenvision-faces")
    parser.add_argument("--qdrant-url", default="http://qdrant:6333")
    parser.add_argument("--collection", default="face_samples_arcface_r50_webface_v1")
    parser.add_argument(
        "--sockets",
        default="/run/mvision/worker-0.sock,/run/mvision/worker-1.sock,/run/mvision/worker-2.sock",
    )
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    samples = load_samples(args.database_url, args.limit)
    print(f"samples={len(samples)}", flush=True)
    minio = Minio(
        args.minio_endpoint,
        access_key=args.minio_access_key,
        secret_key=args.minio_secret_key,
        secure=False,
    )
    workers = GpuWorkerPool(args.sockets.split(","), timeout_seconds=120)
    embeddings, failures = asyncio.run(
        embed_samples(samples, minio, args.bucket, workers, args.concurrency)
    )
    qdrant = QdrantClient(url=args.qdrant_url, timeout=120)
    upsert_points(qdrant, args.collection, embeddings, args.batch_size)

    for sample, error in failures:
        print(f"failed sample_id={sample.sample_id} error={error}", flush=True)
    print(f"completed={len(embeddings)} failed={len(failures)}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
