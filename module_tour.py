"""A guided tour of every Module A1 topic, run on one document photo.

    python module_tour.py                                   # uses the synthetic sample
    python module_tour.py --image my_photo.jpg --show

Writes one labelled figure per topic to outputs/tour/ and prints the numbers
(shapes, dtypes, thresholds, keypoint counts...) to the console.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from docscan import basics, detect, enhance, features, filters, geometry, synthetic
from docscan.camera import Undistorter, apply_distortion
from docscan.viz import draw_quad, montage


def section(title):
    print(f"\n=== {title} " + "=" * (60 - len(title)))


def fundamentals(img):
    section("1. Image fundamentals")
    for k, v in basics.describe(img).items():
        print(f"  {k:22s}: {v}")
    y, x = img.shape[0] // 2, img.shape[1] // 2
    print(f"  pixel at (x={x}, y={y}) img[y, x] = {img[y, x]}  <- B, G, R order")
    gray = basics.convert(img, "gray")
    print(f"  grayscale shape {gray.shape}  (one channel -> 2D array)")
    img16 = img.astype(np.uint16) * 257
    print(f"  as 16-bit: dtype {img16.dtype}, max {img16.max()}  (bit depth 16 -> 0..65535)")
    imgf = img.astype(np.float32) / 255.0
    print(f"  as float : dtype {imgf.dtype}, range {imgf.min():.2f}..{imgf.max():.2f}")

    b, g, r = basics.split_channels(img)
    h, w = img.shape[:2]
    return montage({
        "original (BGR, shown correctly)": img,
        "RGB array treated as BGR (red/blue swapped)": basics.bgr_to_rgb(img),
        "B channel": b, "G channel": g, "R channel": r,
        "2-bit per channel (bit depth)": basics.reduce_bit_depth(img, 2),
        "ROI +80 via slicing & broadcasting": basics.adjust_region(img, w // 4, h // 4, w // 2, h // 2, 80),
        "grayscale (1 channel)": gray,
        "img[::4, ::4] - subsample by slicing": img[::4, ::4],
    }, cols=3)


def color_spaces(img):
    section("2. Colour spaces & colour segmentation")
    hsv = basics.convert(img, "hsv")
    lab = basics.convert(img, "lab")
    print(f"  HSV ranges: H {hsv[..., 0].min()}..{hsv[..., 0].max()} (0..179), "
          f"S {hsv[..., 1].min()}..{hsv[..., 1].max()}, V {hsv[..., 2].min()}..{hsv[..., 2].max()}")
    mask = basics.paper_mask_hsv(img)
    print(f"  paper mask (low S, high V) covers {np.count_nonzero(mask) / mask.size:.0%} of the image")
    # segment the red stamp: red hue wraps around 0/180, so we need two ranges
    red = cv2.bitwise_or(cv2.inRange(hsv, (0, 80, 60), (10, 255, 255)),
                         cv2.inRange(hsv, (170, 80, 60), (179, 255, 255)))
    blue = cv2.inRange(hsv, (95, 80, 40), (130, 255, 255))
    return montage({
        "H (hue)": hsv[..., 0], "S (saturation)": hsv[..., 1], "V (value)": hsv[..., 2],
        "L (lightness)": lab[..., 0], "a (green-red)": lab[..., 1], "b (blue-yellow)": lab[..., 2],
        "HSV paper mask (S<70, V>Otsu)": mask,
        "paper only: bitwise_and(img, mask)": cv2.bitwise_and(img, img, mask=mask),
        "red + blue ink (hue ranges)": cv2.bitwise_and(img, img, mask=red | blue),
    }, cols=3)


def geometric(img, corners):
    section("3. Geometric transforms")
    h, w = img.shape[:2]
    small = geometry.resize(img, width=w // 4)
    nearest = cv2.resize(small[40:100, 100:180], None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
    cubic = cv2.resize(small[40:100, 100:180], None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    src3 = [[0, 0], [w - 1, 0], [0, h - 1]]
    dst3 = [[w * 0.1, h * 0.05], [w * 0.95, h * 0.2], [w * 0.2, h * 0.9]]
    warped, H = geometry.four_point_warp(img, corners, geometry.estimate_aspect(corners, (w, h)))
    print(f"  resize {img.shape[:2]} -> {small.shape[:2]} (INTER_AREA for shrinking)")
    print(f"  homography H (photo -> flat page):\n{np.array2string(H, precision=4, suppress_small=True)}")
    return montage({
        "resize to 1/4 (INTER_AREA)": small,
        "upscale x6: INTER_NEAREST": nearest, "upscale x6: INTER_CUBIC": cubic,
        "crop = img[y:y+h, x:x+w]": geometry.crop(img, w // 4, h // 4, w // 2, h // 2),
        "rotate 30 deg (canvas expanded)": geometry.rotate(img, 30),
        "affine warp (3 point pairs)": geometry.affine_warp(img, src3, dst3),
        "4 detected corners": draw_quad(img, corners),
        "perspective warp (4 point pairs)": warped,
        "flip (cv2.flip, code 1)": cv2.flip(img, 1),
    }, cols=3)


def filtering(img):
    section("4. Filtering, thresholding & morphology")
    gray = basics.convert(img, "gray")
    noisy = gray.copy()
    rng = np.random.default_rng(0)
    salt = rng.random(gray.shape)
    noisy[salt < 0.02], noisy[salt > 0.98] = 0, 255
    otsu_t, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    print(f"  Otsu picked threshold {otsu_t:.0f}")
    binary = cv2.threshold(gray, otsu_t, 255, cv2.THRESH_BINARY_INV)[1]  # text/edges = white
    return montage({
        "salt & pepper noise": noisy,
        "Gaussian blur 5x5": filters.gaussian_blur(noisy, 5),
        "median blur 5 (best for s&p)": filters.median_blur(noisy, 5),
        "bilateral (edge-preserving)": filters.bilateral(img),
        "sharpen kernel (filter2D)": filters.sharpen_kernel(img),
        "unsharp mask": filters.unsharp_mask(img, 2, 1.0),
        "global threshold 127": filters.threshold_global(gray),
        f"Otsu threshold ({otsu_t:.0f})": filters.threshold_otsu(gray),
        "adaptive Gaussian threshold": filters.threshold_adaptive(gray, 31, 10),
        "inverted binary": binary,
        "erode 3x3": filters.morph(binary, "erode", 3),
        "dilate 3x3": filters.morph(binary, "dilate", 3),
        "open 3x3 (erode->dilate)": filters.morph(binary, "open", 3),
        "close 9x9 (dilate->erode)": filters.morph(binary, "close", 9),
        "morph gradient (outline)": filters.morph(binary, "gradient", 3),
    }, cols=3)


def edges_shapes(img, scan):
    section("5. Edges & shapes")
    det = detect.find_document(img, keep_debug=True)
    gray = basics.convert(img, "gray")
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    contours, _ = cv2.findContours(det.debug["edges"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    print(f"  found {len(contours)} external contours; best quad by '{det.method}' "
          f"covering {det.area_ratio:.0%} of the frame")
    small = cv2.resize(img, det.debug["edges"].shape[::-1])
    cnt_img = small.copy()
    cv2.drawContours(cnt_img, contours, -1, (0, 255, 0), 2)
    biggest = max(contours, key=cv2.contourArea)
    approx_img = small.copy()
    for eps, col in ((0.002, (255, 0, 0)), (0.02, (0, 0, 255))):
        approx = cv2.approxPolyDP(biggest, eps * cv2.arcLength(biggest, True), True)
        cv2.drawContours(approx_img, [approx], -1, col, 2)
    lines_img = small.copy()
    for x1, y1, x2, y2 in detect.hough_lines(cv2.Canny(cv2.GaussianBlur(det.debug["gray"], (5, 5), 0), 50, 150)):
        cv2.line(lines_img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
    holes = detect.find_punch_holes(scan)
    circ = scan.copy()
    for x, y, r in holes:
        cv2.circle(circ, (x, y), r, (0, 0, 255), 3)
    print(f"  Hough circles: {len(holes)} punch hole(s) on the flattened page")
    return montage({
        "Canny 30/90": cv2.Canny(blur, 30, 90),
        "Canny 100/200": cv2.Canny(blur, 100, 200),
        "auto-Canny + close (used)": det.debug["edges"],
        "external contours": cnt_img,
        "approxPolyDP eps 0.2% (blue) / 2% (red)": approx_img,
        "HoughLinesP": lines_img,
        "all candidates": det.debug["candidates"],
        "HoughCircles: punch holes": circ,
        "final detection": draw_quad(img, det.corners),
    }, cols=3)


def feature_matching(img, template):
    section("6. Features & homography")
    out = {}
    for method in ("orb", "sift"):
        a = features.align_to_template(img, template, method)
        print(f"  {method.upper():4s}: {a.n_keypoints[0]} / {a.n_keypoints[1]} keypoints, "
              f"{a.n_matches} ratio-test matches, {a.n_inliers} RANSAC inliers")
        out[f"{method.upper()} keypoints (size+orientation)"] = features.draw_keypoints(img, method, 300)
        out[f"{method.upper()} inlier matches"] = a.visual
        out[f"{method.upper()}: photo warped by H"] = a.aligned if a.aligned is not None else np.zeros_like(template)
    return montage(out, cols=3)


def camera_basics(img):
    section("7. Camera basics: lens distortion")
    h, w = img.shape[:2]
    K = np.array([[0.8 * w, 0, w / 2], [0, 0.8 * w, h / 2], [0, 0, 1]])
    dist = np.array([-0.35, 0.12, 0, 0, 0])
    grid = img.copy()
    for x in range(0, w, w // 16):
        cv2.line(grid, (x, 0), (x, h), (0, 255, 255), 1)
    for y in range(0, h, h // 12):
        cv2.line(grid, (0, y), (w, y), (0, 255, 255), 1)
    distorted = apply_distortion(grid, K, dist)
    und0 = Undistorter(K, dist, (w, h), alpha=0)(distorted)
    und1 = Undistorter(K, dist, (w, h), alpha=1)(distorted)
    print(f"  simulated K:\n{K}\n  dist (k1 k2 p1 p2 k3): {dist}")
    print("  with a real camera these come from calibrate.py (chessboard, cv2.calibrateCamera)")
    pincushion = apply_distortion(grid, K, np.array([0.3, 0, 0, 0, 0]))
    return montage({
        "ideal (pinhole) image": grid,
        "barrel distortion k1<0": distorted,
        "pincushion distortion k1>0": pincushion,
        "undistorted, alpha=0 (crop)": und0,
        "undistorted, alpha=1 (keep all)": und1,
    }, cols=3)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", help="document photo (default: synthetic sample)")
    ap.add_argument("--template", help="clean version of the same page for the features demo")
    ap.add_argument("--out", default="outputs/tour")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args(argv)

    if args.image:
        img = cv2.imread(args.image)
        if img is None:
            print(f"cannot read {args.image}", file=sys.stderr)
            return 1
        img = geometry.resize(img, width=1280) if img.shape[1] > 1280 else img
    else:
        img, _ = synthetic.make_photo()
    template = cv2.imread(args.template) if args.template else synthetic.make_page()

    det = detect.find_document(img)
    if det is None:
        print("no document found in the image - the tour needs one", file=sys.stderr)
        return 1
    warped, _ = geometry.four_point_warp(img, det.corners, geometry.estimate_aspect(det.corners, img.shape[1::-1]))
    flat = filters.remove_shadows(warped)

    figures = {
        "01_fundamentals": fundamentals(img),
        "02_color_spaces": color_spaces(img),
        "03_geometry": geometric(img, det.corners),
        "04_filtering": filtering(img),
        "05_edges_shapes": edges_shapes(img, flat),
        "06_features": feature_matching(img, template),
        "07_camera": camera_basics(img),
        "08_scan_modes": montage({m: enhance.enhance(warped, m) for m in enhance.MODES},
                                 cols=4, cell=(360, 460)),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, fig in figures.items():
        cv2.imwrite(str(out / f"{name}.jpg"), fig, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if args.show:
            cv2.imshow(name, geometry.resize(fig, width=1400) if fig.shape[1] > 1400 else fig)
            cv2.waitKey(0)
            cv2.destroyWindow(name)
    print(f"\nfigures written to {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
