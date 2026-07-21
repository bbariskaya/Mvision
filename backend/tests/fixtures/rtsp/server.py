import os

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import GLib, Gst, GstRtspServer  # noqa: E402


def main() -> None:
    Gst.init(None)
    source = os.environ.get("RTSP_FIXTURE_SOURCE", "/fixture/friends.ts")
    server = GstRtspServer.RTSPServer.new()
    server.set_service("8555")
    factory = GstRtspServer.RTSPMediaFactory.new()
    factory.set_shared(True)
    factory.set_eos_shutdown(False)
    factory.set_launch(
        "( appsrc name=source is-live=true format=time block=true max-buffers=8 "
        "caps=video/x-h264,stream-format=byte-stream,alignment=au ! "
        "h264parse config-interval=-1 ! "
        "rtph264pay name=pay0 pt=96 )"
    )

    def configure_media(_factory, media) -> None:
        output_pipeline = media.get_element()
        appsrc = output_pipeline.get_by_name("source")
        producer = Gst.parse_launch(
            f"filesrc location={source} ! tsdemux ! "
            "h264parse config-interval=-1 ! "
            "video/x-h264,stream-format=byte-stream,alignment=au ! "
            "appsink name=sink emit-signals=true sync=false max-buffers=8 drop=false"
        )
        appsink = producer.get_by_name("sink")
        next_pts = 0
        default_duration = Gst.SECOND * 1001 // 24000

        def push_sample(_appsink):
            nonlocal next_pts
            sample = appsink.emit("pull-sample")
            if sample is None:
                return Gst.FlowReturn.ERROR
            source_buffer = sample.get_buffer()
            output_buffer = source_buffer.copy_deep()
            duration = source_buffer.duration
            if duration == Gst.CLOCK_TIME_NONE or duration <= 0:
                duration = default_duration
            output_buffer.pts = next_pts
            output_buffer.dts = Gst.CLOCK_TIME_NONE
            output_buffer.duration = duration
            next_pts += duration
            return appsrc.emit("push-buffer", output_buffer)

        appsink.connect("new-sample", push_sample)
        bus = producer.get_bus()
        bus.add_signal_watch()

        def handle_message(_bus, message) -> None:
            if message.type != Gst.MessageType.EOS:
                return
            if not producer.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                0,
            ):
                raise RuntimeError("RTSP_FIXTURE_LOOP_SEEK_FAILED")

        bus.connect("message", handle_message)

        def stop_producer(_media) -> None:
            producer.set_state(Gst.State.NULL)
            bus.remove_signal_watch()

        media.connect("unprepared", stop_producer)
        if producer.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("RTSP_FIXTURE_PRODUCER_START_FAILED")

    factory.connect("media-configure", configure_media)
    server.get_mount_points().add_factory("/friends", factory)
    if server.attach(None) == 0:
        raise RuntimeError("RTSP_FIXTURE_ATTACH_FAILED")
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
