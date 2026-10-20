# Lab A1 — Document Scanner (OpenCV + NumPy, no deep learning)

Detects a sheet of paper in a photo **or a live webcam / video / RTSP feed**, corrects its
perspective, and cleans it up into a flat "scan" (colour, grayscale or black & white).

```
photo / frame ─► detect paper (edges + colour + Hough) ─► sub-pixel corners ─► true page ratio
             ─► perspective warp ─► shadow removal ─► colour / gray / B&W ─► (deskew, punch-hole removal)
```

## Setup

```bash
pip install -r requirements.txt
python make_samples.py          # synthetic photos, video, chessboard + calibration views
```

## Web app (easiest way to use it)

```bash
python app.py                   # opens http://127.0.0.1:8000
```

| Page | What you can do |
|---|---|
| **Scan** | Drop, browse or paste (Ctrl+V) photos - several at once. Try the built-in sample. |
| **Editor** | Drag corners or whole edges (with a magnifier), auto-detect, use the whole photo, undo; choose Colour / Gray / B&W / Original, page size, straighten text, remove punch holes, rotate; download PNG / JPG / PDF. |
| **Live camera** | Webcam in the browser, an IP/RTSP camera or a video file. Steady-hold detection, auto-capture, debug view of edges and the paper mask. |
| **Library** | Search, sort, multi-select, export many scans as one PDF or a ZIP, delete. |
| **Align to template** | ORB / SIFT keypoint matching to line a photo up with a clean original; matches and difference views. |
| **Calibrate camera** | Chessboard capture (camera or uploads), solve, compare before/after, apply lens correction to camera scans. |
| **How it works** | Every pipeline step on your own scan, and one figure per Module A1 topic. |
| **Settings** | Light / dark / system theme, defaults for new scans, camera options, storage, keyboard shortcuts. |

Scans are stored in `outputs/library/`. Preferences live in the browser.

### Adding a page later

1. Create `webapp/static/js/views/<name>.js` exporting `default { mount(root, ctx) { ...; return cleanup } }`.
2. Add one line to `PAGES` in `webapp/static/js/app.js` (`nav: 'main' | 'tools' | 'footer'` decides where the link goes).
3. Put any new server routes in `webapp/server.py` under `/api/...` and a client call in `webapp/static/js/lib/api.js`.

Shared building blocks are in `webapp/static/js/lib/ui.js` (buttons, segmented controls, toggles, dialogs, menus,
toasts, dropzone, lightbox, compare slider) and all colours are CSS variables at the top of `webapp/static/css/app.css`,
so new pages get both themes for free.

## Run it

| What | Command |
|---|---|
| Scan photos | `python scan_image.py samples/photos --mode bw --debug` |
| Scan + view, click corners if detection fails | `python scan_image.py my_photo.jpg --show` |
| Force manual corners | `python scan_image.py my_photo.jpg --manual` |
| **Live webcam** | `python scan_live.py` |
| Live, auto-capture when held still | `python scan_live.py --auto` |
| Video file / RTSP camera | `python scan_live.py --source clip.mp4` · `--source rtsp://user:pass@ip:554/stream` |
| Record the demo | `python scan_live.py --record outputs/demo.mp4` |
| Calibrate camera (live) | `python calibrate.py --camera 0` (print `samples/chessboard_9x6.png`) |
| Calibrate from photos | `python calibrate.py --images "samples/calib_synth/*.png"` |
| Use calibration | `python scan_live.py --calib outputs/calib.npz` |
| Align to a known form (ORB/SIFT) | `python align_to_template.py --template samples/templates/synthetic_page.png --image samples/photos/synthetic_photo.jpg --method sift` |
| Tour of every A1 topic (figures) | `python module_tour.py` → `outputs/tour/` |
| Tests | `python tests/test_docscan.py` and `python tests/test_webapp.py` (or `python -m pytest -q`) |

**Live keys:** `SPACE`/`s` save · `m` cycle mode · `a` auto-capture · `d` debug window (edges, mask, candidates) · `u` undistortion on/off · `q` quit.

Outline turns **yellow** while the page moves and **green** once it is steady (bar at the bottom fills up).
With `--auto` a scan is saved once per steady hold.

## Where each Module A1 topic lives

| Learning goal | Code | What it does in the scanner |
|---|---|---|
| Pixels, channels, bit depth, NumPy arrays, BGR vs RGB | `docscan/basics.py` (`describe`, `bgr_to_rgb`, `reduce_bit_depth`, `adjust_region`) | tour figure 01; ROI edits via slicing + broadcasting |
| Colour spaces (RGB, HSV, gray, LAB) & colour segmentation | `basics.paper_mask_hsv`, `paper_mask_lab`, `detect.paper_mask` | "paper = low saturation + bright" detection strategy; CLAHE on LAB *L* in colour mode |
| Resize, crop, rotate, affine, perspective | `docscan/geometry.py` | work-resolution resizing, `four_point_warp` (homography), `rotate` for deskew, `estimate_aspect` recovers the real page ratio |
| Blur, sharpen, morphology, thresholding | `docscan/filters.py`, `docscan/enhance.py` | Gaussian blur before Canny, close to join edges, open/close on masks, Otsu + adaptive threshold for B&W, unsharp mask, shadow removal by dilate + median + divide |
| Canny, contours, Hough lines & circles | `docscan/detect.py` | auto-Canny → contours → `approxPolyDP`; `HoughLinesP` fallback when a corner is hidden + text deskew; `HoughCircles` punch-hole detection |
| ORB & SIFT keypoints, matching, homography | `docscan/features.py`, `align_to_template.py` | ratio test + RANSAC `findHomography` to scan a known form without seeing its edges |
| Calibration, lens distortion, video files & RTSP | `docscan/camera.py`, `calibrate.py`, `scan_live.py` | chessboard calibration, `Undistorter` (remap tables), webcam/file/RTSP sources, threaded latest-frame reader for streams, `VideoWriter` recording |

## How detection works (`docscan/detect.py`)

1. Downscale to 500 px height (fast, and removes fine texture).
2. **Edges:** Gaussian blur → Canny (auto thresholds from the median + fixed 50/150) → morphological close → contours → `approxPolyDP` to 4 points.
3. **Colour:** HSV (low S, high V) ∪ LAB (neutral a/b) ∩ Otsu → open/close → largest contour → 4 points.
4. Every candidate must be large enough, convex, with interior angles 35–145°. The biggest wins.
5. **Hough fallback:** if nothing passes, the outermost horizontal/vertical `HoughLinesP` lines are intersected.
6. **Sub-pixel refinement:** `cv2.fitLine` on full-res Canny pixels along each side, neighbouring lines intersected → corners within <1 px on the test set.
7. **True aspect ratio:** a tilted page looks squashed. Using the pinhole model (Zhang & He 2007) the real height/width is recovered from the 4 corners (uses `K` from calibration if given).

## Measured on the synthetic test set

| | Result |
|---|---|
| Corner error after refinement | 0.2 – 1.1 px (was 2–12 px before refinement) |
| Page ratio (true 1.294) | 1.288 – 1.296 |
| Calibration (simulated lens, f = 900) | f = 898.8, RMS 0.06 px |
| ORB / SIFT inliers vs template | ~170 / ~600 |
| Live speed (1280×960, headless incl. preview) | ~11 fps |

## Tips for a real demo

* Dark, plain background + white paper = easiest. A white page on a white desk is the hard case:
  the colour strategy fails, and only edges/Hough can help (or use `align_to_template.py`).
* Even light; avoid strong glare (it can erase part of the page outline).
* Use `d` in live mode to show the edge map, paper mask, and candidate quads when you explain the method.

## Project layout

```
app.py              starts the web app
webapp/             Flask API (server.py, storage.py, pdf.py, streams.py) + static/ frontend
docscan/            library (one module per topic group)
scan_image.py       still images (batch, debug montage, manual corners)
scan_live.py        webcam / video / RTSP with tracking + auto-capture
calibrate.py        chessboard calibration
align_to_template.py  ORB/SIFT homography alignment
module_tour.py      one figure per A1 topic
make_samples.py     synthetic photos, video, chessboard, calibration views
tests/              accuracy tests on synthetic ground truth
```
