# Live RTSP Command-Only Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce webcam-motion-to-annotated-display latency without changing repository code or worker configuration.

**Architecture:** Keep the existing webcam -> input MediaMTX -> DeepStream worker -> output RTSP chain. Bound publisher buffering to four frames, make the existing zero-latency H.264 behavior explicit, and configure ffplay to discard late frames instead of accumulating delay.

**Tech Stack:** FFmpeg, libx264, RTSP over TCP, ffplay, MediaMTX, DeepStream

## Global Constraints

- Do not change Mvision application code, native pipeline code, API configuration, or Docker configuration.
- Keep the worker batch size at `1`.
- Keep RTSP over TCP for the first acceptance test.
- Prefer dropping late frames over increasing end-to-end latency.
- Do not create a git commit.

---

### Task 1: Run The Bounded-Latency Endpoint Commands

**Files:**
- Reference: `docs/superpowers/specs/2026-07-23-live-rtsp-command-only-latency-design.md`
- Create: none
- Modify: none
- Test: live input and annotated RTSP streams

**Interfaces:**
- Consumes: `/dev/video0`, `rtsp://10.1.60.230:8555/baris`
- Produces: `rtsp://10.1.60.230:8554/live/019f88fd-6a38-7701-801f-1c508e2cadb1`

- [ ] **Step 1: Stop the existing publisher and player**

Press `Ctrl+C` once in each terminal running the existing `ffmpeg` publisher and `ffplay` player.

Expected: both commands exit without leaving a publisher or player process running.

- [ ] **Step 2: Start the bounded publisher**

Run on the camera PC:

```bash
ffmpeg \
  -f v4l2 \
  -input_format mjpeg \
  -framerate 30 \
  -video_size 1280x720 \
  -thread_queue_size 4 \
  -i /dev/video0 \
  -an \
  -c:v libx264 \
  -preset ultrafast \
  -tune zerolatency \
  -pix_fmt yuv420p \
  -profile:v baseline \
  -bf 0 \
  -refs 1 \
  -g 30 \
  -keyint_min 30 \
  -sc_threshold 0 \
  -x264-params 'rc-lookahead=0:sync-lookahead=0' \
  -b:v 4M \
  -maxrate 4M \
  -bufsize 1M \
  -flush_packets 1 \
  -muxdelay 0 \
  -f rtsp \
  -rtsp_transport tcp \
  rtsp://10.1.60.230:8555/baris
```

Expected: FFmpeg reports approximately `30 fps`, does not report a growing duplicate/drop count, and continues publishing.

- [ ] **Step 3: Start the strict low-buffer player**

Run in a second terminal on the camera PC:

```bash
ffplay \
  -rtsp_transport tcp \
  -fflags nobuffer \
  -flags low_delay \
  -framedrop \
  -analyzeduration 0 \
  -probesize 2048 \
  -max_delay 0 \
  -sync ext \
  rtsp://10.1.60.230:8554/live/019f88fd-6a38-7701-801f-1c508e2cadb1
```

Expected: the annotated picture opens, follows current camera movement, and does not drift farther behind while left open.

- [ ] **Step 4: Verify server throughput**

Run on the Mvision server while both PC commands remain active:

```bash
timeout 12 ffprobe \
  -v error \
  -rtsp_transport tcp \
  -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,avg_frame_rate \
  -of json \
  rtsp://127.0.0.1:8554/live/019f88fd-6a38-7701-801f-1c508e2cadb1
```

Expected: codec is `h264`, dimensions are `1920x1080`, and the stream remains available near the 30 FPS input rate.

- [ ] **Step 5: Use the GStreamer player only if ffplay remains visibly delayed**

Run on the camera PC:

```bash
gst-launch-1.0 \
  rtspsrc location=rtsp://10.1.60.230:8554/live/019f88fd-6a38-7701-801f-1c508e2cadb1 \
    protocols=tcp latency=0 drop-on-latency=true \
  ! rtph264depay \
  ! h264parse \
  ! avdec_h264 \
  ! videoconvert \
  ! autovideosink sync=false
```

Expected: the player displays the newest decoded frame without clock-synchronized display buffering. If this is materially faster than ffplay, the remaining delay is client playback behavior rather than worker processing.
