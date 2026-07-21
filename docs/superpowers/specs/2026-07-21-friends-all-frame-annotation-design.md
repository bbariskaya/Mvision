# Friends All-Frame Annotation Design

## Goal

Produce `/home/user/Workspace/Mvision/test_videos/friends_annotated.mp4` from every frame of
`Friends.mp4`, using only the isolated Friends gallery.

## Processing

The video job uses `every_n_frames` with `everyNFrames=1`. Every detector output carries its
bounding box, detector confidence, and five landmark coordinates through the native MessagePack
protocol into persisted video detections.

Tracklet voting resolves each canonical track only against `friends_arcface_r50_v1`. The resulting
track-level cosine confidence and identity snapshot are associated with every detection in that
track.

## Overlay

Every detection renders:

- bounding box
- five landmark dots
- actor name or `Unknown`
- track-level cosine confidence
- per-detection detector confidence

The text format is `Name | cos 0.000 | det 0.000`.

## Output Verification

The output path is exactly `test_videos/friends_annotated.mp4`. It preserves 1920x1080 resolution,
source timing, all 6,665 frames, and audio. Representative multi-face scenes and timeline segments
are visually inspected before acceptance.
