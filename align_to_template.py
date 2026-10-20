"""Feature-based scanning: align a photo of a KNOWN document to its clean template.

The contour scanner needs to see the page outline. When you scan a form you
already have digitally (an exam sheet, an invoice layout...), keypoints on the
printed content are enough: ORB/SIFT -> ratio-test matches -> RANSAC homography
-> warp the photo into the template's frame. Works even if the page edges are
cut off or the sheet lies on white paper.

    python align_to_template.py --template samples/templates/synthetic_page.png --image samples/photos/synthetic_photo.jpg
    python align_to_template.py --template form.png --image photo.jpg --method sift
    python align_to_template.py --template form.png --camera 0     # live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from docscan.camera import open_source
from docscan.features import align_to_template
from docscan.viz import fit, label, montage


def report(a, method):
    print(f"{method.upper()}: keypoints photo/template = {a.n_keypoints}, "
          f"good matches = {a.n_matches}, RANSAC inliers = {a.n_inliers}")
    if a.H is not None:
        np.set_printoptions(precision=4, suppress=True)
        print(f"homography (photo -> template):\n{a.H}")
    else:
        print("not enough inliers - alignment failed")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--image")
    src.add_argument("--camera", help="webcam index / video / rtsp URL for live alignment")
    ap.add_argument("--method", choices=["orb", "sift"], default="orb")
    ap.add_argument("--ratio", type=float, default=0.75, help="Lowe ratio test threshold")
    ap.add_argument("--out", default="outputs/aligned")
    args = ap.parse_args(argv)

    template = cv2.imread(args.template)
    if template is None:
        print(f"cannot read {args.template}", file=sys.stderr)
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.image:
        image = cv2.imread(args.image)
        a = align_to_template(image, template, args.method, args.ratio)
        report(a, args.method)
        stem = Path(args.image).stem
        cv2.imwrite(str(out_dir / f"{stem}_matches_{args.method}.jpg"), a.visual)
        if a.aligned is not None:
            cv2.imwrite(str(out_dir / f"{stem}_aligned_{args.method}.png"), a.aligned)
            # difference image: anything written on the form shows up here
            diff = cv2.absdiff(cv2.cvtColor(a.aligned, cv2.COLOR_BGR2GRAY),
                               cv2.cvtColor(template, cv2.COLOR_BGR2GRAY))
            cv2.imwrite(str(out_dir / f"{stem}_diff_{args.method}.png"), diff)
        print(f"outputs -> {out_dir}")
        return 0

    # live mode: matching every frame is slow-ish, ORB is recommended here
    cap = open_source(args.camera)
    print("q to quit, s to save the aligned frame")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        a = align_to_template(frame, template, args.method, args.ratio)
        right = a.aligned if a.aligned is not None else np.zeros_like(template)
        view = montage({f"camera ({a.n_inliers} inliers)": frame, "aligned to template": right},
                       cols=2, cell=(560, 520))
        cv2.imshow("template alignment", view)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("s") and a.aligned is not None:
            cv2.imwrite(str(out_dir / "live_aligned.png"), a.aligned)
            print("saved")
    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
