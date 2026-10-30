"""MJPEG camera: Raspberry Pi camera via Picamera2, or a USB webcam via OpenCV."""
import asyncio
import io
import logging
import threading
import time

log = logging.getLogger(__name__)


class Camera:
    def __init__(self, cfg, loop):
        self.loop = loop
        self.frame = None
        self.frame_time = 0.0
        self.cond = asyncio.Condition()
        self.backend = None
        width, height = cfg["camera_resolution"]
        fps = cfg["camera_fps"]
        for start in (self._start_picamera2, self._start_opencv):
            try:
                start(width, height, fps)
                self.backend = start.__name__.replace("_start_", "")
                log.info("camera started (%s)", self.backend)
                return
            except Exception as exc:
                log.info("camera backend %s unavailable: %s", start.__name__, exc)
        log.warning("no camera found - video disabled")

    @property
    def available(self):
        return self.backend is not None

    # --- backends ---------------------------------------------------------

    def _start_picamera2(self, width, height, fps):
        from picamera2 import Picamera2
        from picamera2.encoders import MJPEGEncoder
        from picamera2.outputs import FileOutput

        cam = Picamera2()
        cam.configure(cam.create_video_configuration(
            main={"size": (width, height)}, controls={"FrameRate": fps}))
        camera = self

        class Sink(io.BufferedIOBase):
            def write(self, buf):
                camera._push(bytes(buf))
                return len(buf)

        cam.start_recording(MJPEGEncoder(), FileOutput(Sink()))
        self._cam = cam

    def _start_opencv(self, width, height, fps):
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise RuntimeError("no /dev/video0")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        def grab():
            while True:
                ok, img = cap.read()
                if ok:
                    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        self._push(jpg.tobytes())
                time.sleep(1.0 / fps)

        threading.Thread(target=grab, daemon=True).start()

    # --- frames -----------------------------------------------------------

    def _push(self, jpeg):
        """Called from a camera thread."""
        self.frame = jpeg
        self.frame_time = time.time()
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._wake()))

    async def _wake(self):
        async with self.cond:
            self.cond.notify_all()

    async def next_frame(self):
        async with self.cond:
            await self.cond.wait()
        return self.frame

    def save_snapshot(self, path):
        if self.frame and time.time() - self.frame_time < 10:
            with open(path, "wb") as f:
                f.write(self.frame)
