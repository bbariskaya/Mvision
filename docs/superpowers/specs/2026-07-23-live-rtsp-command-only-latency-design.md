# Live RTSP Command-Only Latency Design

## Scope

Reduce perceived motion-to-annotated-video latency without changing the Mvision worker, native pipeline, API, or deployment configuration.

## Evidence

- The input and annotated streams both sustain approximately 30 FPS.
- GPU utilization and encoder/decoder utilization show available capacity.
- Server-side visual matching did not show a multi-second processing backlog.
- The publisher currently permits a 512-frame capture queue, which can retain about 17 seconds at 30 FPS if encoding or network output falls behind.
- The worker already uses leaky queues, no sink synchronization, GPU encoding, and no encoder B-frames by default.

## Design

Keep RTSP over TCP for the first test. Change only endpoint commands:

- Reduce the publisher capture queue from 512 frames to 4 frames.
- Make zero B-frames, one reference frame, zero lookahead, immediate packet flushing, and zero RTSP mux delay explicit.
- Keep the existing ultrafast and zerolatency x264 settings.
- Disable input analysis and playback buffering conservatively in ffplay while retaining enough probe data to discover H.264 reliably.
- Drop late display frames rather than allowing playback latency to grow.

UDP remains an optional second experiment only if the TCP command still has unacceptable latency on the local network.

## Acceptance

- The annotated stream remains near 30 FPS.
- Delay does not grow while the stream remains open.
- Camera movement and annotated output are visibly closer than with the existing commands.
- The stream reconnects cleanly after restarting the publisher or player.

## Non-Goals

- Changing DeepStream batch size or inference behavior.
- Changing worker jitter buffers or queue sizes.
- Changing the output resolution.
- Redesigning the annotated-stream architecture.
