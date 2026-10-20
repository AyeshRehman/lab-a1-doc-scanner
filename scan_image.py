"""Scan photos of documents.

Examples
--------
    python scan_image.py samples/photos/synthetic_photo.jpg
    python scan_image.py samples/photos/ --mode bw --debug
    python scan_image.py page.jpg --show --manual        # click the 4 corners yourself
    python scan_image.py page.jpg --aspect a4 --holes --deskew
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from docscan import scan_document
from docscan.camera import Undistorter
from docscan.enhance import MODES
from docscan.geometry import resize
from docscan.viz import draw_quad, montage

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
PAPER_RATIOS = {"a4": 297 / 210, "letter": 11 / 8.5, "legal": 14 / 8.5}


def collect_inputs(paths: list[str]) -> list[Path]:
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS)
        elif p.exists():
            files.append(p)
        else:
            files += sorted(Path().glob(str(p)))
    return files


def parse_aspect(value: str):
    if value == "auto":
        return "auto"
    if value == "none":
        return None
    if value.lower() in PAPER_RATIOS:
        return PAPER_RATIOS[value.lower()]
    return float(value)


def pick_corners(img: np.ndarray, initial=None):
    """Let the user click 4 corners. Left click = add point, r = reset, Enter = accept."""
    view = resize(img, height=800) if img.shape[0] > 800 else img
    scale = img.shape[0] / view.shape[0]
    pts = [] if initial is None else [tuple(p / scale) for p in initial]
    win = "click the 4 corners - Enter: accept, r: reset, Esc: skip"

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((x, y))

    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)
    while True:
        canvas = view.copy()
        for p in pts:
            cv2.circle(canvas, (int(p[0]), int(p[1])), 6, (0, 0, 255), -1)
        if len(pts) == 4:
            canvas = draw_quad(canvas, pts)
        cv2.imshow(win, canvas)
        key = cv2.waitKey(20) & 0xFF
        if key == ord("r"):
            pts.clear()
        elif key in (13, 10) and len(pts) == 4:
            break
        elif key == 27:
            pts = None
            break
    cv2.destroyWindow(win)
    return None if pts is None else np.float32(pts) * scale


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="image files, folders or glob patterns")
    ap.add_argument("--mode", choices=MODES, default="color")
    ap.add_argument("--out", default="outputs/scans", help="output folder")
    ap.add_argument("--aspect", type=parse_aspect, default="auto",
                    help="auto | none | a4 | letter | legal | <height/width>")
    ap.add_argument("--min-area", type=float, default=0.15, help="min page area as fraction of image")
    ap.add_argument("--deskew", action="store_true", help="straighten text lines with Hough lines")
    ap.add_argument("--holes", action="store_true", help="remove punch holes (Hough circles)")
    ap.add_argument("--calib", help="calibration .npz from calibrate.py (undistort first)")
    ap.add_argument("--debug", action="store_true", help="also save a montage of every step")
    ap.add_argument("--show", action="store_true", help="display results in a window")
    ap.add_argument("--manual", action="store_true", help="always pick corners by hand")
    args = ap.parse_args(argv)

    files = collect_inputs(args.inputs)
    if not files:
        print("no input images found", file=sys.stderr)
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    K, undistort = None, None
    if args.calib:
        undistort = Undistorter.from_file(args.calib)

    for path in files:
        img = cv2.imread(str(path))
        if img is None:
            print(f"[skip] cannot read {path}")
            continue
        if undistort:
            img = undistort(img)
            K = undistort.new_K   # intrinsics of the undistorted image -> better aspect estimate

        corners = None
        if args.manual:
            corners = pick_corners(img)
        result = scan_document(img, args.mode, corners=corners, min_area_ratio=args.min_area,
                               aspect=args.aspect, K=K, do_deskew=args.deskew,
                               holes=args.holes, keep_steps=args.debug)
        if result.detection is None and args.show and not args.manual:
            print(f"[{path.name}] detection failed - pick the corners manually")
            corners = pick_corners(img)
            if corners is not None:
                result = scan_document(img, args.mode, corners=corners, aspect=args.aspect, K=K,
                                       do_deskew=args.deskew, holes=args.holes, keep_steps=args.debug)

        out_path = out_dir / f"{path.stem}_scan_{args.mode}.png"
        cv2.imwrite(str(out_path), result.scan)
        print(f"[{path.name}] {'; '.join(result.notes)} -> {out_path}")

        if args.debug:
            dbg = out_dir / f"{path.stem}_steps.jpg"
            cv2.imwrite(str(dbg), montage(result.steps))
            print(f"    steps montage -> {dbg}")

        if args.show:
            left = draw_quad(img, result.detection.corners) if result.detection else img
            view = montage({"input": left, f"scan ({args.mode})": result.scan}, cols=2, cell=(640, 720))
            cv2.imshow("scan - any key for next", view)
            cv2.waitKey(0)
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
