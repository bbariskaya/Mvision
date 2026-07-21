# Deterministic Friends RTSP Fixture

This fixture publishes the existing local Friends source at
`rtsp://rtsp-fixture:8555/friends`. The source is read-only and generated media
is ignored by Git.

## Frozen Source Contract

The local source path is exact:

```text
/home/user/Workspace/Mvision/test_videos/Friends.mp4
```

Verify it before every runtime gate:

```bash
ffprobe -v error \
  -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate \
  -show_entries format=duration \
  -of default=noprint_wrappers=1 \
  /home/user/Workspace/Mvision/test_videos/Friends.mp4
```

The frozen values are H.264, `1920x1080`, `24000/1001` FPS and approximately
`278.035737` seconds. Stop if codec, dimensions or frame rate differ.

## Generate The Loopable Transport Stream

The RTSP server loops an MPEG-TS remux so the source video is not decoded or
re-encoded during fixture preparation:

```bash
mkdir -p backend/tests/fixtures/rtsp/generated
ffmpeg -y \
  -i /home/user/Workspace/Mvision/test_videos/Friends.mp4 \
  -map 0:v:0 -an -c:v copy -bsf:v h264_mp4toannexb \
  -f mpegts backend/tests/fixtures/rtsp/generated/friends.ts
```

The generated file is test-only, reproducible and must remain untracked.

## Publish With GstRtspServer

Create the isolated network once:

```bash
docker network inspect mvision-live-test >/dev/null 2>&1 || \
  docker network create mvision-live-test
```

Run the pinned DeepStream base with the generated fixture mounted read-only.
The ephemeral package install supplies only the GstRtspServer Python binding;
the production worker image is not changed:

```bash
docker run --rm --name rtsp-fixture \
  --network mvision-live-test \
  -v "$PWD/backend/tests/fixtures/rtsp/generated/friends.ts:/fixture/friends.ts:ro" \
  -v "$PWD/backend/tests/fixtures/rtsp/server.py:/fixture/server.py:ro" \
  nvcr.io/nvidia/deepstream:9.0-triton-multiarch@sha256:60888367d4c97ba192411a7694c984080a553f855ad53fc4c5579d70424fafd7 \
  bash -lc 'apt-get update >/tmp/apt.log && \
    apt-get install -y --no-install-recommends python3-gi gir1.2-gst-rtsp-server-1.0 >>/tmp/apt.log && \
    exec /usr/bin/python3 /fixture/server.py'
```

The command contains no camera credentials. Generated paths and source paths
must not be copied into product logs or metrics.

## Fixture Health

From a container on `mvision-live-test`, run:

```bash
ffprobe -v error -rtsp_transport tcp \
  -show_entries stream=codec_name,width,height,r_frame_rate \
  -of default=noprint_wrappers=1 \
  rtsp://rtsp-fixture:8555/friends
```

Acceptance requires H.264, `1920x1080`, advancing timestamps, and a bounded
probe exit. Stop the fixture with `docker stop rtsp-fixture`; never use a volume
destructive command.
