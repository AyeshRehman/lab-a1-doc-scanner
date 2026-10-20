"""Calibrate a camera with a chessboard, then check the undistortion.

1. Print samples/chessboard_9x6.png (or show it full-screen on a phone/tablet).
2. Capture 10-20 views at different angles and distances:

    python calibrate.py --camera 0                     # live: press c to capture, q to finish
    python calibrate.py --images "calib_photos/*.jpg"  # from saved photos

3. Use the result in the scanner:  python scan_live.py --calib outputs/calib.npz

`--pattern` is the number of INNER corners (columns x rows), not squares.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import cv2
import numpy as np

from docscan.camera import Undistorter, calibrate, find_chessboard, open_source, save_calibration
from docscan.viz import label, montage


def parse_pattern(s: str) -> tuple[int, int]:
    cols, rows = s.lower().split("x")
    return int(cols), int(rows)


def from_images(pattern_glob: str, pattern):
    points, size, used = [], None, []
    for path in sorted(glob.glob(pattern_glob)):
        img = cv2.imread(path)
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        size = size or (gray.shape[1], gray.shape[0])
        corners = find_chessboard(gray, pattern)
        print(f"{'found ' if corners is not None else 'MISSED'}  {path}")
        if corners is not None:
            points.append(corners)
            used.append(img)
    return points, size, used


def from_camera(source, pattern, save_dir: Path):
    cap = open_source(source)
    points, size, used = [], None, []
    save_dir.mkdir(parents=True, exist_ok=True)
    print("c = capture view, q = finish and calibrate")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        size = (gray.shape[1], gray.shape[0])
        corners = find_chessboard(gray, pattern)
        view = frame.copy()
        if corners is not None:
            cv2.drawChessboardCorners(view, pattern, corners, True)
        view = label(view, f"views: {len(points)}  (c: capture, q: calibrate)"
                           + ("" if corners is not None else "  - board not found"))
        cv2.imshow("calibration", view)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("c") and corners is not None:
            points.append(corners)
            used.append(frame.copy())
            cv2.imwrite(str(save_dir / f"view_{len(points):02d}.jpg"), frame)
        elif key in (ord("q"), 27):
            break
    cap.release()
    cv2.destroyAllWindows()
    return points, size, used


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--camera", help="webcam index or stream URL for live capture")
    src.add_argument("--images", help='glob of chessboard photos, e.g. "calib/*.jpg"')
    ap.add_argument("--pattern", type=parse_pattern, default=(9, 6), help="inner corners, e.g. 9x6")
    ap.add_argument("--square", type=float, default=1.0, help="square size (any unit, e.g. mm)")
    ap.add_argument("--out", default="outputs/calib.npz")
    args = ap.parse_args(argv)

    if args.images:
        points, size, used = from_images(args.images, args.pattern)
    else:
        points, size, used = from_camera(args.camera, args.pattern, Path("outputs/calib_views"))

    if len(points) < 5:
        print(f"need at least 5 good views, got {len(points)}", file=sys.stderr)
        return 1

    calib = calibrate(points, args.pattern, size, args.square)
    np.set_printoptions(precision=3, suppress=True)
    print(f"\nviews used         : {len(points)}")
    print(f"RMS reprojection   : {calib['rms']:.3f} px  (< 0.5 great, < 1.0 ok)")
    print(f"camera matrix K    :\n{calib['K']}")
    print(f"distortion (k1 k2 p1 p2 k3): {calib['dist'].ravel()}")
    worst = int(np.argmax(calib["per_view_error"]))
    print(f"worst view         : #{worst + 1} ({calib['per_view_error'][worst]:.3f} px) - "
          f"drop it and recalibrate if it is much worse than the rest")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    save_calibration(args.out, calib)
    print(f"saved -> {args.out}")

    # before / after comparison on the first view
    und = Undistorter(calib["K"], calib["dist"], size, alpha=0.0)
    before = used[0]
    after = und(before)
    cmp_path = Path(args.out).with_name("undistort_check.jpg")
    cv2.imwrite(str(cmp_path), montage({"original": before, "undistorted": after}, cols=2, cell=(640, 480)))
    print(f"before/after       -> {cmp_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
