"""A tiny dependency-free PDF writer: one JPEG-compressed image per page.

PDF supports JPEG data directly (the DCTDecode filter), so each page is just
an image object plus a one-line drawing command that stretches it over the page.
"""

from __future__ import annotations

import io

import cv2
import numpy as np

A4_WIDTH_PT = 595.28  # 1 pt = 1/72 inch


def images_to_pdf(images: list[np.ndarray], page_width: float = A4_WIDTH_PT, quality: int = 90) -> bytes:
    out = io.BytesIO()
    offsets: dict[int, int] = {}

    def write_obj(num: int, body: bytes):
        offsets[num] = out.tell()
        out.write(f"{num} 0 obj\n".encode() + body + b"\nendobj\n")

    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    page_ids = [3 + 3 * i for i in range(len(images))]
    write_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    write_obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {len(images)} >>".encode())

    for i, img in enumerate(images):
        page, image, content = page_ids[i], page_ids[i] + 1, page_ids[i] + 2
        if img.ndim == 3 and img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        gray = img.ndim == 2
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise ValueError("could not encode page")
        jpg = jpg.tobytes()
        h, w = img.shape[:2]
        pw, ph = page_width, page_width * h / w
        write_obj(page, (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw:.2f} {ph:.2f}] "
                         f"/Resources << /XObject << /Im{i} {image} 0 R >> >> /Contents {content} 0 R >>").encode())
        write_obj(image, (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} "
                          f"/ColorSpace /{'DeviceGray' if gray else 'DeviceRGB'} /BitsPerComponent 8 "
                          f"/Filter /DCTDecode /Length {len(jpg)} >>\nstream\n").encode() + jpg + b"\nendstream")
        draw = f"q {pw:.2f} 0 0 {ph:.2f} 0 0 cm /Im{i} Do Q".encode()
        write_obj(content, f"<< /Length {len(draw)} >>\nstream\n".encode() + draw + b"\nendstream")

    total = 3 + 3 * len(images)
    xref = out.tell()
    out.write(f"xref\n0 {total}\n0000000000 65535 f \n".encode())
    for num in range(1, total):
        out.write(f"{offsets[num]:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()
