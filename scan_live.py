"""Live document scanner: webcam, video file or RTSP/HTTP stream.

Examples
--------
    python scan_live.py                         # default laptop webcam (index 0)
    python scan_live.py --source 1              # another camera
    python scan_live.py --source samples/synthetic_video.mp4
    python scan_live.py --source rtsp://user:pass@192.168.1.20:554/stream1
    python scan_live.py --calib outputs/calib.npz --auto
    python scan_live.py --source clip.mp4 --no-window --record outputs/demo.mp4

Keys
----
    SPACE / s  save a scan now          m  cycle mode (color / gray / bw / original)
    a          toggle auto-capture      d  toggle debug window (edges, mask, candidates)
    u          toggle undistortion      q / Esc  quit
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from docscan import scan_document
from docscan.camera import LatestFrameReader, Undistorter, is_stream, open_source, source_info
from docscan.detect import find_document, refine_corners
from docscan.enhance import MODES, enhance
from docscan.tracking import CornerTracker
from docscan.geometry import estimate_aspect, four_point_warp
from docscan.viz import fit, label, montage

VIEW_HEIGHT = 540
PREVIEW_SIZE = (380, VIEW_HEIGHT)


def preview_scan(frame, corners, mode, K):
    """Fast low-res warp + enhance for the side panel."""
    s = 0.5
    small = cv2.resize(frame, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    aspect = estimate_aspect(corners, (frame.shape[1], frame.shape[0]), K)
    warped, _ = four_point_warp(small, corners * s, aspect)
    return enhance(warped, mode)


def draw_hud(frame, corners, tracker, method, mode, fps, auto, undistorting, flash):
    out = frame.copy()
    if corners is not None:
        color = (0, 220, 0) if tracker.is_stable else (0, 200, 255)
        overlay = out.copy()
        cv2.fillPoly(overlay, [corners.astype(np.int32)], color)
        out = cv2.addWeighted(overlay, 0.15, out, 0.85, 0)
        cv2.polylines(out, [corners.astype(np.int32)], True, color, 3, cv2.LINE_AA)
        for x, y in corners:
            cv2.circle(out, (int(x), int(y)), 8, color, -1, cv2.LINE_AA)
        # stability bar
        w = out.shape[1]
        cv2.rectangle(out, (0, out.shape[0] - 10), (int(w * tracker.progress), out.shape[0]), color, -1)
    status = f"{mode} | {method or 'searching...'} | {fps:4.1f} fps | auto {'ON' if auto else 'off'}"
    if undistorting:
        status += " | undistort"
    out = label(out, status)
    if flash:
        out = cv2.addWeighted(out, 0.4, np.full_like(out, 255), 0.6, 0)
    return out


def save_scan(frame, corners, mode, K, out_dir: Path) -> Path:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners = refine_corners(gray, corners.astype(np.float32))   # sub-pixel on the full frame
    result = scan_document(frame, mode, corners=corners, aspect="auto", K=K)
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
    path = out_dir / f"live_{stamp}_{mode}.png"
    cv2.imwrite(str(path), result.scan)
    cv2.imwrite(str(out_dir / f"live_{stamp}_frame.jpg"), frame)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="0", help="webcam index, video file or rtsp:// URL")
    ap.add_argument("--width", type=int, default=1280, help="requested webcam width")
    ap.add_argument("--height", type=int, default=720, help="requested webcam height")
    ap.add_argument("--mode", choices=MODES, default="color")
    ap.add_argument("--out", default="outputs/live", help="where captured scans go")
    ap.add_argument("--calib", help="calibration .npz from calibrate.py")
    ap.add_argument("--auto", action="store_true", help="auto-capture when the page is held still")
    ap.add_argument("--min-area", type=float, default=0.15)
    ap.add_argument("--record", help="save the annotated view to this video file (.mp4/.avi)")
    ap.add_argument("--no-window", action="store_true", help="headless: no GUI (for testing)")
    ap.add_argument("--max-frames", type=int, default=0, help="stop after N frames (0 = no limit)")
    ap.add_argument("--loop", action="store_true", help="restart video files at the end")
    args = ap.parse_args(argv)

    cap = open_source(args.source, args.width, args.height)
    info = source_info(cap)
    print(f"opened {args.source}: {info}")
    reader = LatestFrameReader(cap) if is_stream(args.source) else cap
    is_file = not str(args.source).isdigit() and not is_stream(args.source)

    undistort = Undistorter.from_file(args.calib) if args.calib else None
    use_undistort = undistort is not None
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tracker = CornerTracker()
    mode_idx = MODES.index(args.mode)
    auto, show_debug = args.auto, False
    captured_this_hold, last_capture, flash_until = False, 0.0, 0.0
    fps, t_prev = 0.0, time.perf_counter()
    writer, n_frames, n_saved = None, 0, 0

    while True:
        ok, frame = reader.read()
        if not ok or frame is None:
            if is_file and args.loop:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            break
        n_frames += 1
        if use_undistort:
            frame = undistort(frame)
        K = undistort.new_K if use_undistort else None
        mode = MODES[mode_idx]

        # detection is fast without sub-pixel refinement; that is done at capture time
        det = find_document(frame, args.min_area, keep_debug=show_debug, refine=False)
        diag = float(np.hypot(*frame.shape[:2]))
        corners = tracker.update(det.corners if det else None, diag)

        # ---- auto capture: once per steady hold
        if tracker.stable == 0:
            captured_this_hold = False
        now = time.perf_counter()
        if auto and tracker.is_stable and not captured_this_hold and now - last_capture > 2.0:
            path = save_scan(frame, corners, mode, K, out_dir)
            print(f"[auto] saved {path}")
            captured_this_hold, last_capture, flash_until = True, now, now + 0.15
            n_saved += 1

        # ---- draw
        dt = now - t_prev
        t_prev = now
        fps = 0.9 * fps + 0.1 * (1.0 / dt) if dt > 0 else fps
        hud = draw_hud(frame, corners, tracker, det.method if det else None, mode, fps, auto,
                       use_undistort, now < flash_until)
        view = cv2.resize(hud, (int(hud.shape[1] * VIEW_HEIGHT / hud.shape[0]), VIEW_HEIGHT),
                          interpolation=cv2.INTER_AREA)
        if corners is not None:
            panel = label(fit(preview_scan(frame, corners, mode, K), *PREVIEW_SIZE), "preview")
        else:
            panel = label(np.full((PREVIEW_SIZE[1], PREVIEW_SIZE[0], 3), 40, np.uint8), "no page")
        canvas = np.hstack([view, panel])

        if args.record:
            if writer is None:
                fps_out = info["fps"] if 1 < info["fps"] < 120 else 20
                writer = cv2.VideoWriter(args.record, cv2.VideoWriter_fourcc(*"mp4v"), fps_out,
                                         (canvas.shape[1], canvas.shape[0]))
            writer.write(canvas)

        if args.max_frames and n_frames >= args.max_frames:
            break
        if args.no_window:
            continue

        cv2.imshow("docscan live", canvas)
        if show_debug and det is not None and det.debug:
            cv2.imshow("docscan debug", montage(det.debug, cols=2, cell=(400, 300)))

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key in (ord(" "), ord("s")):
            if corners is not None:
                path = save_scan(frame, corners, mode, K, out_dir)
                print(f"[manual] saved {path}")
                flash_until = now + 0.15
                n_saved += 1
            else:
                print("no page in view - nothing saved")
        elif key == ord("m"):
            mode_idx = (mode_idx + 1) % len(MODES)
        elif key == ord("a"):
            auto = not auto
        elif key == ord("d"):
            show_debug = not show_debug
            if not show_debug:
                cv2.destroyWindow("docscan debug")
        elif key == ord("u") and undistort is not None:
            use_undistort = not use_undistort

    reader.release()
    if writer is not None:
        writer.release()
    cv2.destroyAllWindows()
    print(f"processed {n_frames} frames, saved {n_saved} scan(s) to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
