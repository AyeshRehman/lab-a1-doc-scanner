"""Generate test data so every script can be tried without a camera.

    samples/templates/synthetic_page.png  - the clean "digital original" (template)
    samples/photos/synthetic_photo.jpg    - that page photographed at an angle on a desk
    samples/photos/synthetic_photo_*.jpg  - more poses (steep tilt, rotated, etc.)
    samples/synthetic_video.mp4           - the page moving under the camera (for scan_live)
    samples/chessboard_9x6.png            - print this for calibrate.py
    samples/calib_synth/*.png             - chessboard views through a distorting lens
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from docscan import synthetic
from docscan.camera import apply_distortion

OUT = Path("samples")

# a simulated lens with noticeable barrel distortion, used for calibration samples
LENS_K = np.array([[900.0, 0, 640], [0, 900.0, 480], [0, 0, 1]])
LENS_DIST = np.array([-0.28, 0.09, 0.0005, -0.0004, 0.0])


def main():
    photos, templates = OUT / "photos", OUT / "templates"
    photos.mkdir(parents=True, exist_ok=True)
    templates.mkdir(parents=True, exist_ok=True)
    page = synthetic.make_page()
    cv2.imwrite(str(templates / "synthetic_page.png"), page)

    photo, _ = synthetic.make_photo(page)
    cv2.imwrite(str(photos / "synthetic_photo.jpg"), photo, [cv2.IMWRITE_JPEG_QUALITY, 92])
    poses = {"steep": (50, 8, (0, 0)), "rotated": (25, 35, (2, 0)), "flat": (5, -3, (0, 0))}
    for name, (tilt, spin, shift) in poses.items():
        c = synthetic.project_page(page.shape, tilt, spin, shift=shift)
        img, _ = synthetic.make_photo(page, corners=c, seed=1)
        cv2.imwrite(str(photos / f"synthetic_photo_{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])

    # video: page slides in, holds still (auto-capture should fire), tilts, leaves
    writer = cv2.VideoWriter(str(OUT / "synthetic_video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                             20, (1280, 960))
    n = 120
    for i in range(n):
        t = i / (n - 1)
        if t < 0.2:          # slide in from the left
            shift, tilt, spin = (-30 + 150 * t, 0), 30, 6
        elif t < 0.55:       # hold still
            shift, tilt, spin = (0, 0), 30, 6
        elif t < 0.85:       # tilt and rotate
            k = (t - 0.55) / 0.3
            shift, tilt, spin = (0, 0), 30 + 15 * k, 6 - 20 * k
        else:                # move away
            k = (t - 0.85) / 0.15
            shift, tilt, spin = (40 * k, 0), 45, -14
        c = synthetic.project_page(page.shape, tilt, spin, shift=shift)
        frame, _ = synthetic.make_photo(page, corners=c, seed=i % 3)
        writer.write(frame)
    writer.release()

    board = synthetic.make_chessboard((9, 6))
    cv2.imwrite(str(OUT / "chessboard_9x6.png"), board)

    calib_dir = OUT / "calib_synth"
    calib_dir.mkdir(exist_ok=True)
    board_bgr = cv2.cvtColor(board, cv2.COLOR_GRAY2BGR)
    rng = np.random.default_rng(0)
    for i in range(15):
        tilt, spin = rng.uniform(-35, 35), rng.uniform(-25, 25)
        shift = (rng.uniform(-6, 6), rng.uniform(-4, 4))
        c = synthetic.project_page(board.shape, tilt, spin, distance=rng.uniform(32, 45),
                                   shift=shift, K=LENS_K)
        ideal, _ = synthetic.make_photo(board_bgr, corners=c, seed=i, shadow=False)
        cv2.imwrite(str(calib_dir / f"view_{i:02d}.png"), apply_distortion(ideal, LENS_K, LENS_DIST))

    print(f"samples written to {OUT.resolve()}")


if __name__ == "__main__":
    main()
