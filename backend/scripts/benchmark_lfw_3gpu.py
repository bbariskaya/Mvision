#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import os
import queue
import socket
import struct
import subprocess
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import msgpack
import psycopg
from minio import Minio
from qdrant_client import QdrantClient, models


NAMESPACE = uuid.UUID("5705284d-8ef8-4ac8-ae68-fc295f26d221")
MODEL_VERSION = "arcface_r50_webface4m_v1"
PREPROCESS_VERSION = "five-point-umeyama-112x112"
DETECTOR_VERSION = "yolov8n-face-v1"
ALIGNMENT_VERSION = "umeyama-5point-112x112"
COLLECTION = "face_samples_arcface_r50_webface_v1"
BUCKET = "mergenvision-faces"


def stable_id(kind: str, value: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}:{value}"))


def frame(payload: dict) -> bytes:
    packed = msgpack.packb(payload, use_bin_type=True)
    return struct.pack("!I", len(packed)) + packed


def read_exact(stream: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.recv(size - len(chunks))
        if not chunk:
            raise RuntimeError("worker socket closed")
        chunks.extend(chunk)
    return bytes(chunks)


def read_result(stream: socket.socket) -> dict:
    size = struct.unpack("!I", read_exact(stream, 4))[0]
    return msgpack.unpackb(read_exact(stream, size), raw=False)


@dataclass
class Metrics:
    lock: threading.Lock = field(default_factory=threading.Lock)
    discovered: int = 0
    submitted: int = 0
    gpu_completed: int = 0
    persisted: int = 0
    rejected: int = 0
    failed: int = 0
    minio_seconds: float = 0.0
    qdrant_seconds: float = 0.0
    postgres_seconds: float = 0.0
    worker_images: Counter = field(default_factory=Counter)
    batch_histogram: Counter = field(default_factory=Counter)

    def add(self, **values: int | float) -> None:
        with self.lock:
            for key, value in values.items():
                setattr(self, key, getattr(self, key) + value)


def start_workers(socket_dir: Path, slots: int) -> list[subprocess.Popen]:
    if all((socket_dir / f"worker-{worker}.sock").exists() for worker in range(3)):
        return []
    workers = []
    for worker in range(3):
        name = f"mvision-gpu-worker-{worker}"
        subprocess.run(["docker", "rm", "-f", name], check=False, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        command = [
            "docker", "run", "--rm", "--name", name,
            "--ulimit", "nofile=65536:65536", "--gpus", f"device={worker}",
            "-v", f"{Path.cwd()}:/workspace", "-v", f"{socket_dir}:/run/mvision",
            "-w", "/workspace", "-e",
            "LD_LIBRARY_PATH=/workspace/build/pipeline:/opt/nvidia/deepstream/deepstream/lib",
            "mvision-pipeline-builder:local", "build/pipeline/mvision_worker",
            f"/run/mvision/worker-{worker}.sock", str(slots),
            "/workspace/configs/pgie_yolov8_face.txt",
            "/workspace/configs/preprocess_arcface.txt",
            "/workspace/configs/sgie_arcface_r50.txt",
        ]
        workers.append(subprocess.Popen(command, stdout=subprocess.DEVNULL))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if all((socket_dir / f"worker-{worker}.sock").exists() for worker in range(3)):
            return workers
        if any(process.poll() is not None for process in workers):
            raise RuntimeError("GPU worker exited during startup")
        time.sleep(0.1)
    raise RuntimeError("GPU worker socket startup timeout")


def gpu_worker(worker: int, socket_dir: Path, work: queue.Queue, persist: queue.Queue,
               metrics: Metrics) -> None:
    socket_path = str(socket_dir / f"worker-{worker}.sock")
    while True:
        batch = work.get()
        if batch is None:
            return
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.connect(socket_path)
                stream.sendall(struct.pack("!I", len(batch)))
                request_map = {}
                for path in batch:
                    request_id = stable_id("request", path.as_posix())
                    request_map[request_id] = path
                    stream.sendall(frame({"protocol_version": 1, "request_id": request_id,
                                          "encoded_jpeg": path.read_bytes()}))
                metrics.add(submitted=len(batch))
                for _ in batch:
                    result = read_result(stream)
                    path = request_map[result["request_id"]]
                    faces = result["faces"]
                    metrics.add(gpu_completed=1)
                    metrics.worker_images[worker] += 1
                    if len(faces) != 1:
                        metrics.add(rejected=1)
                        continue
                    persist.put((path, faces[0]))
        except Exception as exc:
            print(f"worker-{worker} batch failed: {exc}", flush=True)
            metrics.add(failed=len(batch))
        finally:
            work.task_done()


def upload(minio: Minio, root: Path, path: Path) -> tuple[str, str]:
    relative = path.relative_to(root).as_posix()
    label = path.parent.name
    sample_id = stable_id("sample", relative)
    face_id = stable_id("face", label)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    object_key = f"faces/{face_id}/{sample_id}/aligned"
    minio.put_object(BUCKET, object_key, io.BytesIO(data), len(data), content_type="image/jpeg",
                     metadata={"sample-id": sample_id, "sha256": digest})
    return object_key, digest


def landmark_payload(face: dict) -> dict:
    landmarks = face["landmarks_xy"]
    return {"points": [[landmarks[i], landmarks[i + 1]] for i in range(0, 10, 2)]}


def persist_batch(batch: list[tuple[Path, dict]], root: Path, minio: Minio,
                  qdrant: QdrantClient, pool: concurrent.futures.ThreadPoolExecutor,
                  metrics: Metrics) -> None:
    started = time.perf_counter()
    uploads = [pool.submit(upload, minio, root, path) for path, _ in batch]
    points = []
    for path, face in batch:
        relative = path.relative_to(root).as_posix()
        sample_id = stable_id("sample", relative)
        face_id = stable_id("face", path.parent.name)
        points.append(models.PointStruct(
            id=sample_id, vector=face["embedding"],
            payload={"sample_id": sample_id, "face_id": face_id, "active": True,
                     "embedding_model_version": MODEL_VERSION,
                     "preprocess_version": PREPROCESS_VERSION},
        ))
    qdrant_started = time.perf_counter()
    qdrant.upsert(COLLECTION, points=points, wait=True)
    qdrant_elapsed = time.perf_counter() - qdrant_started
    upload_results = [future.result() for future in uploads]
    minio_elapsed = time.perf_counter() - started

    identities = {(stable_id("face", path.parent.name), path.parent.name) for path, _ in batch}
    rows = []
    for (path, face), (object_key, digest) in zip(batch, upload_results, strict=True):
        relative = path.relative_to(root).as_posix()
        rows.append((stable_id("sample", relative), stable_id("face", path.parent.name), BUCKET,
                     object_key, digest,
                     json.dumps({"x": face["x"], "y": face["y"], "width": face["width"],
                                 "height": face["height"]}),
                     json.dumps(landmark_payload(face))))
    postgres_started = time.perf_counter()
    with psycopg.connect("postgresql://mergen:mergen@localhost:5432/mergenvision") as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO face_identity
                   (face_id,lifecycle_status,name,metadata,is_active,version)
                   VALUES (%s,'known',%s,'{}'::jsonb,true,1) ON CONFLICT DO NOTHING""", identities)
            cursor.executemany(
                """INSERT INTO face_sample
                   (sample_id,face_id,lifecycle_state,bucket,object_key,media_type,sha256,
                    detector_version,embedding_model_version,alignment_version,preprocess_version,
                    is_active,bounding_box,landmarks,quality)
                   VALUES (%s,%s,'active',%s,%s,'image/jpeg',%s,%s,%s,%s,%s,true,
                           %s::jsonb,%s::jsonb,NULL) ON CONFLICT DO NOTHING""",
                [(row[0], row[1], row[2], row[3], row[4], DETECTOR_VERSION, MODEL_VERSION,
                  ALIGNMENT_VERSION, PREPROCESS_VERSION, row[5], row[6]) for row in rows])
        connection.commit()
    metrics.add(persisted=len(batch), minio_seconds=minio_elapsed,
                qdrant_seconds=qdrant_elapsed,
                postgres_seconds=time.perf_counter() - postgres_started)
    metrics.batch_histogram[len(batch)] += 1


def persistence_worker(results: queue.Queue, root: Path, batch_size: int, minio_workers: int,
                       metrics: Metrics) -> None:
    minio = Minio("localhost:9000", access_key="minioadmin", secret_key="minioadmin",
                  secure=False)
    if not minio.bucket_exists(BUCKET):
        minio.make_bucket(BUCKET)
    qdrant = QdrantClient(url="http://localhost:6333", timeout=120)
    if not qdrant.collection_exists(COLLECTION):
        qdrant.create_collection(
            COLLECTION, vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE))
    batch = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=minio_workers) as pool:
        while True:
            item = results.get()
            if item is None:
                if batch:
                    persist_batch(batch, root, minio, qdrant, pool, metrics)
                return
            batch.append(item)
            if len(batch) >= batch_size:
                persist_batch(batch, root, minio, qdrant, pool, metrics)
                batch = []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=Path("lfw"))
    parser.add_argument("--slots", type=int, default=128)
    parser.add_argument("--gpu-batch", type=int, default=128)
    parser.add_argument("--persistence-batch", type=int, default=256)
    parser.add_argument("--minio-workers", type=int, default=30)
    args = parser.parse_args()
    root = args.dataset_root.resolve()
    images = sorted(root.glob("*/*.jpg"))
    metrics = Metrics(discovered=len(images))
    socket_dir = Path("run/mvision").resolve()
    socket_dir.mkdir(parents=True, exist_ok=True)
    for old_socket in socket_dir.glob("*.sock"):
        old_socket.unlink()

    subprocess.run(["docker", "compose", "-f", "docker-compose.sprint01.yml", "run", "--rm",
                    "api", "alembic", "upgrade", "head"], check=True)
    workers = start_workers(socket_dir, args.slots)
    work_queue: queue.Queue = queue.Queue(maxsize=24)
    result_queue: queue.Queue = queue.Queue(maxsize=1024)
    gpu_threads = [threading.Thread(target=gpu_worker,
                                   args=(worker, socket_dir, work_queue, result_queue, metrics))
                   for worker in range(3)]
    persistence = threading.Thread(target=persistence_worker,
                                   args=(result_queue, root, args.persistence_batch,
                                         args.minio_workers, metrics))
    started = time.perf_counter()
    persistence.start()
    for thread in gpu_threads:
        thread.start()
    for offset in range(0, len(images), args.gpu_batch):
        chunk = images[offset:offset + args.gpu_batch]
        work_queue.put(chunk)
        metrics.batch_histogram[len(chunk)] += 1
    for _ in gpu_threads:
        work_queue.put(None)
    for thread in gpu_threads:
        thread.join()
    gpu_finished = time.perf_counter()
    result_queue.put(None)
    persistence.join()
    finished = time.perf_counter()
    report = {
        "discovered": metrics.discovered, "submitted": metrics.submitted,
        "gpu_completed": metrics.gpu_completed, "persisted": metrics.persisted,
        "rejected": metrics.rejected, "failed": metrics.failed,
        "gpu_seconds": gpu_finished - started, "persistence_drain_seconds": finished - gpu_finished,
        "wall_seconds": finished - started,
        "gpu_fps": metrics.gpu_completed / (gpu_finished - started),
        "durable_samples_per_second": metrics.persisted / (finished - started),
        "minio_stage_seconds": metrics.minio_seconds,
        "qdrant_commit_seconds": metrics.qdrant_seconds,
        "postgres_commit_seconds": metrics.postgres_seconds,
        "worker_distribution": dict(metrics.worker_images),
        "batch_histogram": dict(metrics.batch_histogram),
    }
    print(json.dumps(report, indent=2))
    if workers:
        subprocess.run(["docker", "stop", "-t", "5", "mvision-gpu-worker-0",
                        "mvision-gpu-worker-1", "mvision-gpu-worker-2"], check=False,
                       stdout=subprocess.DEVNULL)
        for process in workers:
            process.wait(timeout=30)
    return 0 if metrics.failed == 0 and metrics.persisted + metrics.rejected == len(images) else 1


if __name__ == "__main__":
    raise SystemExit(main())
