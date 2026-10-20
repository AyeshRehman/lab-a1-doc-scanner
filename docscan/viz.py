"""Small drawing helpers for overlays and side-by-side figures."""

from __future__ import annotations

import cv2
import numpy as np

CORNER_NAMES = ("TL", "TR", "BR", "BL")


def to_bgr(img: np.ndarray) -> np.ndarray:
    if img.dtype != np.uint8:
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img


def draw_quad(img: np.ndarray, corners, color=(0, 255, 0), thickness: int | None = None) -> np.ndarray:
    out = to_bgr(img).copy()
    t = thickness or max(2, out.shape[1] // 300)
    pts = np.asarray(corners).reshape(-1, 2)
    cv2.polylines(out, [pts.astype(np.int32)], True, color, t, cv2.LINE_AA)
    for name, (x, y) in zip(CORNER_NAMES, pts):
        cv2.circle(out, (int(x), int(y)), t * 4, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.putText(out, name, (int(x) + 8, int(y) - 8), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5 * t, (0, 0, 255), max(1, t // 2), cv2.LINE_AA)
    return out


def label(img: np.ndarray, text: str) -> np.ndarray:
    out = to_bgr(img).copy()
    scale = max(0.5, out.shape[1] / 700)
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    cv2.rectangle(out, (0, 0), (tw + 12, th + base + 12), (0, 0, 0), -1)
    cv2.putText(out, text, (6, th + 6), cv2.FONT_HERSHEY_SIMPLEX, scale,
                (255, 255, 255), 1, cv2.LINE_AA)
    return out


def fit(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Letterbox `img` into a w x h cell."""
    img = to_bgr(img)
    s = min(w / img.shape[1], h / img.shape[0])
    resized = cv2.resize(img, (max(1, int(img.shape[1] * s)), max(1, int(img.shape[0] * s))),
                         interpolation=cv2.INTER_AREA)
    cell = np.full((h, w, 3), 40, np.uint8)
    y, x = (h - resized.shape[0]) // 2, (w - resized.shape[1]) // 2
    cell[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
    return cell


def montage(items, cols: int = 3, cell: tuple[int, int] = (420, 320)) -> np.ndarray:
    """Grid of (title, image) pairs."""
    items = list(items.items()) if isinstance(items, dict) else list(items)
    cw, ch = cell
    tiles = [label(fit(img, cw, ch), title) for title, img in items]
    while len(tiles) % cols:
        tiles.append(np.full((ch, cw, 3), 40, np.uint8))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    return np.vstack(rows)
