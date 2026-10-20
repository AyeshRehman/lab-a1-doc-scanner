"""Image fundamentals: how an image lives in memory, and colour spaces.

Key facts
---------
* An OpenCV image is just a NumPy array.
    - colour image : shape (H, W, 3), dtype uint8  -> 3 channels in **B, G, R** order
    - grayscale    : shape (H, W),    dtype uint8
* "Bit depth" = bits per channel. uint8 -> 8 bits -> values 0..255.
  uint16 -> 0..65535, float32 images are usually scaled to 0..1.
* Pixel (x, y) is accessed as img[y, x]  (row first, then column!).
* OpenCV uses BGR, Matplotlib / PIL / the web use RGB. Mixing them up swaps red and blue.
"""

from __future__ import annotations

import cv2
import numpy as np


def describe(img: np.ndarray) -> dict:
    """Return the basic facts about how an image is stored."""
    channels = 1 if img.ndim == 2 else img.shape[2]
    info = {
        "shape": img.shape,
        "height": img.shape[0],
        "width": img.shape[1],
        "channels": channels,
        "dtype": str(img.dtype),
        "bit_depth": img.dtype.itemsize * 8,
        "size_bytes": img.nbytes,
        "min": int(img.min()),
        "max": int(img.max()),
    }
    if channels == 1:
        info["mean"] = round(float(img.mean()), 2)
    else:
        # mean of every channel; axis=(0, 1) collapses rows and columns, keeps channels
        info["mean_per_channel_BGR"] = [round(float(m), 2) for m in img.mean(axis=(0, 1))]
    return info


def bgr_to_rgb(img: np.ndarray) -> np.ndarray:
    """Reverse the channel axis. Same result as cv2.cvtColor(img, cv2.COLOR_BGR2RGB)."""
    return img[..., ::-1].copy()


def split_channels(img: np.ndarray) -> list[np.ndarray]:
    """Split a BGR image into its three single-channel planes (B, G, R)."""
    return [img[..., i] for i in range(img.shape[2])]


def reduce_bit_depth(img: np.ndarray, bits: int) -> np.ndarray:
    """Quantise an 8-bit image to `bits` bits per channel (keeps uint8 for display).

    With 2 bits each channel can only take 4 values, which makes banding obvious.
    """
    levels = 2 ** bits
    step = 256 // levels
    # Integer division drops the low bits; multiplying back puts values in 0..255 range.
    return ((img // step) * step + step // 2).astype(np.uint8)


def adjust_region(img: np.ndarray, x: int, y: int, w: int, h: int, delta: int) -> np.ndarray:
    """Brighten/darken a rectangle using slicing + broadcasting.

    `delta` (a scalar) is broadcast over every pixel and channel of the ROI. We go
    through int16 so the addition cannot wrap around (uint8: 250 + 10 = 4!).
    """
    out = img.copy()
    roi = out[y:y + h, x:x + w].astype(np.int16)
    out[y:y + h, x:x + w] = np.clip(roi + delta, 0, 255).astype(np.uint8)
    return out


CONVERSIONS = {
    "gray": cv2.COLOR_BGR2GRAY,
    "rgb": cv2.COLOR_BGR2RGB,
    "hsv": cv2.COLOR_BGR2HSV,
    "lab": cv2.COLOR_BGR2LAB,
}


def convert(img: np.ndarray, space: str) -> np.ndarray:
    """Convert a BGR image into 'gray', 'rgb', 'hsv' or 'lab'.

    In 8-bit OpenCV images: H is 0..179 (degrees / 2), S and V are 0..255;
    L, a, b are all 0..255 with a = b = 128 meaning "no colour".
    """
    return cv2.cvtColor(img, CONVERSIONS[space])


def paper_mask_hsv(img: np.ndarray, s_max: int = 70, v_min: int | None = None) -> np.ndarray:
    """Colour-based segmentation of white paper.

    Paper is *bright* (high V) and *unsaturated* (low S) whatever its hue, which is
    much easier to express in HSV than in BGR. If v_min is None it is chosen
    automatically with Otsu's method on the V channel.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    if v_min is None:
        v_min, _ = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        v_min = int(v_min)
    lower = np.array([0, 0, v_min], dtype=np.uint8)
    upper = np.array([179, s_max, 255], dtype=np.uint8)
    return cv2.inRange(hsv, lower, upper)


def paper_mask_lab(img: np.ndarray, chroma_max: int = 20) -> np.ndarray:
    """Same idea in LAB: bright L and a/b close to the neutral value 128."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L, a, b = cv2.split(lab)
    _, bright = cv2.threshold(L, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    chroma = np.hypot(a.astype(np.float32) - 128, b.astype(np.float32) - 128)
    neutral = (chroma < chroma_max).astype(np.uint8) * 255
    return cv2.bitwise_and(bright, neutral)
