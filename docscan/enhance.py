"""Turn a perspective-corrected sheet into a clean scan."""

from __future__ import annotations

import cv2
import numpy as np

from . import filters
from .detect import find_punch_holes

MODES = ("color", "gray", "bw", "original")


def enhance(img: np.ndarray, mode: str = "color") -> np.ndarray:
    """
    color    - shadows removed per channel, local contrast boost in LAB, mild sharpen
    gray     - grayscale, shadows removed, sharpened
    bw       - pure black & white "photocopy" via adaptive threshold + cleanup
    original - untouched warp
    """
    if mode == "original":
        return img.copy()

    if mode == "color":
        flat = filters.remove_shadows(img)
        # boost contrast on lightness only, so colours are not distorted
        L, a, b = cv2.split(cv2.cvtColor(flat, cv2.COLOR_BGR2LAB))
        L = filters.clahe(L, clip=1.5)
        out = cv2.cvtColor(cv2.merge([L, a, b]), cv2.COLOR_LAB2BGR)
        return filters.unsharp_mask(out, sigma=1.5, amount=0.5)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    flat = filters.remove_shadows(gray)

    if mode == "gray":
        return filters.unsharp_mask(flat, sigma=1.5, amount=0.7)

    if mode == "bw":
        block = filters.odd(gray.shape[1] / 30, 15)
        bw = filters.threshold_adaptive(flat, block=block, c=15)
        bw = cv2.medianBlur(bw, 3)             # kill isolated salt-and-pepper pixels
        # open on the inverted image removes tiny black dots without thinning text much
        inv = filters.morph(255 - bw, "open", 2)
        return 255 - inv

    raise ValueError(f"unknown mode {mode!r}, choose from {MODES}")


def remove_punch_holes(img: np.ndarray) -> tuple[np.ndarray, list]:
    """Detect binder holes with Hough circles and paint them out with inpainting."""
    holes = find_punch_holes(img)
    if not holes:
        return img, holes
    mask = np.zeros(img.shape[:2], np.uint8)
    for x, y, r in holes:
        cv2.circle(mask, (x, y), int(r * 1.3), 255, -1)
    return cv2.inpaint(img, mask, 5, cv2.INPAINT_TELEA), holes
