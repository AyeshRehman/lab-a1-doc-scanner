"""The full still-image pipeline: detect -> warp -> clean up."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .detect import Detection, deskew, find_document
from .enhance import enhance, remove_punch_holes
from .geometry import estimate_aspect, four_point_warp
from .viz import draw_quad


@dataclass
class ScanResult:
    scan: np.ndarray                     # final cleaned image
    warped: np.ndarray                   # perspective-corrected colour image
    detection: Detection | None          # None -> whole image was used
    steps: dict = field(default_factory=dict, repr=False)
    notes: list = field(default_factory=list)


def scan_document(img: np.ndarray, mode: str = "color", corners=None,
                  min_area_ratio: float = 0.15, aspect: float | str | None = "auto",
                  K: np.ndarray | None = None, trim: float = 0.006,
                  do_deskew: bool = False, holes: bool = False,
                  keep_steps: bool = False) -> ScanResult:
    """Scan a BGR photo.

    corners - skip detection and use these 4 points (manual selection)
    aspect  - "auto" (estimate the real page ratio), a number (height/width,
              1.414 = A4) or None (use measured edge lengths)
    K       - camera matrix from calibration, makes "auto" aspect more accurate
    trim    - fraction of the border to cut away (removes slivers of background)
    """
    notes, steps = [], {}
    detection = None

    if corners is not None:
        detection = Detection(np.asarray(corners, np.float32), "manual", 0.0)
    else:
        detection = find_document(img, min_area_ratio, keep_debug=keep_steps)

    if detection is None:
        notes.append("no document found - using the whole image")
        warped = img.copy()
    else:
        if aspect == "auto":
            aspect = estimate_aspect(detection.corners, (img.shape[1], img.shape[0]), K)
        warped, _ = four_point_warp(img, detection.corners, aspect)
        if trim:
            dy, dx = int(warped.shape[0] * trim), int(warped.shape[1] * trim)
            warped = warped[dy:warped.shape[0] - dy, dx:warped.shape[1] - dx]
        notes.append(f"document found by '{detection.method}' "
                     f"({detection.area_ratio:.0%} of the frame)"
                     + (f", page ratio {aspect:.3f}" if aspect else ""))

    if do_deskew:
        warped, angle = deskew(warped)
        if angle:
            notes.append(f"deskewed by {angle:.2f} deg")

    if holes:
        warped, found = remove_punch_holes(warped)
        if found:
            notes.append(f"removed {len(found)} punch hole(s)")

    scan = enhance(warped, mode)

    if keep_steps:
        steps["1_input"] = img
        if detection is not None:
            steps.update({f"2_{k}": v for k, v in detection.debug.items()})
            steps["3_detected"] = draw_quad(img, detection.corners)
        steps["4_warped"] = warped
        steps[f"5_scan_{mode}"] = scan

    return ScanResult(scan=scan, warped=warped, detection=detection, steps=steps, notes=notes)
