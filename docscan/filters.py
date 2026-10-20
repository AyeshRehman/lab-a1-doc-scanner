"""Filtering: blur, sharpening, morphology and thresholding.

* Blur = low-pass filter, removes noise and fine detail before edge detection.
    - Gaussian  : weighted average, smooth everything.
    - Median    : great for salt-and-pepper noise, keeps edges.
    - Bilateral : smooths flat areas but preserves strong edges (slow).
* Sharpen = boost high frequencies (kernel or "unsharp mask").
* Morphology works on binary images with a structuring element (kernel):
    - erode  : shrinks white regions, removes small white specks
    - dilate : grows white regions, fills small gaps
    - open   : erode then dilate  -> remove small noise
    - close  : dilate then erode  -> close small holes / join broken edges
* Threshold turns gray -> binary: global, Otsu (automatic) or adaptive (local).
"""

from __future__ import annotations

import cv2
import numpy as np


def odd(n: float, minimum: int = 3) -> int:
    """Kernel sizes must be odd integers."""
    n = max(minimum, int(n))
    return n if n % 2 == 1 else n + 1


def gaussian_blur(img, ksize: int = 5):
    return cv2.GaussianBlur(img, (ksize, ksize), 0)


def median_blur(img, ksize: int = 5):
    return cv2.medianBlur(img, ksize)


def bilateral(img, d: int = 9, sigma_color: float = 75, sigma_space: float = 75):
    return cv2.bilateralFilter(img, d, sigma_color, sigma_space)


SHARPEN_KERNEL = np.array([[0, -1, 0],
                           [-1, 5, -1],
                           [0, -1, 0]], dtype=np.float32)


def sharpen_kernel(img):
    """Convolve with a Laplacian-style kernel (centre minus neighbours)."""
    return cv2.filter2D(img, -1, SHARPEN_KERNEL)


def unsharp_mask(img, sigma: float = 2.0, amount: float = 0.6):
    """out = img + amount * (img - blurred). Gentler and tunable."""
    blurred = cv2.GaussianBlur(img, (0, 0), sigma)
    return cv2.addWeighted(img, 1 + amount, blurred, -amount, 0)


def kernel(size: int = 5, shape: str = "rect"):
    shapes = {"rect": cv2.MORPH_RECT, "ellipse": cv2.MORPH_ELLIPSE, "cross": cv2.MORPH_CROSS}
    return cv2.getStructuringElement(shapes[shape], (size, size))


MORPH_OPS = {
    "erode": cv2.MORPH_ERODE,
    "dilate": cv2.MORPH_DILATE,
    "open": cv2.MORPH_OPEN,
    "close": cv2.MORPH_CLOSE,
    "gradient": cv2.MORPH_GRADIENT,
}


def morph(binary, op: str, size: int = 5, iterations: int = 1, shape: str = "rect"):
    return cv2.morphologyEx(binary, MORPH_OPS[op], kernel(size, shape), iterations=iterations)


def threshold_global(gray, value: int = 127):
    return cv2.threshold(gray, value, 255, cv2.THRESH_BINARY)[1]


def threshold_otsu(gray):
    """Otsu picks the threshold that best separates a two-peak histogram."""
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def threshold_adaptive(gray, block: int = 31, c: int = 10):
    """Each pixel is compared with a Gaussian-weighted mean of its neighbourhood,
    so uneven lighting (shadows) does not ruin the result."""
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, odd(block), c)


def remove_shadows(img):
    """Flatten uneven illumination on a page.

    1. shrink the page (cheap, and lighting varies slowly anyway)
    2. dilate with a big kernel -> wipes out dark text *and* solid blocks such as
       headers, leaving only the light falling on the paper
    3. median blur -> smooth background estimate, scaled back to full size
    4. divide the image by the background -> paper becomes uniform white
    Works per channel so colour images keep their colours.
    """
    if img.ndim == 3:
        return cv2.merge([remove_shadows(c) for c in cv2.split(img)])
    h, w = img.shape[:2]
    small_w = 256
    small = cv2.resize(img, (small_w, max(1, round(h * small_w / w))), interpolation=cv2.INTER_AREA)
    background = cv2.dilate(small, kernel(odd(small_w / 10), "ellipse"))
    background = cv2.medianBlur(background, odd(small_w / 12))
    background = cv2.resize(background, (w, h), interpolation=cv2.INTER_LINEAR)
    # cv2.divide(a, b, scale=255) computes a / b * 255 with saturation
    return cv2.divide(img, background, scale=255)


def clahe(gray, clip: float = 2.0, tiles: int = 8):
    """Contrast Limited Adaptive Histogram Equalisation (local contrast boost)."""
    return cv2.createCLAHE(clipLimit=clip, tileGridSize=(tiles, tiles)).apply(gray)
