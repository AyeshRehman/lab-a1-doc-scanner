"""Flask API for the scanner. Every route lives under /api; the frontend is static files."""

from __future__ import annotations

import base64
import io
import json
import threading
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, abort, jsonify, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import module_tour
from docscan import scan_document, synthetic
from docscan import camera as cam
from docscan.detect import edge_map, find_document, paper_mask, refine_corners
from docscan.enhance import MODES, enhance
from docscan.features import align_to_template
from docscan.filters import remove_shadows
from docscan.geometry import estimate_aspect, four_point_warp
from docscan.viz import draw_quad, montage

from . import __version__
from .pdf import images_to_pdf
from .storage import DEFAULT_OPTIONS, Library
from .streams import StreamManager

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).parent / "static"
OUTPUTS = ROOT / "outputs"
SAMPLES = ROOT / "samples"
CALIB_PATH = OUTPUTS / "calib.npz"
CALIB_INFO = OUTPUTS / "calib.json"
SETTINGS_PATH = OUTPUTS / "app_settings.json"

ASPECTS = {"auto": "auto", "a4": 297 / 210, "letter": 11 / 8.5, "legal": 14 / 8.5, "free": None}
ROTATIONS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
MAX_SIDE = 4000

app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024
lib = Library(OUTPUTS / "library")
streams = StreamManager()
_samples_lock = threading.Lock()


# =========================================================================== helpers
@app.errorhandler(HTTPException)
def http_error(e):
    return jsonify(error=e.description), e.code


@app.errorhandler(KeyError)
def not_found(e):
    return jsonify(error="Not found"), 404


def decode_image(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        abort(400, "That file is not an image OpenCV can read.")
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    return img


def request_image(field: str = "file") -> np.ndarray:
    f = request.files.get(field)
    return decode_image(f.read() if f else request.get_data())


def data_url(img: np.ndarray, max_side: int = 900, quality: int = 82) -> str:
    h, w = img.shape[:2]
    if max(h, w) > max_side:
        s = max_side / max(h, w)
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])[1]
    return "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()


def norm(corners, w, h):
    return None if corners is None else (np.asarray(corners, np.float64) / [w, h]).round(5).tolist()


def denorm(corners, w, h) -> np.ndarray:
    pts = np.asarray(corners, np.float32).reshape(4, 2) * np.float32([w, h])
    return pts


def load_settings() -> dict:
    try:
        return {"use_calibration": False, **json.loads(SETTINGS_PATH.read_text())}
    except (OSError, ValueError):
        return {"use_calibration": False}


def save_settings(s: dict):
    OUTPUTS.mkdir(exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(s, indent=2))


def calibration_info():
    if not CALIB_PATH.exists():
        return None
    try:
        info = json.loads(CALIB_INFO.read_text())
    except (OSError, ValueError):
        c = cam.load_calibration(CALIB_PATH)
        info = {"rms": c["rms"], "size": c["size"]}
    return info


def active_undistorter():
    if load_settings()["use_calibration"] and CALIB_PATH.exists():
        return cam.Undistorter.from_file(CALIB_PATH)
    return None


def public(meta: dict) -> dict:
    v = meta.get("version", 0)
    base = f"/api/docs/{meta['id']}"
    return {
        **meta,
        "urls": {
            "original": f"{base}/file/original_view.jpg?v=0",
            "preview": f"{base}/file/preview.jpg?v={v}" if meta.get("scan") else None,
            "thumb": f"{base}/file/thumb.jpg?v={v}" if meta.get("scan") else None,
        },
    }


def clean_options(raw: dict | None, base: dict) -> dict:
    opts = {**DEFAULT_OPTIONS, **base}
    for key, value in (raw or {}).items():
        if key == "mode" and value in MODES:
            opts["mode"] = value
        elif key == "aspect" and value in ASPECTS:
            opts["aspect"] = value
        elif key in ("deskew", "holes"):
            opts[key] = bool(value)
        elif key == "rotate" and int(value) % 360 in (0, 90, 180, 270):
            opts["rotate"] = int(value) % 360
    return opts


# =========================================================================== processing
def process(doc_id: str, options: dict | None = None, corners="keep") -> dict:
    """(Re)render a document's scan. corners: 'keep', None (= whole photo) or 4 normalised points."""
    meta = lib.meta(doc_id)
    meta["options"] = clean_options(options, meta.get("options", {}))
    if corners != "keep":
        meta["corners"] = corners
    opts = meta["options"]
    img = lib.read_original(doc_id)
    h, w = img.shape[:2]

    full = meta["corners"] is None
    pts = (np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]]) if full
           else denorm(meta["corners"], w, h))
    aspect = ASPECTS[opts["aspect"]]
    if aspect == "auto":
        aspect = None if full else estimate_aspect(pts, (w, h))
    result = scan_document(img, opts["mode"], corners=pts, aspect=aspect,
                           do_deskew=opts["deskew"], holes=opts["holes"], trim=0 if full else 0.006)
    scan = result.scan
    if opts["rotate"]:
        scan = cv2.rotate(scan, ROTATIONS[opts["rotate"]])
    lib.save_scan(doc_id, scan)
    meta["scan"] = {"width": scan.shape[1], "height": scan.shape[0]}
    meta["notes"] = [n for n in result.notes if not n.startswith("document found")]
    meta["version"] = meta.get("version", 0) + 1
    return lib.save_meta(doc_id, meta)


def detect_corners(img: np.ndarray):
    det = find_document(img)
    if det is None:
        return None, None
    h, w = img.shape[:2]
    return norm(det.corners, w, h), {"method": det.method, "area": round(det.area_ratio, 4)}


def create_doc(img: np.ndarray, name: str, source: str, corners=None, detect=True, options=None) -> dict:
    if source in ("camera", "stream"):
        und = active_undistorter()
        if und is not None:
            img = und(img)
            corners = None          # geometry changed - detect again on the corrected image
    meta = lib.create(img, name, source)
    h, w = img.shape[:2]
    detection = None
    if corners is not None:
        refined = refine_corners(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), denorm(corners, w, h))
        corners, detection = norm(refined, w, h), {"method": "live", "area": None}
    elif detect:
        corners, detection = detect_corners(img)
    meta["corners"], meta["detection"] = corners, detection
    lib.save_meta(meta["id"], meta)
    return process(meta["id"], options)


def default_name(prefix: str = "Scan") -> str:
    return time.strftime(f"{prefix} %d %b %Y, %H:%M:%S")


def form_options() -> dict:
    raw = request.form.get("options")
    return json.loads(raw) if raw else {}


# =========================================================================== app + status
@app.get("/")
def index():
    return send_file(STATIC / "index.html")


@app.get("/api/status")
def status():
    return jsonify({
        "version": __version__,
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "modes": list(MODES),
        "aspects": list(ASPECTS),
        "library": lib.stats(),
        "calibration": calibration_info(),
        "settings": load_settings(),
    })


@app.patch("/api/settings")
def update_settings():
    s = load_settings()
    body = request.get_json(force=True) or {}
    if "use_calibration" in body:
        s["use_calibration"] = bool(body["use_calibration"])
    save_settings(s)
    return jsonify(s)


# =========================================================================== documents
@app.get("/api/docs")
def list_docs():
    return jsonify([public(m) for m in lib.list()])


@app.post("/api/docs")
def create_docs():
    """Upload one or more photos. Optional form fields: source, corners (JSON), detect, options (JSON)."""
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        abort(400, "No image received.")
    source = request.form.get("source", "upload")
    corners = json.loads(request.form["corners"]) if request.form.get("corners") else None
    detect = request.form.get("detect", "1") != "0"
    options = form_options()
    docs = []
    for f in files:
        img = decode_image(f.read())
        stem = Path(f.filename or "").stem
        name = stem if stem and stem not in ("blob", "frame") else default_name()
        docs.append(public(create_doc(img, name, source, corners if len(files) == 1 else None, detect, options)))
    return jsonify({"docs": docs})


@app.get("/api/docs/<doc_id>")
def get_doc(doc_id):
    return jsonify(public(lib.meta(doc_id)))


@app.patch("/api/docs/<doc_id>")
def rename_doc(doc_id):
    body = request.get_json(force=True) or {}
    meta = lib.meta(doc_id)
    name = str(body.get("name", "")).strip()[:120]
    if name:
        meta["name"] = name
    return jsonify(public(lib.save_meta(doc_id, meta)))


@app.delete("/api/docs/<doc_id>")
def delete_doc(doc_id):
    lib.delete(doc_id)
    return jsonify(ok=True)


@app.delete("/api/docs")
def delete_all():
    lib.clear()
    return jsonify(ok=True)


@app.post("/api/docs/<doc_id>/process")
def process_doc(doc_id):
    body = request.get_json(force=True) or {}
    corners = body["corners"] if "corners" in body else "keep"
    return jsonify(public(process(doc_id, body.get("options"), corners)))


@app.post("/api/docs/<doc_id>/detect")
def redetect(doc_id):
    img = lib.read_original(doc_id)
    corners, detection = detect_corners(img)
    meta = lib.meta(doc_id)
    meta["detection"] = detection
    lib.save_meta(doc_id, meta)
    if corners is None:
        return jsonify({**public(meta), "found": False})
    return jsonify({**public(process(doc_id, None, corners)), "found": True})


@app.get("/api/docs/<doc_id>/file/<name>")
def doc_file(doc_id, name):
    return send_file(lib.file(doc_id, name), max_age=31536000)  # URLs carry ?v=, so cache forever


def _safe_name(name: str, fallback: str) -> str:
    return secure_filename(name) or fallback


@app.get("/api/docs/<doc_id>/download")
def download_doc(doc_id):
    fmt = request.args.get("format", "png")
    meta = lib.meta(doc_id)
    scan = lib.read_scan(doc_id)
    name = _safe_name(meta["name"], doc_id)
    if fmt == "pdf":
        return send_file(io.BytesIO(images_to_pdf([scan])), mimetype="application/pdf",
                         as_attachment=True, download_name=f"{name}.pdf")
    if fmt in ("jpg", "png"):
        params = [cv2.IMWRITE_JPEG_QUALITY, 93] if fmt == "jpg" else []
        data = cv2.imencode(f".{fmt}", scan, params)[1].tobytes()
        return send_file(io.BytesIO(data), mimetype=f"image/{'jpeg' if fmt == 'jpg' else 'png'}",
                         as_attachment=True, download_name=f"{name}.{fmt}")
    abort(400, "Unknown format.")


@app.post("/api/export")
def export_many():
    body = request.get_json(force=True) or {}
    ids, fmt = body.get("ids") or [], body.get("format", "pdf")
    if not ids:
        abort(400, "Nothing selected.")
    stamp = time.strftime("%Y%m%d_%H%M")
    if fmt == "pdf":
        pdf = images_to_pdf([lib.read_scan(i) for i in ids])
        return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True,
                         download_name=f"scans_{stamp}.pdf")
    if fmt == "zip":
        buf, used = io.BytesIO(), set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i in ids:
                name = _safe_name(lib.meta(i)["name"], i)
                while name in used:
                    name += "_"
                used.add(name)
                z.writestr(f"{name}.png", cv2.imencode(".png", lib.read_scan(i))[1].tobytes())
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=f"scans_{stamp}.zip")
    abort(400, "Unknown format.")


STEP_TEXT = {
    "input": ("Your photo", "The image exactly as the camera captured it - a NumPy array of "
              "height x width x 3 numbers (Blue, Green, Red), each 0-255."),
    "gray": ("Grayscale, smaller", "Colour is dropped and the image shrunk to 500 px high. Detection is "
             "faster, and fine texture that would confuse it disappears."),
    "edges": ("Edges", "Gaussian blur removes noise, Canny marks strong brightness changes, and a "
              "morphological close joins small gaps so the page outline is one connected line."),
    "paper_mask": ("Paper colour", "A second opinion from colour: paper is bright and unsaturated, which "
                   "is easy to express in HSV and LAB colour spaces. Opening/closing cleans the mask."),
    "candidates": ("Candidate shapes", "Contours are simplified to polygons (approxPolyDP). Four-sided, "
                   "convex shapes with sensible angles become candidates; the largest wins."),
    "detected": ("Corners", "The corners are refined to sub-pixel accuracy by fitting a straight line "
                 "to the edge pixels along each side and intersecting them."),
    "warped": ("Perspective corrected", "A 3x3 homography maps the 4 corners onto a rectangle whose "
               "proportions are recovered from the perspective itself (pinhole camera model)."),
    "flat": ("Shadows removed", "The page background is estimated with a big dilation and median blur, "
             "and the image is divided by it - uneven lighting becomes flat white."),
    "final": ("Final scan", "The chosen look is applied: colour with a local contrast boost, sharpened "
              "gray, or black & white with an adaptive threshold."),
}


@app.get("/api/docs/<doc_id>/steps")
def doc_steps(doc_id):
    meta = lib.meta(doc_id)
    img = lib.read_original(doc_id)
    h, w = img.shape[:2]
    det = find_document(img, keep_debug=True)
    images = {"input": img}
    if det is not None:
        images.update({k: det.debug[k] for k in ("gray", "edges", "paper_mask", "candidates")})
    if meta["corners"] is not None:
        pts = denorm(meta["corners"], w, h)
        images["detected"] = draw_quad(img, pts)
        warped, _ = four_point_warp(img, pts, estimate_aspect(pts, (w, h)))
        images["warped"] = warped
        images["flat"] = remove_shadows(warped)
    images["final"] = lib.read_scan(doc_id)
    steps = [{"key": k, "title": STEP_TEXT[k][0], "text": STEP_TEXT[k][1], "image": data_url(v)}
             for k, v in images.items()]
    return jsonify({"found": det is not None, "steps": steps})


# =========================================================================== live detection
@app.post("/api/detect")
def detect_frame():
    """Fast detection for live preview frames (no sub-pixel refinement)."""
    img = request_image()
    h, w = img.shape[:2]
    debug = request.args.get("debug") == "1"
    det = find_document(img, keep_debug=debug, refine=False)
    out = {"found": det is not None, "corners": norm(det.corners, w, h) if det else None,
           "method": det.method if det else None}
    if debug and det is not None:
        out["debug"] = {k: data_url(det.debug[k], 360, 70) for k in ("edges", "paper_mask")}
    elif debug:
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        out["debug"] = {"edges": data_url(edge_map(g), 360, 70), "paper_mask": data_url(paper_mask(img), 360, 70)}
    return jsonify(out)


# =========================================================================== samples
def ensure_samples():
    with _samples_lock:
        if not (SAMPLES / "photos").exists() or not (SAMPLES / "synthetic_video.mp4").exists():
            import make_samples
            make_samples.main()


@app.get("/api/samples")
def list_samples():
    ensure_samples()
    photos = sorted(p.name for p in (SAMPLES / "photos").glob("*.jpg"))
    return jsonify({"photos": photos, "template": "synthetic_page.png", "video": "synthetic_video.mp4"})


@app.get("/api/samples/<kind>/<name>")
def sample_file(kind, name):
    folders = {"photos": SAMPLES / "photos", "templates": SAMPLES / "templates", "board": SAMPLES}
    if kind not in folders:
        abort(404)
    ensure_samples()
    path = folders[kind] / secure_filename(name)
    if not path.exists():
        abort(404)
    return send_file(path)


@app.post("/api/samples/import")
def import_sample():
    ensure_samples()
    name = secure_filename((request.get_json(force=True) or {}).get("name", "synthetic_photo.jpg"))
    path = SAMPLES / "photos" / name
    if not path.exists():
        abort(404, "Sample not found.")
    img = cv2.imread(str(path))
    return jsonify({"docs": [public(create_doc(img, f"Sample - {path.stem}", "sample",
                                               options=(request.get_json(force=True) or {}).get("options")))]})


# =========================================================================== streams
@app.post("/api/stream/start")
def stream_start():
    body = request.get_json(force=True) or {}
    source = str(body.get("source", "")).strip()
    if source == "sample":
        ensure_samples()
        source = str(SAMPLES / "synthetic_video.mp4")
    if not source:
        abort(400, "Enter a camera address or file.")
    try:
        s = streams.start(source, undistort=active_undistorter(),
                          stable_frames=int(body.get("stable_frames", 15)))
    except (RuntimeError, FileNotFoundError) as e:
        abort(400, f"Could not open that source: {e}")
    return jsonify({"ok": True, "info": s.info})


@app.post("/api/stream/upload")
def stream_upload():
    f = request.files.get("file")
    if not f:
        abort(400, "No video received.")
    folder = OUTPUTS / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (secure_filename(f.filename or "video.mp4") or "video.mp4")
    f.save(path)
    try:
        s = streams.start(str(path), undistort=active_undistorter())
    except RuntimeError as e:
        abort(400, f"Could not play that video: {e}")
    return jsonify({"ok": True, "info": s.info})


@app.get("/api/stream/frame")
def stream_frame():
    s = streams.session
    if s is None:
        abort(404, "No stream running.")
    jpeg, state, seq = s.wait_frame(int(request.args.get("after", 0)))
    if s.error and jpeg is None:
        abort(502, s.error)
    if jpeg is None:
        abort(504, "Waiting for the first frame.")
    state.update(seq=seq, error=s.error)
    resp = Response(jpeg, mimetype="image/jpeg")
    resp.headers["X-State"] = json.dumps(state)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/stream/capture")
def stream_capture():
    s = streams.session
    if s is None:
        abort(404, "No stream running.")
    frame, corners = s.snapshot()
    if frame is None:
        abort(409, "No frame yet.")
    if corners is None:
        abort(409, "No page in view.")
    h, w = frame.shape[:2]
    body = request.get_json(force=True) or {}
    meta = create_doc(frame, default_name(), "stream", norm(corners, w, h), options=body.get("options"))
    return jsonify({"docs": [public(meta)]})


@app.post("/api/stream/stop")
def stream_stop():
    streams.stop()
    return jsonify(ok=True)


# =========================================================================== calibration
class CalibrationSession:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.points, self.thumbs, self.size, self.last = [], [], None, None


calib = CalibrationSession()


def _pattern() -> tuple[int, int]:
    raw = request.args.get("pattern") or request.form.get("pattern") or "9x6"
    try:
        cols, rows = (int(v) for v in raw.lower().split("x"))
    except ValueError:
        abort(400, "Pattern must look like 9x6.")
    return cols, rows


@app.post("/api/calibration/detect")
def calib_detect():
    img = request_image()
    h, w = img.shape[:2]
    corners = cam.find_chessboard(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), _pattern())
    return jsonify({"found": corners is not None,
                    "corners": None if corners is None else norm(corners.reshape(-1, 2), w, h)})


def _calib_state():
    return {"count": len(calib.points), "thumbs": calib.thumbs,
            "size": calib.size, "calibration": calibration_info()}


@app.post("/api/calibration/views")
def calib_add():
    pattern = _pattern()
    files = request.files.getlist("files") or request.files.getlist("file")
    images = [decode_image(f.read()) for f in files] if files else [decode_image(request.get_data())]
    added, rejected = 0, 0
    with calib.lock:
        for img in images:
            size = (img.shape[1], img.shape[0])
            if calib.size and size != tuple(calib.size):
                rejected += 1
                continue
            corners = cam.find_chessboard(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), pattern)
            if corners is None:
                rejected += 1
                continue
            calib.size = list(size)
            calib.points.append(corners)
            calib.last = img
            view = img.copy()
            cv2.drawChessboardCorners(view, pattern, corners, True)
            calib.thumbs.append(data_url(view, 240, 70))
            added += 1
    return jsonify({**_calib_state(), "added": added, "rejected": rejected})


@app.delete("/api/calibration/views/<int:index>")
def calib_remove(index):
    with calib.lock:
        if 0 <= index < len(calib.points):
            calib.points.pop(index)
            calib.thumbs.pop(index)
        if not calib.points:
            calib.size = None
    return jsonify(_calib_state())


@app.delete("/api/calibration/views")
def calib_reset():
    with calib.lock:
        calib.reset()
    return jsonify(_calib_state())


@app.get("/api/calibration")
def calib_status():
    return jsonify(_calib_state())


@app.post("/api/calibration/run")
def calib_run():
    body = request.get_json(force=True) or {}
    try:
        cols, rows = (int(v) for v in str(body.get("pattern", "9x6")).lower().split("x"))
    except ValueError:
        abort(400, "Pattern must look like 9x6.")
    square = float(body.get("square", 1.0))
    with calib.lock:
        if len(calib.points) < 5:
            abort(400, "Capture at least 5 views first.")
        result = cam.calibrate(calib.points, (cols, rows), tuple(calib.size), square)
        last = calib.last
    OUTPUTS.mkdir(exist_ok=True)
    cam.save_calibration(CALIB_PATH, result)
    info = {"rms": result["rms"], "size": result["size"], "views": len(calib.points),
            "pattern": f"{cols}x{rows}", "date": time.time(),
            "K": result["K"].round(3).tolist(), "dist": result["dist"].ravel().round(5).tolist(),
            "per_view_error": [round(e, 4) for e in result["per_view_error"]]}
    CALIB_INFO.write_text(json.dumps(info, indent=2))
    und = cam.Undistorter(result["K"], result["dist"], result["size"])
    return jsonify({"calibration": info, "before": data_url(last, 1000), "after": data_url(und(last), 1000)})


@app.delete("/api/calibration")
def calib_delete():
    for p in (CALIB_PATH, CALIB_INFO):
        p.unlink(missing_ok=True)
    s = load_settings()
    s["use_calibration"] = False
    save_settings(s)
    return jsonify(ok=True)


# =========================================================================== template alignment
@app.post("/api/align")
def align():
    if "template" not in request.files or "image" not in request.files:
        abort(400, "Add both a template and a photo.")
    template = decode_image(request.files["template"].read())
    image = decode_image(request.files["image"].read())
    method = request.form.get("method", "orb")
    if method not in ("orb", "sift"):
        abort(400, "Method must be ORB or SIFT.")
    ratio = float(request.form.get("ratio", 0.75))
    t0 = time.perf_counter()
    a = align_to_template(image, template, method, ratio)
    out = {"ok": a.aligned is not None, "method": method,
           "keypoints": {"photo": a.n_keypoints[0], "template": a.n_keypoints[1]},
           "matches": a.n_matches, "inliers": a.n_inliers,
           "ms": round((time.perf_counter() - t0) * 1000),
           "matches_image": data_url(a.visual, 1600)}
    if a.aligned is not None:
        diff = cv2.absdiff(cv2.cvtColor(a.aligned, cv2.COLOR_BGR2GRAY), cv2.cvtColor(template, cv2.COLOR_BGR2GRAY))
        heat = cv2.applyColorMap(cv2.GaussianBlur(diff, (5, 5), 0), cv2.COLORMAP_INFERNO)
        out.update(aligned=data_url(a.aligned, 1600, 92), diff=data_url(heat, 1600))
    return jsonify(out)


# =========================================================================== learn: topic figures
TOPICS = [
    ("fundamentals", "Pixels & channels", "How an image is stored: arrays, BGR channels, bit depth, slicing."),
    ("color", "Colour spaces", "Grayscale, HSV and LAB, and segmenting paper and ink by colour."),
    ("geometry", "Geometric transforms", "Resize, crop, rotate, affine and perspective warps."),
    ("filtering", "Filtering", "Blur, sharpening, thresholding and morphology."),
    ("edges", "Edges & shapes", "Canny, contours, polygon fitting, Hough lines and circles."),
    ("features", "Features & matching", "ORB and SIFT keypoints, matches and homography."),
    ("camera", "Lens distortion", "Barrel and pincushion distortion, and undoing it."),
    ("modes", "Scan modes", "The four output looks side by side."),
]
_topic_cache: dict = {}


@app.get("/api/topics")
def topics():
    return jsonify([{"id": i, "title": t, "text": d} for i, t, d in TOPICS])


@app.get("/api/topics/<topic>.jpg")
def topic_figure(topic):
    doc_id = request.args.get("doc")
    if doc_id:
        meta = lib.meta(doc_id)
        key = (topic, doc_id, meta.get("version"))
    else:
        key = (topic, None, None)
    if key not in _topic_cache:
        if doc_id:
            img = lib.read_original(doc_id)
            if max(img.shape[:2]) > 1280:
                s = 1280 / max(img.shape[:2])
                img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            template = lib.read_scan(doc_id)
            if template.ndim == 2:
                template = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)
        else:
            img, _ = synthetic.make_photo()
            template = synthetic.make_page()
        det = find_document(img)
        h, w = img.shape[:2]
        corners = det.corners if det else np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
        warped, _ = four_point_warp(img, corners, estimate_aspect(corners, (w, h)) if det else None)
        builders = {
            "fundamentals": lambda: module_tour.fundamentals(img),
            "color": lambda: module_tour.color_spaces(img),
            "geometry": lambda: module_tour.geometric(img, corners),
            "filtering": lambda: module_tour.filtering(img),
            "edges": lambda: module_tour.edges_shapes(img, remove_shadows(warped)) if det else abort(
                422, "No page was found in this photo, so there is nothing to outline."),
            "features": lambda: module_tour.feature_matching(img, template),
            "camera": lambda: module_tour.camera_basics(img),
            "modes": lambda: montage({m: enhance(warped, m) for m in MODES}, cols=4, cell=(360, 460)),
        }
        if topic not in builders:
            abort(404)
        fig = builders[topic]()
        _topic_cache[key] = cv2.imencode(".jpg", fig, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()
    return Response(_topic_cache[key], mimetype="image/jpeg")
