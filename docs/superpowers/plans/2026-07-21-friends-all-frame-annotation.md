# Friends All-Frame Annotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist five landmarks for every detection, process every Friends frame, and render `test_videos/friends_annotated.mp4` with name, cosine, detector score, box, and landmarks.

**Architecture:** Extend the native/Python MessagePack detection contract with ten landmark floats. Persist them in each detection JSON object and teach the ASS annotation renderer to draw landmark dots and the complete label. Submit the isolated Friends video with `everyNFrames=1`.

**Tech Stack:** C++17, MessagePack, DeepStream metadata, Python 3.12, pytest, FFmpeg/ASS, Docker Compose.

## Global Constraints

- Use only the isolated Friends stores and `friends_arcface_r50_v1`.
- Process every source frame with `everyNFrames=1`.
- Output exactly `test_videos/friends_annotated.mp4`.
- Overlay `Name | cos 0.000 | det 0.000`, bounding box, and five landmarks.
- Do not commit or push.

---

### Task 1: Carry Five Landmarks Through the Video Protocol

**Files:** `backend/pipeline/include/mvision/video_protocol.hpp`, `backend/pipeline/src/video_protocol.cpp`, `backend/pipeline/src/video_pipeline.cpp`, `backend/pipeline/tests/test_video_protocol.cpp`, `backend/app/infrastructure/video/protocol.py`, `backend/tests/unit/test_video_protocol.py`.

- [ ] Add failing C++ and Python protocol tests asserting ten landmark floats survive encode/decode.
- [ ] Verify both tests fail before implementation.
- [ ] Add landmark storage to native/Python `VideoDetection` and MessagePack encoding.
- [ ] Read five landmark triplets from `NvDsObjectMeta.mask_params` into each observation.
- [ ] Rebuild and pass native/Python protocol tests.

### Task 2: Persist and Render Complete Detection Overlays

**Files:** `backend/app/services/video_result_service.py`, `backend/scripts/annotate_video.py`, `backend/scripts/test_annotate_video.py`, `backend/tests/unit/test_video_result_service.py`.

- [ ] Add failing tests for persisted landmark JSON and ASS output containing five landmark markers plus name/cosine/detector text.
- [ ] Persist landmarks as five `{x,y}` objects per detection.
- [ ] Render box, five dots, and `Name | cos N | det N` for each detection.
- [ ] Pass result and annotation tests.

### Task 3: Run and Validate Every Frame

- [ ] Rebuild the native video worker and Friends worker image.
- [ ] Recreate `friends-video-worker-0`.
- [ ] Submit `Friends.mp4` with `samplingMode=every_n_frames` and `everyNFrames=1`.
- [ ] Verify completion covers all 6,665 source frames and inspect canonical identities.
- [ ] Inspect representative multi-face scenes and reject incorrect known labels.
- [ ] Render `test_videos/friends_annotated.mp4`.
- [ ] Verify 1920x1080, approximately 278.036 seconds, 6,665 frames, H.264/AAC, visible landmarks, boxes, names, cosine, and detector confidence.
