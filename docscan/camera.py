"""Camera basics: opening video sources, calibration and lens undistortion.

Pinhole model
-------------
    camera matrix K = [[fx, 0, cx],
                       [0, fy, cy],
                       [0,  0,  1]]       fx, fy = focal length in pixels, (cx, cy) = principal point
    distortion  = (k1, k2, p1, p2, k3)   k = radial ("barrel/pincushion"), p = tangential

Calibration: photograph a chessboard of known geometry from many angles, find its
inner corners, then cv2.calibrateCamera solves for K and the distortion
coefficients. The RMS re-projection error (pixels) tells you how good it is:
< 0.5 px is great, < 1 px is fine.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

STREAM_PREFIXES = ("rtsp://", "rtmp://", "http://", "https://")


# --------------------------------------------------------------------------- sources
def open_source(source, width: int | None = 1280, height: int | None = 720) -> cv2.VideoCapture:
    """Open a webcam index ("0"), a video file path, or an RTSP/HTTP stream URL."""
    src = str(source)
    if src.isdigit():
        index = int(src)
        # DirectShow opens much faster than MSMF on Windows laptops
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(index)
        if not cap.isOpened():
            cap = cv2.VideoCapture(index)
        if width and height:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    elif src.lower().startswith(STREAM_PREFIXES):
        cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # keep latency low
    else:
        if not Path(src).exists():
            raise FileNotFoundError(src)
        cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise RuntimeError(f"could not open video source {source!r}")
    return cap


def is_stream(source) -> bool:
    return str(source).lower().startswith(STREAM_PREFIXES)


class LatestFrameReader:
    """Reads a network stream in a background thread and keeps only the newest frame.

    RTSP cameras push frames at their own pace; if processing is slower than the
    stream, OpenCV's internal buffer fills up and you see seconds of lag.
    """

    def __init__(self, cap: cv2.VideoCapture):
        self.cap = cap
        self.frame = None
        self.ok = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.ok:
            ok, frame = self.cap.read()
            with self.lock:
                self.ok, self.frame = ok, frame

    def read(self):
        while self.ok and self.frame is None:
            time.sleep(0.01)
        with self.lock:
            return self.ok, None if self.frame is None else self.frame.copy()

    def release(self):
        self.ok = False
        self.thread.join(timeout=1)
        self.cap.release()


def source_info(cap: cv2.VideoCapture) -> dict:
    return {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": round(cap.get(cv2.CAP_PROP_FPS), 2),
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "backend": cap.getBackendName(),
    }


# --------------------------------------------------------------------------- calibration
def chessboard_object_points(pattern: tuple[int, int], square_size: float = 1.0) -> np.ndarray:
    """3D coordinates of the inner corners on the flat board (z = 0)."""
    cols, rows = pattern
    grid = np.zeros((rows * cols, 3), np.float32)
    grid[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_size
    return grid


def find_chessboard(gray: np.ndarray, pattern: tuple[int, int]):
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK
    found, corners = cv2.findChessboardCorners(gray, pattern, flags)
    if not found:
        return None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    return cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)


def calibrate(image_points: list, pattern: tuple[int, int], image_size: tuple[int, int],
              square_size: float = 1.0) -> dict:
    """image_size is (width, height)."""
    objp = chessboard_object_points(pattern, square_size)
    object_points = [objp] * len(image_points)
    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(object_points, image_points, image_size, None, None)
    per_view = []
    for objp_i, imgp, r, t in zip(object_points, image_points, rvecs, tvecs):
        proj, _ = cv2.projectPoints(objp_i, r, t, K, dist)
        err = proj.reshape(-1, 2) - np.asarray(imgp).reshape(-1, 2)
        per_view.append(float(np.sqrt(np.mean(np.sum(err ** 2, axis=1)))))
    return {"rms": float(rms), "K": K, "dist": dist, "size": image_size, "per_view_error": per_view}


def save_calibration(path, calib: dict):
    np.savez(path, K=calib["K"], dist=calib["dist"], size=np.array(calib["size"]), rms=calib["rms"])


def load_calibration(path) -> dict:
    data = np.load(path)
    return {"K": data["K"], "dist": data["dist"], "size": tuple(int(v) for v in data["size"]),
            "rms": float(data["rms"])}


class Undistorter:
    """Pre-computes the remap tables once, then undistorts each frame cheaply.

    If frames arrive at a different resolution than the calibration images,
    the camera matrix is scaled accordingly.
    """

    def __init__(self, K, dist, calib_size, alpha: float = 0.0):
        self.K, self.dist = np.asarray(K, np.float64), np.asarray(dist, np.float64)
        self.calib_size, self.alpha = tuple(calib_size), alpha
        self._maps, self._size = None, None
        self.new_K = None   # intrinsics of the *undistorted* frames

    @classmethod
    def from_file(cls, path, alpha: float = 0.0):
        c = load_calibration(path)
        return cls(c["K"], c["dist"], c["size"], alpha)

    def _build(self, size):
        w, h = size
        sx, sy = w / self.calib_size[0], h / self.calib_size[1]
        K = self.K.copy()
        K[0, :] *= sx
        K[1, :] *= sy
        # alpha=0 crops to valid pixels only, alpha=1 keeps every source pixel
        newK, _ = cv2.getOptimalNewCameraMatrix(K, self.dist, size, self.alpha, size)
        self.new_K = newK
        self._maps = cv2.initUndistortRectifyMap(K, self.dist, None, newK, size, cv2.CV_16SC2)
        self._size = size

    def __call__(self, frame: np.ndarray) -> np.ndarray:
        size = (frame.shape[1], frame.shape[0])
        if self._size != size:
            self._build(size)
        return cv2.remap(frame, *self._maps, interpolation=cv2.INTER_LINEAR)


def apply_distortion(img: np.ndarray, K, dist) -> np.ndarray:
    """Simulate a lens: produce the image a camera with (K, dist) would capture.

    For every output (distorted) pixel we ask undistortPoints where it comes from
    in the ideal image and sample it with remap. Handy for demos and tests.
    """
    h, w = img.shape[:2]
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1).reshape(-1, 1, 2)
    src = cv2.undistortPoints(pts, K, dist, P=K).reshape(h, w, 2)
    return cv2.remap(img, src[..., 0], src[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
