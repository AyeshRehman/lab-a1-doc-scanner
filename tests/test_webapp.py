"""API tests for the web app, using Flask's test client and a throw-away library.

Run with:  python -m pytest -q      (or:  python tests/test_webapp.py)
"""

import io
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import webapp.server as server  # noqa: E402
from docscan import synthetic  # noqa: E402
from webapp.storage import Library  # noqa: E402

_tmp = tempfile.TemporaryDirectory()
server.lib = Library(Path(_tmp.name))
client = server.app.test_client()

PHOTO, _ = synthetic.make_photo()
PHOTO_JPG = cv2.imencode(".jpg", PHOTO)[1].tobytes()


def upload(n=1, **form):
    data = {"files": [(io.BytesIO(PHOTO_JPG), f"page{i}.jpg") for i in range(n)], **form}
    r = client.post("/api/docs", data=data)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["docs"]


def test_index_and_status():
    assert client.get("/").status_code == 200
    s = client.get("/api/status").get_json()
    assert s["opencv"] == cv2.__version__ and "color" in s["modes"]


def test_upload_detects_and_scans():
    doc = upload(options=json.dumps({"mode": "bw"}))[0]
    assert doc["detection"]["method"] in ("edges", "color", "hough")
    assert doc["options"]["mode"] == "bw" and doc["scan"]["height"] > doc["scan"]["width"]
    for url in doc["urls"].values():
        assert client.get(url).status_code == 200


def test_process_options_corners_and_rotation():
    doc = upload()[0]
    r = client.post(f"/api/docs/{doc['id']}/process", json={"options": {"mode": "gray", "rotate": 90}})
    after = r.get_json()
    assert after["version"] == doc["version"] + 1
    assert after["scan"]["width"] == doc["scan"]["height"]          # rotated 90 degrees
    full = client.post(f"/api/docs/{doc['id']}/process", json={"corners": None}).get_json()
    assert full["corners"] is None
    again = client.post(f"/api/docs/{doc['id']}/detect").get_json()
    assert again["found"] and again["corners"] is not None


def test_rename_download_export_delete():
    a, b = upload(2)
    assert client.patch(f"/api/docs/{a['id']}", json={"name": "Homework"}).get_json()["name"] == "Homework"
    for fmt, magic in (("png", b"\x89PNG"), ("jpg", b"\xff\xd8"), ("pdf", b"%PDF")):
        r = client.get(f"/api/docs/{a['id']}/download?format={fmt}")
        assert r.status_code == 200 and r.data.startswith(magic), fmt
    pdf = client.post("/api/export", json={"ids": [a["id"], b["id"]], "format": "pdf"}).data
    assert pdf.count(b"/Type /Page ") == 2
    assert client.post("/api/export", json={"ids": [a["id"]], "format": "zip"}).data[:2] == b"PK"
    assert client.delete(f"/api/docs/{a['id']}").status_code == 200
    assert client.get(f"/api/docs/{a['id']}").status_code == 404


def test_bad_input_is_rejected():
    assert client.get("/api/docs/..%2F..%2Fetc").status_code == 404
    r = client.post("/api/docs", data={"files": [(io.BytesIO(b"not an image"), "x.jpg")]})
    assert r.status_code == 400 and "image" in r.get_json()["error"]


def test_live_detect_and_steps():
    r = client.post("/api/detect?debug=1", data=PHOTO_JPG, content_type="image/jpeg").get_json()
    assert r["found"] and len(r["corners"]) == 4 and set(r["debug"]) == {"edges", "paper_mask"}
    doc = upload()[0]
    steps = client.get(f"/api/docs/{doc['id']}/steps").get_json()["steps"]
    assert [s["key"] for s in steps][0] == "input" and steps[-1]["key"] == "final"


def test_camera_capture_with_corners():
    h, w = PHOTO.shape[:2]
    corners = (synthetic.project_page(synthetic.make_page().shape) / [w, h]).tolist()
    doc = upload(source="camera", corners=json.dumps(corners))[0]
    assert doc["detection"]["method"] == "live"
    assert np.abs(np.array(doc["corners"]) - corners).max() < 0.01


def test_align():
    page = cv2.imencode(".png", synthetic.make_page())[1].tobytes()
    r = client.post("/api/align", data={"template": (io.BytesIO(page), "t.png"),
                                        "image": (io.BytesIO(PHOTO_JPG), "p.jpg"), "method": "orb"}).get_json()
    assert r["ok"] and r["inliers"] > 30 and r["aligned"].startswith("data:image/jpeg")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} tests passed")
