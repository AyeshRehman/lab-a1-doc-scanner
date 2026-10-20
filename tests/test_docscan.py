"""Run with:  python -m pytest -q      (or:  python tests/test_docscan.py)

Synthetic photos have known ground truth, so we can test accuracy, not just
"it didn't crash".
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docscan import scan_document, synthetic  # noqa: E402
from docscan.camera import Undistorter, apply_distortion, calibrate, find_chessboard  # noqa: E402
from docscan.detect import find_document, find_punch_holes  # noqa: E402
from docscan.enhance import MODES, enhance  # noqa: E402
from docscan.features import align_to_template  # noqa: E402
from docscan.geometry import estimate_aspect, four_point_warp, order_points, rotate  # noqa: E402

PAGE_RATIO = 1100 / 850


def test_order_points_handles_any_input_order_and_45_degrees():
    square = np.float32([[0, 0], [10, 0], [10, 10], [0, 10]])
    for perm in ([2, 0, 3, 1], [3, 2, 1, 0], [1, 3, 0, 2]):
        assert np.allclose(order_points(square[perm]), square)
    diamond = np.float32([[5, 0], [10, 5], [5, 10], [0, 5]])   # rotated 45 deg
    ordered = order_points(diamond[[2, 0, 3, 1]])
    assert len({tuple(p) for p in ordered}) == 4               # no duplicate corners


def test_four_point_warp_size_and_aspect():
    img = np.zeros((200, 300, 3), np.uint8)
    pts = [[10, 10], [210, 10], [210, 110], [10, 110]]
    warped, H = four_point_warp(img, pts)
    assert warped.shape[:2] == (100, 200)   # side lengths become the output size
    warped, _ = four_point_warp(img, pts, aspect=2.0)        # force height = 2 * width
    assert abs(warped.shape[0] / warped.shape[1] - 2.0) < 0.02


def test_rotate_expand_keeps_whole_image():
    img = np.zeros((100, 200), np.uint8)
    out = rotate(img, 90)
    assert out.shape == (200, 100)


def test_detection_is_subpixel_accurate_across_poses():
    page = synthetic.make_page()
    for tilt, spin, shift in [(30, 6, (0, 0)), (50, -12, (0, 0)), (20, 35, (3, 1)), (0, 0, (0, 0))]:
        true = synthetic.project_page(page.shape, tilt, spin, shift=shift)
        photo, _ = synthetic.make_photo(page, corners=true)
        det = find_document(photo)
        assert det is not None, (tilt, spin)
        err = np.abs(det.corners - true).max()
        assert err < 2.0, f"corner error {err:.2f}px at tilt={tilt} spin={spin}"


def test_aspect_ratio_recovered_from_perspective():
    page = synthetic.make_page()
    for tilt, spin in [(30, 6), (45, -10), (15, 30)]:
        true = synthetic.project_page(page.shape, tilt, spin)
        assert abs(estimate_aspect(true, (1280, 960)) - PAGE_RATIO) < 0.005
        assert abs(estimate_aspect(true, (1280, 960), synthetic.CAMERA_K) - PAGE_RATIO) < 0.005


def test_no_document_returns_none():
    desk = synthetic.make_desk(640, 480)
    assert find_document(desk) is None


def test_full_pipeline_all_modes():
    photo, _ = synthetic.make_photo()
    for mode in MODES:
        result = scan_document(photo, mode)
        assert result.detection is not None
        h, w = result.scan.shape[:2]
        assert abs(h / w - PAGE_RATIO) < 0.03
    bw = scan_document(photo, "bw").scan
    assert set(np.unique(bw)) <= {0, 255}


def test_shadow_removal_flattens_paper():
    photo, _ = synthetic.make_photo()
    result = scan_document(photo, "original")
    gray_before = cv2.cvtColor(result.warped, cv2.COLOR_BGR2GRAY)
    gray_after = enhance(result.warped, "gray")
    # paper brightness should vary far less across the page after flattening
    def spread(g):
        paper = g[g > np.percentile(g, 50)]
        return np.percentile(paper, 95) - np.percentile(paper, 5)
    assert spread(gray_after) < spread(gray_before) / 2


def test_punch_holes_found_and_removed():
    photo, _ = synthetic.make_photo()
    warped = scan_document(photo, "original").warped
    assert len(find_punch_holes(warped)) == 3
    result = scan_document(photo, "original", holes=True)
    assert len(find_punch_holes(result.warped)) == 0


def test_feature_alignment_orb_and_sift():
    page = synthetic.make_page()
    photo, _ = synthetic.make_photo(page)
    for method in ("orb", "sift"):
        a = align_to_template(photo, page, method)
        assert a.H is not None and a.n_inliers > 30, method
        # the aligned photo should look like the template
        diff = cv2.absdiff(cv2.cvtColor(a.aligned, cv2.COLOR_BGR2GRAY),
                           cv2.cvtColor(page, cv2.COLOR_BGR2GRAY))
        assert np.median(diff) < 60, method


def test_calibration_recovers_lens():
    K = np.array([[900.0, 0, 640], [0, 900.0, 480], [0, 0, 1]])
    dist = np.array([-0.25, 0.08, 0, 0, 0])
    board = cv2.cvtColor(synthetic.make_chessboard((9, 6)), cv2.COLOR_GRAY2BGR)
    rng = np.random.default_rng(1)
    points = []
    for i in range(10):
        c = synthetic.project_page(board.shape, rng.uniform(-30, 30), rng.uniform(-20, 20),
                                   distance=rng.uniform(32, 42),
                                   shift=(rng.uniform(-5, 5), rng.uniform(-3, 3)), K=K)
        view, _ = synthetic.make_photo(board, corners=c, seed=i, shadow=False)
        view = apply_distortion(view, K, dist)
        corners = find_chessboard(cv2.cvtColor(view, cv2.COLOR_BGR2GRAY), (9, 6))
        if corners is not None:
            points.append(corners)
    assert len(points) >= 8
    calib = calibrate(points, (9, 6), (1280, 960))
    assert calib["rms"] < 0.5
    assert abs(calib["K"][0, 0] - 900) < 15
    assert max(calib["per_view_error"]) < 0.5
    und = Undistorter(calib["K"], calib["dist"], (1280, 960))
    assert und(view).shape == view.shape


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} tests passed")
