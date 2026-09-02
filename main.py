# main.py
"""
HandClose: now with a pretty neon hand skeleton overlay.

New CLI:
  --no-skeleton          disable drawing
  --skeleton-style       neon|solid (default: neon)
  --skeleton-size        base thickness (default: 2)
"""

import argparse
import logging
import os
import time
import threading
from urllib.parse import urlparse, urlunparse

from config import (
    LOG_DIR,
    LOG_FILE,
    DEFAULT_WHITELIST,
    MAX_TRANSITION_TIME,
    COOLDOWN,
    HAND_CONFIDENCE,
    TRACKING_CONFIDENCE,
    GRACE_PERIOD,
)

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("handclose")

from hand_detector import HandDetector, HandStateMachine
import app_manager

try:
    import ctypes
except Exception:
    ctypes = None

# ---------- Drawing utilities ----------

def _denorm(pt, w, h):
    x = int(max(0, min(1, pt[0])) * w)
    y = int(max(0, min(1, pt[1])) * h)
    return x, y

_HAND_EDGES = [
    # palm
    (0,1),(1,2),(2,5),(5,9),(9,13),(13,17),(17,0),
    # thumb
    (1,2),(2,3),(3,4),
    # index
    (5,6),(6,7),(7,8),
    # middle
    (9,10),(10,11),(11,12),
    # ring
    (13,14),(14,15),(15,16),
    # pinky
    (17,18),(18,19),(19,20),
]

def draw_neon_skeleton(frame, landmarks, base=2, hue=(60,255,255)):
    """
    Neon glow style: draw fat blurred-like layers (manual) then crisp center.
    hue is HSV tuple-like (H,S,V) used to derive colors.
    """
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    overlay = frame.copy()

    # derive BGR colors from HSV-ish input (approx via OpenCV conversion)
    hsv = np.uint8([[[hue[0], hue[1], hue[2]]]])
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0][0].tolist()
    core = tuple(map(int, bgr))          # bright core
    outer = (int(bgr[0]*0.5), int(bgr[1]*0.5), int(bgr[2]*0.5))  # darker halo

    # multiple passes for halo
    for t in (base*6, base*4, base*2):
        for a, b in _HAND_EDGES:
            p1 = _denorm(landmarks[a], w, h)
            p2 = _denorm(landmarks[b], w, h)
            cv2.line(overlay, p1, p2, outer, t, cv2.LINE_AA)
        for i in range(21):
            c = _denorm(landmarks[i], w, h)
            cv2.circle(overlay, c, t//2, outer, -1, lineType=cv2.LINE_AA)

    # crisp center strokes
    for a, b in _HAND_EDGES:
        p1 = _denorm(landmarks[a], w, h)
        p2 = _denorm(landmarks[b], w, h)
        cv2.line(overlay, p1, p2, core, base+1, cv2.LINE_AA)
    for i in range(21):
        c = _denorm(landmarks[i], w, h)
        cv2.circle(overlay, c, base+3, (255,255,255), -1, lineType=cv2.LINE_AA)
        cv2.circle(overlay, c, base+3, core, 2, lineType=cv2.LINE_AA)

    # gentle blend
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

def draw_solid_skeleton(frame, landmarks, base=2, color=(50,220,255)):
    import cv2
    h, w = frame.shape[:2]
    for a, b in _HAND_EDGES:
        p1 = _denorm(landmarks[a], w, h)
        p2 = _denorm(landmarks[b], w, h)
        cv2.line(frame, p1, p2, color, base+1, cv2.LINE_AA)
    for i in range(21):
        c = _denorm(landmarks[i], w, h)
        cv2.circle(frame, c, base+3, (255,255,255), -1, lineType=cv2.LINE_AA)
        cv2.circle(frame, c, base+3, color, 2, lineType=cv2.LINE_AA)

# ---------- App closing bits ----------

def load_whitelist(path=None):
    wl = list(DEFAULT_WHITELIST)
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for ln in f:
                    s = ln.strip()
                    if not s or s.startswith("#"):
                        continue
                    wl.append(s)
        except Exception:
            log.exception("Failed to load whitelist file '%s'", path)
    return wl

def confirm_dialog(text, title="Confirm"):
    if ctypes is None:
        return False
    MB_YESNO = 0x04
    IDYES = 6
    return ctypes.windll.user32.MessageBoxW(0, text, title, MB_YESNO) == IDYES

def perform_close_sequence(simulate, whitelist):
    try:
        candidates = app_manager.list_user_windows(whitelist=whitelist)
    except Exception as e:
        log.exception("Failed to list windows: %s", e)
        return
    if not candidates:
        log.info("No candidate user windows to close.")
        return
    log.info("Candidates to close: %s", [(c['title'], c['exe']) for c in candidates])
    for c in candidates:
        try:
            r = app_manager.close_application(c, simulate=simulate, grace_period=GRACE_PERIOD)
            log.info("Close result: %s", r)
        except Exception:
            log.exception("Error while closing candidate: %s", c)

# ---------- Camera helpers (same as ранее, урезано для краткости) ----------

def _derive_alt_urls(base_url: str):
    try:
        parsed = urlparse(base_url)
    except Exception:
        return [base_url]
    scheme = parsed.scheme or "http"; netloc = parsed.netloc
    c = [base_url]
    for p in ("/video", "/mjpegfeed", "/stream/video.mjpeg"):
        c.append(urlunparse((scheme, netloc, p, "", "", "")))
    for hint in ("?1280x720", "?960x540", "?640x480"):
        c.append(urlunparse((scheme, netloc, "/video", "", "", "")) + hint)
    # dedup
    return list(dict.fromkeys(c))

def _try_open_url(url: str):
    import cv2
    for backend in (cv2.CAP_FFMPEG, 0):
        cap = cv2.VideoCapture(url, backend) if backend else cv2.VideoCapture(url)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok and frame is not None:
                return cap, True
            cap.release()
    return None, False

def open_capture(camera_index: int, camera_url: str, backend: str, probe_url: bool):
    import cv2
    if camera_url:
        urls = _derive_alt_urls(camera_url) if probe_url else [camera_url]
        log.info("Probing URL variants: %s", urls)
        for u in urls:
            cap, ok = _try_open_url(u)
            if ok:
                log.info("Using camera URL: %s", u)
                return cap
        return None
    # local
    if backend == "dshow":
        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap
    if backend == "msmf":
        cap = cv2.VideoCapture(camera_index, cv2.CAP_MSMF)
        if cap.isOpened():
            return cap
    # auto: try both
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(camera_index, cv2.CAP_MSMF)
    return cap

def list_cameras(max_index=10):
    import cv2
    results=[]
    for i in range(max_index+1):
        for name, backend in (("dshow", cv2.CAP_DSHOW), ("msmf", cv2.CAP_MSMF)):
            cap = cv2.VideoCapture(i, backend); opened = cap.isOpened()
            ret, frame = (False, None)
            if opened: ret, frame = cap.read()
            if cap: cap.release()
            results.append((i, name, opened, bool(ret and frame is not None)))
    log.info("Camera probe results (index, backend, opened, got_frame): %s", results)
    print("index | backend | opened | got_frame")
    for (i, name, opened, got) in results:
        print(f"{i:5d} | {name:7s} | {str(opened):6s} | {str(got):9s}")

# ---------- Main ----------

def main():
    import cv2

    parser = argparse.ArgumentParser(description="Hand-based app closer (Windows) with pretty skeleton.")
    # simulate toggles (фикс)
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--simulate", dest="simulate", action="store_true",
                   help="Safe mode: don't actually close apps (default).")
    g.add_argument("--no-simulate", dest="simulate", action="store_false",
                   help="Allow real app closing (with other safeties).")
    parser.set_defaults(simulate=True)

    parser.add_argument("--auto-exec", action="store_true")
    parser.add_argument("--no-confirmation", dest="require_confirmation", action="store_false")
    parser.add_argument("--whitelist", type=str)

    parser.add_argument("--max-transition-time", type=float, default=MAX_TRANSITION_TIME)
    parser.add_argument("--cooldown", type=float, default=COOLDOWN)
    parser.add_argument("--confidence", type=float, default=HAND_CONFIDENCE)

    # camera
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", type=str, default="auto", choices=["auto","dshow","msmf"])
    parser.add_argument("--camera-url", type=str, default=None)
    parser.add_argument("--probe-url", action="store_true")
    parser.add_argument("--list-cameras", action="store_true")

    # skeleton rendering
    parser.add_argument("--no-skeleton", action="store_true", help="Disable drawing hand skeleton overlay.")
    parser.add_argument("--skeleton-style", type=str, default="neon", choices=["neon","solid"])
    parser.add_argument("--skeleton-size", type=int, default=2, help="Base thickness/radius for skeleton cosmetics.")

    args = parser.parse_args()
    if args.list_cameras and not args.camera_url:
        list_cameras()
        return
    if args.auto_exec and args.simulate:
        log.info("Note: --auto-exec passed but simulate is ON; remove --simulate/enable --no-simulate for real actions.")

    whitelist = load_whitelist(args.whitelist)
    log.info("Loaded whitelist: %s", whitelist)

    sm = HandStateMachine(max_transition_time=args.max_transition_time, cooldown=args.cooldown)
    try:
        detector = HandDetector(min_detection_confidence=args.confidence, min_tracking_confidence=TRACKING_CONFIDENCE)
    except Exception as e:
        log.exception("Failed to initialize HandDetector: %s", e)
        return

    cap = open_capture(args.camera, args.camera_url, args.backend, args.probe_url)
    if not cap or not cap.isOpened():
        log.error("Cannot open video source")
        return

    simulate = args.simulate
    auto_exec = args.auto_exec
    require_confirmation = getattr(args, "require_confirmation", True)

    log.info("Starting camera loop. Simulate=%s AutoExec=%s RequireConfirmation=%s Source=%s",
             simulate, auto_exec, require_confirmation, args.camera_url or f"index:{args.camera}/{args.backend}")

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue

            state, conf, lm = detector.process_frame(frame)
            ts = time.time()
            triggered, info = sm.feed(state, ts)

            # pretty overlay
            if not args.no_skeleton and lm:
                if args.skeleton_style == "neon":
                    draw_neon_skeleton(frame, lm, base=max(1, args.skeleton_size))
                else:
                    draw_solid_skeleton(frame, lm, base=max(1, args.skeleton_size))

            # HUD
            cv2.putText(frame, f"Conf:{conf:.2f}", (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200,255,200), 2)
            if state:
                cv2.putText(frame, f"{state}", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0,255,0), 2)
            cv2.putText(frame, "Q - quit", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220,220,220), 1)

            if triggered:
                log.info("Gesture triggered at %s (info=%s)", ts, info)
                if auto_exec:
                    do_exec = True
                    if require_confirmation:
                        do_exec = confirm_dialog("Hand gesture detected: close user applications?")
                    if do_exec:
                        t = threading.Thread(target=perform_close_sequence, args=(simulate, whitelist), daemon=True)
                        t.start()
                else:
                    log.info("Auto-exec disabled: will not perform closures. (simulate=%s)", simulate)

            cv2.imshow("HandClose (Press Q to quit)", frame)
            if (cv2.waitKey(1) & 0xFF) == ord('q'):
                log.info("Quitting by user request.")
                break
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        try: detector.close()
        except Exception: pass
        try: cap.release()
        except Exception: pass
        try:
            import cv2
            cv2.destroyAllWindows()
        except Exception:
            pass


if __name__ == "__main__":
    main()
