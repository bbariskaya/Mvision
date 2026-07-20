FROM python:3.12-slim

RUN pip install --no-cache-dir onnx==1.22.0 pytest==9.1.1 pytest-asyncio==1.4.0

WORKDIR /work
