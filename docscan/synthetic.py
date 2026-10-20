"""Synthetic test data: a fake page photographed at an angle on a wooden desk.

Because we choose the camera geometry ourselves, we know the *true* corners and
can measure how accurate the detector is (see tests/).
"""

from __future__ import annotations

import string

import cv2
import numpy as np


def make_page(w: int = 850, h: int = 1100, seed: int = 0, punch_holes: bool = True) -> np.ndarray:
    rng = np.random.default_rng(seed)
    page = np.full((h, w, 3), 248, np.uint8)
    cv2.rectangle(page, (60, 50), (w - 60, 140), (170, 90, 30), -1)          # blue header bar
    cv2.putText(page, "LAB A1 - DOCUMENT SCANNER", (80, 110),
                cv2.FONT_HERSHEY_DUPLEX, 1.25, (255, 255, 255), 2, cv2.LINE_AA)
    letters = np.array(list(string.ascii_lowercase))
    y = 200
    while y < h - 260:
        x = 80
        while True:
            word = "".join(rng.choice(letters, rng.integers(2, 9)))
            (tw, _), _ = cv2.getTextSize(word, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            if x + tw > w - 80:
                break
            cv2.putText(page, word, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (25, 25, 25), 2, cv2.LINE_AA)
            x += tw + 14
        y += 36
    # a small table and a red stamp give the colour mode something to keep
    for i in range(4):
        cv2.line(page, (80, h - 230 + i * 40), (w - 300, h - 230 + i * 40), (60, 60, 60), 2)
    cv2.circle(page, (w - 160, h - 160), 70, (40, 40, 200), 4, cv2.LINE_AA)
    cv2.putText(page, "OK", (w - 195, h - 145), cv2.FONT_HERSHEY_DUPLEX, 1.4, (40, 40, 200), 3, cv2.LINE_AA)
    if punch_holes:
        for fy in (0.25, 0.5, 0.75):
            cv2.circle(page, (34, int(h * fy)), 14, (70, 55, 40), -1, cv2.LINE_AA)
    return page


def make_desk(w: int, h: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1, (h, w)).astype(np.float32)
    grain = cv2.GaussianBlur(noise, (0, 0), sigmaX=40, sigmaY=2)      # streaky wood grain
    grain = cv2.normalize(grain, None, 0, 1, cv2.NORM_MINMAX)
    base = np.array([45, 85, 130], np.float32)                         # brown in BGR
    desk = base * (0.7 + 0.5 * grain[..., None])
    return np.clip(desk, 0, 255).astype(np.uint8)


CAMERA_K = np.array([[1000.0, 0, 640], [0, 1000.0, 480], [0, 0, 1]])


def project_page(page_shape, tilt_deg: float = 30.0, spin_deg: float = 6.0,
                 distance: float = 40.0, shift=(0.0, 0.0), K=CAMERA_K) -> np.ndarray:
    """Where the 4 page corners land when a real pinhole camera looks at the sheet.

    The page is a flat rectangle (in cm, letter-sized) on the z = 0 plane; the camera
    is tilted by `tilt_deg` about x and the page is spun by `spin_deg` about z.
    """
    ph, pw = page_shape[:2]
    W = 21.6
    H = W * ph / pw
    obj = np.float32([[-W / 2, -H / 2, 0], [W / 2, -H / 2, 0], [W / 2, H / 2, 0], [-W / 2, H / 2, 0]])
    rz = np.radians(spin_deg)
    Rz = np.array([[np.cos(rz), -np.sin(rz), 0], [np.sin(rz), np.cos(rz), 0], [0, 0, 1]])
    Rx, _ = cv2.Rodrigues(np.array([np.radians(tilt_deg), 0, 0]))
    rvec, _ = cv2.Rodrigues(Rx @ Rz)
    tvec = np.array([shift[0], shift[1], distance], np.float64)
    img_pts, _ = cv2.projectPoints(obj, rvec, tvec, K, None)
    return img_pts.reshape(4, 2).astype(np.float32)


def make_photo(page: np.ndarray | None = None, size=(1280, 960), corners=None,
               seed: int = 0, shadow: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Place `page` on a desk, seen by CAMERA_K. Returns (photo, true_corners)."""
    rng = np.random.default_rng(seed)
    page = make_page(seed=seed) if page is None else page
    w, h = size
    corners = project_page(page.shape) if corners is None else np.float32(corners)
    ph, pw = page.shape[:2]
    src = np.float32([[0, 0], [pw - 1, 0], [pw - 1, ph - 1], [0, ph - 1]])
    H = cv2.getPerspectiveTransform(src, corners)
    warped = cv2.warpPerspective(page, H, (w, h))
    mask = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), H, (w, h))
    photo = make_desk(w, h, seed)
    photo[mask > 0] = warped[mask > 0]
    photo = photo.astype(np.float32)
    if shadow:   # a soft light gradient + a darker blob, like a hand/phone shadow
        xs, ys = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
        light = 0.75 + 0.3 * xs - 0.1 * ys
        light -= 0.25 * np.exp(-(((xs - 0.35) ** 2) + ((ys - 0.7) ** 2)) / 0.03)
        photo *= light[..., None]
    photo += rng.normal(0, 4, photo.shape)                               # sensor noise
    photo = cv2.GaussianBlur(np.clip(photo, 0, 255).astype(np.uint8), (3, 3), 0)
    return photo, corners


def make_chessboard(pattern=(9, 6), square: int = 60, margin: int = 60) -> np.ndarray:
    """Printable board with `pattern` INNER corners (so pattern+1 squares)."""
    cols, rows = pattern[0] + 1, pattern[1] + 1
    board = np.full((rows * square + 2 * margin, cols * square + 2 * margin), 255, np.uint8)
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                y, x = margin + r * square, margin + c * square
                board[y:y + square, x:x + square] = 0
    return board
