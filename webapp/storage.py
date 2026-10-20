"""The scan library: one folder per document under outputs/library/<id>/.

    original.jpg       the photo as received (after optional undistortion)
    original_view.jpg  smaller copy for the corner editor
    scan.png           full-resolution result (lossless)
    preview.jpg        result for on-screen display
    thumb.jpg          small card image
    meta.json          name, corners, options, detection info ...
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

ID_RE = re.compile(r"^[a-f0-9]{12}$")
FILES = {"original.jpg", "original_view.jpg", "scan.png", "preview.jpg", "thumb.jpg"}
DEFAULT_OPTIONS = {"mode": "color", "aspect": "auto", "deskew": False, "holes": False, "rotate": 0}


def _fit_width(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    if s >= 1:
        return img
    return cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ paths
    def _dir(self, doc_id: str) -> Path:
        if not ID_RE.match(doc_id or ""):
            raise KeyError(doc_id)
        d = self.root / doc_id
        if not d.is_dir():
            raise KeyError(doc_id)
        return d

    def file(self, doc_id: str, name: str) -> Path:
        if name not in FILES:
            raise KeyError(name)
        p = self._dir(doc_id) / name
        if not p.exists():
            raise KeyError(name)
        return p

    # ------------------------------------------------------------------ meta
    def meta(self, doc_id: str) -> dict:
        return json.loads((self._dir(doc_id) / "meta.json").read_text(encoding="utf-8"))

    def save_meta(self, doc_id: str, meta: dict) -> dict:
        meta["updated"] = time.time()
        path = self._dir(doc_id) / "meta.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        tmp.replace(path)
        return meta

    def list(self) -> list[dict]:
        docs = []
        for d in self.root.iterdir():
            try:
                docs.append(json.loads((d / "meta.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(docs, key=lambda m: m.get("created", 0), reverse=True)

    # ------------------------------------------------------------------ create / update
    def create(self, img: np.ndarray, name: str, source: str) -> dict:
        doc_id = uuid.uuid4().hex[:12]
        d = self.root / doc_id
        d.mkdir()
        cv2.imwrite(str(d / "original.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        cv2.imwrite(str(d / "original_view.jpg"), _fit_width(img, 1800), [cv2.IMWRITE_JPEG_QUALITY, 88])
        now = time.time()
        meta = {
            "id": doc_id, "name": name, "source": source, "created": now, "updated": now,
            "width": img.shape[1], "height": img.shape[0],
            "corners": None, "detection": None, "options": dict(DEFAULT_OPTIONS),
            "scan": None, "notes": [], "version": 0,
        }
        (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    def read_original(self, doc_id: str) -> np.ndarray:
        return cv2.imread(str(self.file(doc_id, "original.jpg")))

    def read_scan(self, doc_id: str) -> np.ndarray:
        return cv2.imread(str(self.file(doc_id, "scan.png")), cv2.IMREAD_UNCHANGED)

    def save_scan(self, doc_id: str, scan: np.ndarray):
        d = self._dir(doc_id)
        cv2.imwrite(str(d / "scan.png"), scan)
        cv2.imwrite(str(d / "preview.jpg"), _fit_width(scan, 1800), [cv2.IMWRITE_JPEG_QUALITY, 90])
        cv2.imwrite(str(d / "thumb.jpg"), _fit_width(scan, 480), [cv2.IMWRITE_JPEG_QUALITY, 82])

    def delete(self, doc_id: str):
        shutil.rmtree(self._dir(doc_id))

    def clear(self):
        with self._lock:
            for d in self.root.iterdir():
                if d.is_dir() and ID_RE.match(d.name):
                    shutil.rmtree(d)

    def stats(self) -> dict:
        count, size = 0, 0
        for d in self.root.iterdir():
            if d.is_dir() and ID_RE.match(d.name):
                count += 1
                size += sum(f.stat().st_size for f in d.iterdir() if f.is_file())
        return {"count": count, "bytes": size}
