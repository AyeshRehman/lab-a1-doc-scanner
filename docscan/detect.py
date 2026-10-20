"""Finding the paper sheet: edges, contours, colour masks and Hough transforms.

Strategy (all run on a downscaled copy for speed, corners are scaled back):

1. **Edges**  - Gaussian blur -> Canny -> morphological close -> contours ->
                approxPolyDP to 4 corners.
2. **Colour** - paper is bright and unsaturated -> HSV / LAB / Otsu masks ->
                open/close -> largest contour -> 4 corners.
3. **Hough**  - fallback when a corner is hidden (e.g. by your hand): find the
                4 dominant straight lines with HoughLinesP and intersect them.

Every candidate quad is checked (big enough, convex, sane angles) and the
largest valid one wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from . import basics, filters
from .geometry import order_points, rotate

DETECT_HEIGHT = 500  # work resolution in pixels


@dataclass
class Detection:
    corners: np.ndarray          # (4, 2) float32, TL TR BR BL, full-resolution coords
    method: str                  # "edges" | "color" | "hough"
    area_ratio: float            # quad area / image area
    debug: dict = field(default_factory=dict, repr=False)


# --------------------------------------------------------------------------- edges
def auto_canny(gray: np.ndarray, sigma: float = 0.33) -> np.ndarray:
    """Canny with thresholds placed around the median intensity."""
    v = float(np.median(gray))
    lower = int(max(0, (1.0 - sigma) * v))
    upper = int(min(255, (1.0 + sigma) * v))
    return cv2.Canny(gray, lower, upper)


def edge_map(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.bitwise_or(auto_canny(blur), cv2.Canny(blur, 50, 150))
    # close small gaps so the paper outline becomes one connected contour
    return filters.morph(edges, "close", 5, iterations=2)


# --------------------------------------------------------------------------- quads
def quad_from_contour(contour: np.ndarray) -> np.ndarray | None:
    """Simplify a contour to 4 vertices with Douglas-Peucker (approxPolyDP)."""
    for cnt in (contour, cv2.convexHull(contour)):
        peri = cv2.arcLength(cnt, True)
        for eps in (0.02, 0.03, 0.04, 0.06, 0.08):
            approx = cv2.approxPolyDP(cnt, eps * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                return approx.reshape(4, 2).astype(np.float32)
    return None


def interior_angles(quad: np.ndarray) -> list[float]:
    angles = []
    for i in range(4):
        p_prev, p, p_next = quad[i - 1], quad[i], quad[(i + 1) % 4]
        v1, v2 = p_prev - p, p_next - p
        cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        angles.append(float(np.degrees(np.arccos(np.clip(cos, -1, 1)))))
    return angles


def quad_score(quad: np.ndarray, shape, min_area_ratio: float) -> float:
    """Area ratio of a plausible document quad, or 0 if it is not plausible."""
    quad = order_points(quad)
    h, w = shape[:2]
    ratio = cv2.contourArea(quad) / float(h * w)
    if ratio < min_area_ratio or ratio > 0.995:
        return 0.0
    if not cv2.isContourConvex(quad.reshape(-1, 1, 2)):
        return 0.0
    if not all(35 <= a <= 145 for a in interior_angles(quad)):
        return 0.0
    return ratio


def biggest_contours(binary: np.ndarray, n: int = 8, mode=cv2.RETR_LIST):
    contours, _ = cv2.findContours(binary, mode, cv2.CHAIN_APPROX_SIMPLE)
    return sorted(contours, key=cv2.contourArea, reverse=True)[:n]


# --------------------------------------------------------------------------- colour
def paper_mask(img: np.ndarray) -> np.ndarray:
    """Union of a few colour-segmentation masks for 'white paper', cleaned with morphology."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = cv2.bitwise_or(basics.paper_mask_hsv(img), basics.paper_mask_lab(img))
    mask = cv2.bitwise_and(mask, filters.threshold_otsu(cv2.GaussianBlur(gray, (5, 5), 0)))
    mask = filters.morph(mask, "open", 5)          # remove specks
    mask = filters.morph(mask, "close", 15)        # fill text holes inside the page
    return mask


# --------------------------------------------------------------------------- hough
def _intersect(l1, l2):
    """Intersection of two lines given as (x1, y1, x2, y2), via homogeneous coords."""
    p = lambda x, y: np.array([x, y, 1.0])
    a = np.cross(p(*l1[:2]), p(*l1[2:]))
    b = np.cross(p(*l2[:2]), p(*l2[2:]))
    x = np.cross(a, b)
    if abs(x[2]) < 1e-9:
        return None
    return x[:2] / x[2]


def hough_lines(edges: np.ndarray, min_len_ratio: float = 0.25):
    h, w = edges.shape[:2]
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                            minLineLength=int(min_len_ratio * min(h, w)), maxLineGap=20)
    # OpenCV 4 returns shape (N, 1, 4), OpenCV 5 (N, 4) - reshape handles both
    return [] if lines is None else [tuple(map(float, l)) for l in lines.reshape(-1, 4)]


def quad_from_hough(edges: np.ndarray) -> np.ndarray | None:
    """Take the outermost near-horizontal and near-vertical lines and intersect them."""
    h, w = edges.shape[:2]
    horiz, vert = [], []
    for x1, y1, x2, y2 in hough_lines(edges):
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
        (horiz if angle < 45 or angle > 135 else vert).append((x1, y1, x2, y2))
    if len(horiz) < 2 or len(vert) < 2:
        return None
    mid_y = lambda l: (l[1] + l[3]) / 2
    mid_x = lambda l: (l[0] + l[2]) / 2
    top, bottom = min(horiz, key=mid_y), max(horiz, key=mid_y)
    left, right = min(vert, key=mid_x), max(vert, key=mid_x)
    if mid_y(bottom) - mid_y(top) < 0.2 * h or mid_x(right) - mid_x(left) < 0.2 * w:
        return None
    pts = [_intersect(top, left), _intersect(top, right),
           _intersect(bottom, right), _intersect(bottom, left)]
    if any(p is None for p in pts):
        return None
    return np.array(pts, dtype=np.float32)


# --------------------------------------------------------------------------- refinement
def refine_corners(gray: np.ndarray, corners: np.ndarray, band_ratio: float = 0.012) -> np.ndarray:
    """Sub-pixel corners: fit a straight line to the full-resolution Canny edge
    pixels along each side (cv2.fitLine, robust Huber loss) and intersect
    neighbouring lines. Falls back to the input if a side has too little support
    (e.g. hidden under a hand)."""
    h, w = gray.shape[:2]
    band = max(4.0, band_ratio * max(h, w))
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    ys, xs = np.nonzero(edges)
    pts = np.stack([xs, ys], axis=1).astype(np.float32)
    lines = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        d = b - a
        length = float(np.linalg.norm(d))
        normal = np.array([-d[1], d[0]]) / length
        rel = pts - a
        t = rel @ d / length ** 2                  # position along the side, 0..1
        dist = np.abs(rel @ normal)                # distance from the side
        side = pts[(dist < band) & (t > 0.1) & (t < 0.9)]
        if len(side) < 0.3 * length:
            return corners
        vx, vy, x0, y0 = cv2.fitLine(side, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((x0, y0, x0 + vx, y0 + vy))
    refined = [_intersect(lines[i - 1], lines[i]) for i in range(4)]  # corner i joins sides i-1 and i
    if any(p is None for p in refined):
        return corners
    refined = np.float32(refined)
    if np.abs(refined - corners).max() > 2 * band:
        return corners
    return refined


# --------------------------------------------------------------------------- main
def find_document(img: np.ndarray, min_area_ratio: float = 0.15,
                  keep_debug: bool = False, refine: bool = True) -> Detection | None:
    """Locate the largest paper-like quadrilateral in a BGR image."""
    h = img.shape[0]
    scale = DETECT_HEIGHT / h if h > DETECT_HEIGHT else 1.0
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1 else img
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    candidates = []  # (score, method, quad)

    edges = edge_map(gray)
    for cnt in biggest_contours(edges):
        quad = quad_from_contour(cnt)
        if quad is not None:
            candidates.append((quad_score(quad, small.shape, min_area_ratio), "edges", quad))

    mask = paper_mask(small)
    for cnt in biggest_contours(mask, n=3, mode=cv2.RETR_EXTERNAL):
        quad = quad_from_contour(cnt)
        if quad is not None:
            candidates.append((quad_score(quad, small.shape, min_area_ratio), "color", quad))

    candidates = [c for c in candidates if c[0] > 0]
    if not candidates:
        quad = quad_from_hough(cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150))
        if quad is not None:
            score = quad_score(quad, small.shape, min_area_ratio)
            if score > 0:
                candidates.append((score, "hough", quad))

    debug = {}
    if keep_debug:
        debug = {"gray": gray, "edges": edges, "paper_mask": mask}
        overlay = small.copy()
        all_cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, all_cnts, -1, (255, 0, 255), 1)
        for _, _, q in candidates:
            cv2.polylines(overlay, [q.astype(np.int32)], True, (0, 200, 255), 2)
        for x1, y1, x2, y2 in hough_lines(edges):
            cv2.line(overlay, (int(x1), int(y1)), (int(x2), int(y2)), (255, 128, 0), 1)
        debug["candidates"] = overlay

    if not candidates:
        return None
    score, method, quad = max(candidates, key=lambda c: c[0])
    corners = order_points(quad / scale)
    if refine:
        full_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if scale != 1 else gray
        corners = order_points(refine_corners(full_gray, corners))
    return Detection(corners=corners, method=method, area_ratio=score, debug=debug)


# --------------------------------------------------------------------------- page-level
def estimate_skew(gray: np.ndarray, max_angle: float = 15.0) -> float:
    """Estimate text-line skew (degrees) with Hough lines on dilated text."""
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    # smear characters horizontally so each text line becomes one long blob
    smeared = cv2.dilate(binary, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3)))
    edges = cv2.Canny(smeared, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=100,
                            minLineLength=gray.shape[1] // 4, maxLineGap=10)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(a) <= max_angle:
            angles.append(a)
    return float(np.median(angles)) if angles else 0.0


def deskew(img: np.ndarray) -> tuple[np.ndarray, float]:
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    angle = estimate_skew(gray)
    if abs(angle) < 0.3:
        return img, 0.0
    # image y axis points down, so a positive line angle is a clockwise tilt
    return rotate(img, angle, expand=False), angle


def find_punch_holes(img: np.ndarray, margin: float = 0.09) -> list[tuple[int, int, int]]:
    """Hough circle transform: find binder holes near the page edges.

    Hough votes are cheap to fool (letters like 'o' are circles too), so every
    candidate must also be near an edge, dark inside and surrounded by bright paper.
    """
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = filters.remove_shadows(gray)        # so holes inside a shadow still stand out
    blurred = cv2.medianBlur(gray, 5)
    h, w = gray.shape
    r_min, r_max = max(4, int(0.008 * w)), int(0.035 * w)
    circles = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=4 * r_min,
                               param1=120, param2=18, minRadius=r_min, maxRadius=r_max)
    if circles is None:
        return []
    paper = float(np.median(gray))
    holes = []
    for x, y, r in np.round(circles.reshape(-1, 3)).astype(int):
        near_edge = x < margin * w or x > (1 - margin) * w or y < margin * h or y > (1 - margin) * h
        if not near_edge:
            continue
        disk = np.zeros_like(gray)
        cv2.circle(disk, (x, y), max(2, int(r * 0.6)), 255, -1)
        ring = np.zeros_like(gray)
        cv2.circle(ring, (x, y), int(r * 1.8), 255, -1)
        cv2.circle(ring, (x, y), int(r * 1.3), 0, -1)
        inside, around = cv2.mean(gray, disk)[0], cv2.mean(gray, ring)[0]
        if inside < paper - 60 and around > paper - 30:
            holes.append((int(x), int(y), int(r)))
    return holes
