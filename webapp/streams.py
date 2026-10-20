"""Server-side video sources (RTSP/IP cameras, video files, server webcams).

The browser cannot open RTSP itself, so the server reads the stream in a
background thread, runs detection + tracking on every frame and hands the
newest JPEG plus the corner state to the page.
"""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np

from docscan.camera import LatestFrameReader, is_stream, open_source, source_info
from docscan.detect import find_document
from docscan.tracking import CornerTracker


class StreamSession:
    def __init__(self, source: str, undistort=None, stable_frames: int = 15):
        self.source = source
        self.cap = open_source(source)
        self.info = source_info(self.cap)
        self.is_file = not str(source).isdigit() and not is_stream(source)
        self.reader = LatestFrameReader(self.cap) if is_stream(source) else None
        fps = self.info["fps"]
        self.fps = fps if 1 < fps < 120 else 25
        self.undistort = undistort
        self.tracker = CornerTracker(stable_frames=stable_frames)
        self.cond = threading.Condition()
        self.frame, self.jpeg, self.state, self.seq = None, None, {}, 0
        self.error, self.running = None, True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _read(self):
        if self.reader is not None:
            return self.reader.read()
        ok, frame = self.cap.read()
        if not ok and self.is_file:          # loop video files
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        return ok, frame

    def _run(self):
        while self.running:
            t0 = time.perf_counter()
            ok, frame = self._read()
            if not ok or frame is None:
                self.error = "The stream ended or cannot be reached."
                break
            if self.undistort is not None:
                frame = self.undistort(frame)
            h, w = frame.shape[:2]
            det = find_document(frame, refine=False)
            corners = self.tracker.update(det.corners if det else None, float(np.hypot(w, h)))
            view = frame if w <= 960 else cv2.resize(frame, (960, round(h * 960 / w)), interpolation=cv2.INTER_AREA)
            jpeg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
            state = {
                "corners": None if corners is None else (corners / [w, h]).round(5).tolist(),
                "progress": round(self.tracker.progress, 3),
                "stable": self.tracker.is_stable,
                "method": det.method if det else None,
                "width": w, "height": h,
            }
            with self.cond:
                self.frame, self.jpeg, self.state = frame, jpeg, state
                self.seq += 1
                self.cond.notify_all()
            if self.is_file:                 # play files at their real speed
                time.sleep(max(0.0, 1.0 / self.fps - (time.perf_counter() - t0)))
        with self.cond:
            self.running = False
            self.cond.notify_all()

    def wait_frame(self, after: int, timeout: float = 2.0):
        with self.cond:
            self.cond.wait_for(lambda: self.seq > after or not self.running, timeout)
            return self.jpeg, dict(self.state), self.seq

    def snapshot(self):
        with self.cond:
            if self.frame is None:
                return None, None
            c = self.tracker.corners
            return self.frame.copy(), None if c is None else c.copy()

    def stop(self):
        self.running = False
        self.thread.join(timeout=2)
        if self.reader is not None:
            self.reader.release()
        else:
            self.cap.release()


class StreamManager:
    def __init__(self):
        self.session: StreamSession | None = None
        self.lock = threading.Lock()

    def start(self, source: str, **kw) -> StreamSession:
        with self.lock:
            if self.session is not None:
                self.session.stop()
                self.session = None
            self.session = StreamSession(source, **kw)
            return self.session

    def stop(self):
        with self.lock:
            if self.session is not None:
                self.session.stop()
                self.session = None
