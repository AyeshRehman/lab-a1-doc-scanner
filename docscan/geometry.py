"""Geometric transforms: resize, crop, rotate, affine and perspective warps.

* Affine (2x3 matrix, 3 point pairs): keeps parallel lines parallel
  (translation, rotation, scale, shear).
* Perspective / homography (3x3 matrix, 4 point pairs): straight lines stay straight
  but parallel lines may meet - exactly what happens when you photograph a sheet
  of paper at an angle. Undoing it gives a "flat" top-down view.
"""

from __future__ import annotations

import cv2
import numpy as np


def resize(img: np.ndarray, width: int | None = None, height: int | None = None,
           interpolation: int | None = None) -> np.ndarray:
    """Resize keeping the aspect ratio. Give either width or height.

    INTER_AREA is the best choice for shrinking, INTER_CUBIC/LINEAR for enlarging.
    """
    h, w = img.shape[:2]
    if width is None and height is None:
        return img
    if width is not None:
        scale = width / w
    else:
        scale = height / h
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))  # cv2 wants (w, h)
    if interpolation is None:
        interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, new_size, interpolation=interpolation)


def crop(img: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """Crop is plain NumPy slicing: rows (y) first, then columns (x).

    Slicing returns a *view* - call .copy() if you will modify it independently.
    """
    return img[y:y + h, x:x + w]


def rotate(img: np.ndarray, angle: float, expand: bool = True,
           border: int = cv2.BORDER_REPLICATE) -> np.ndarray:
    """Rotate counter-clockwise by `angle` degrees about the centre.

    With expand=True the output canvas grows so no corner is cut off; we just add
    the needed shift to the translation column of the 2x3 affine matrix.
    """
    h, w = img.shape[:2]
    cx, cy = w / 2, h / 2
    M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    out_w, out_h = w, h
    if expand:
        cos, sin = abs(M[0, 0]), abs(M[0, 1])
        out_w = int(round(h * sin + w * cos))
        out_h = int(round(h * cos + w * sin))
        M[0, 2] += out_w / 2 - cx
        M[1, 2] += out_h / 2 - cy
    return cv2.warpAffine(img, M, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=border)


def affine_warp(img: np.ndarray, src_pts, dst_pts, size: tuple[int, int] | None = None) -> np.ndarray:
    """Warp with the affine transform that maps 3 src points onto 3 dst points."""
    M = cv2.getAffineTransform(np.float32(src_pts), np.float32(dst_pts))
    h, w = img.shape[:2]
    return cv2.warpAffine(img, M, size or (w, h), borderMode=cv2.BORDER_CONSTANT)


def order_points(pts) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left.

    Sorting by angle around the centroid is robust even for sheets rotated ~45 deg
    (the classic "x+y / y-x" trick breaks there).
    """
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    centre = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0])
    pts = pts[np.argsort(angles)]          # clockwise on screen (y points down)
    start = int(np.argmin(pts.sum(axis=1)))  # top-left has the smallest x + y
    return np.roll(pts, -start, axis=0)


def estimate_aspect(pts, image_size: tuple[int, int], K: np.ndarray | None = None) -> float | None:
    """Real height/width ratio of a rectangle seen in perspective.

    Edge lengths in the photo are foreshortened, so a tilted sheet looks squatter
    than it is. Using the pinhole camera model (Zhang & He, "Whiteboard scanning
    and image enhancement", 2007) we recover the true ratio. The focal length is
    taken from K when you have a calibration, otherwise it is estimated from the
    quad itself, assuming the principal point is the image centre.
    Returns None when the geometry is degenerate.
    """
    tl, tr, br, bl = order_points(pts).astype(np.float64)
    if K is not None:
        u0, v0 = K[0, 2], K[1, 2]
    else:
        u0, v0 = image_size[0] / 2.0, image_size[1] / 2.0
    # shift so the principal point is the origin
    m1, m2, m3, m4 = (np.array([p[0] - u0, p[1] - v0, 1.0]) for p in (tl, tr, bl, br))

    k2 = np.dot(np.cross(m1, m4), m3) / np.dot(np.cross(m2, m4), m3)
    k3 = np.dot(np.cross(m1, m4), m2) / np.dot(np.cross(m3, m4), m2)
    n2 = k2 * m2 - m1          # direction of the top edge in 3D (up to scale)
    n3 = k3 * m3 - m1          # direction of the left edge

    if abs(n2[2]) < 1e-6 or abs(n3[2]) < 1e-6:
        # sheet is parallel to the sensor -> no perspective, plain lengths are right
        ratio_wh = np.hypot(n2[0], n2[1]) / np.hypot(n3[0], n3[1])
        return float(1.0 / ratio_wh)

    if K is not None:
        f = (K[0, 0] + K[1, 1]) / 2.0
    else:
        f2 = -(n2[0] * n3[0] + n2[1] * n3[1]) / (n2[2] * n3[2])
        if f2 <= 0:
            return None
        f = np.sqrt(f2)
    A_inv = np.diag([1.0 / f, 1.0 / f, 1.0])
    w2 = np.dot(A_inv @ n2, A_inv @ n2)
    h2 = np.dot(A_inv @ n3, A_inv @ n3)
    if w2 <= 0 or h2 <= 0:
        return None
    aspect = float(np.sqrt(h2 / w2))
    return aspect if 0.2 < aspect < 5 else None


def four_point_warp(img: np.ndarray, pts, aspect: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Perspective-correct the quadrilateral `pts` into an upright rectangle.

    Output size comes from the longest opposite edges, so no resolution is lost.
    `aspect` (height / width, e.g. 1.414 for A4) forces a known paper ratio.
    Returns (warped_image, 3x3 homography).
    """
    rect = order_points(pts)
    tl, tr, br, bl = rect
    width = max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))
    height = max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))
    if aspect:
        # keep the longer measured side, derive the other one from the ratio
        if height >= width:
            width = height / aspect
        else:
            height = width * aspect
    w, h = int(round(width)), int(round(height))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(img, H, (w, h), flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)
    return warped, H
