# hand_detector.py
"""
MediaPipe-based hand detector with a tiny state machine and (new)
exposed landmarks for pretty skeleton rendering.

Exports:
- HandDetector: wrapper over MediaPipe Hands; returns hand state + landmarks.
- HandStateMachine: OPEN -> FIST transition with cooldown.

Notes:
- We add a simple EMA smoothing for landmarks to make the skeleton steadier.
"""

import time
import logging

try:
    import cv2
    import mediapipe as mp
except Exception as e:
    cv2 = None
    mp = None
    logging.warning("Some vision libraries are not installed: %s", e)

log = logging.getLogger(__name__)


class HandDetector:
    """Wrapper around MediaPipe Hands to get a simple hand 'state' and landmarks."""

    def __init__(self, min_detection_confidence=0.7, min_tracking_confidence=0.6, max_num_hands=1, smooth_alpha=0.35):
        if mp is None or cv2 is None:
            raise ImportError("OpenCV and MediaPipe are required for HandDetector")
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=max_num_hands,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        # EMA smoothing buffer: list of 21 (x,y,z)
        self._ema = None
        self._alpha = float(smooth_alpha)

    def _ema_update(self, pts):
        """Exponential moving average over normalized landmarks."""
        if pts is None:
            self._ema = None
            return None
        if self._ema is None:
            self._ema = [(p.x, p.y, p.z) for p in pts]
            return self._ema
        a = self._alpha
        out = []
        for (ex, ey, ez), p in zip(self._ema, pts):
            nx = a * p.x + (1 - a) * ex
            ny = a * p.y + (1 - a) * ey
            nz = a * p.z + (1 - a) * ez
            out.append((nx, ny, nz))
        self._ema = out
        return out

    @staticmethod
    def _fingers_up_from_landmarks(lm):
        """
        Count 'fingers up' using tip vs pip y (thumb by x).
        lm can be list of landmark objects or list of tuples.
        """
        # access helper
        def get(i):
            v = lm[i]
            if hasattr(v, "x"):
                return v.x, v.y, v.z
            return v

        fingers_up = 0
        tips = [4, 8, 12, 16, 20]
        pips = [2, 6, 10, 14, 18]
        for tip_idx, pip_idx in zip(tips, pips):
            tx, ty, _ = get(tip_idx)
            px, py, _ = get(pip_idx)
            if tip_idx == 4:
                if abs(tx - px) > 0.04 and tx < px:
                    fingers_up += 1
            else:
                if ty < py:
                    fingers_up += 1
        return fingers_up

    def process_frame(self, frame_bgr):
        """
        Runs mediapipe on BGR frame.
        Returns: (state ('OPEN'|'FIST'|None), confidence float, landmarks_smooth or None)
        landmarks_smooth is a list of 21 tuples (x,y,z) in normalized coords.
        """
        try:
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            results = self.hands.process(frame_rgb)
            if not results.multi_hand_landmarks:
                self._ema = None
                return None, 0.0, None

            raw = results.multi_hand_landmarks[0].landmark
            smoothed = self._ema_update(raw)

            fingers_up = self._fingers_up_from_landmarks(smoothed or raw)
            confidence = 1.0  # mediapipe API doesn't expose per-hand score; treat as detected.

            if fingers_up >= 4:
                return "OPEN", confidence, smoothed
            elif fingers_up <= 1:
                return "FIST", confidence, smoothed
            else:
                return None, confidence, smoothed
        except Exception as e:
            log.exception("Error processing frame: %s", e)
            return None, 0.0, None

    def close(self):
        try:
            self.hands.close()
        except Exception:
            pass


class HandStateMachine:
    """
    Maintains state for sequence OPEN -> FIST within max_transition_time.
    Respects cooldown after trigger.

    API:
    - feed(state, timestamp) -> (triggered: bool, info: dict)
    """

    def __init__(self, max_transition_time=1.5, cooldown=10.0):
        self.max_transition_time = float(max_transition_time)
        self.cooldown = float(cooldown)
        self.last_open_ts = None
        self.last_trigger_ts = 0.0

    def feed(self, state, ts=None):
        ts = ts or time.time()
        info = {"state": state, "ts": ts}
        if ts - self.last_trigger_ts < self.cooldown:
            info["reason"] = "cooldown"
            return False, info

        if state == "OPEN":
            self.last_open_ts = ts
            info["note"] = "open_seen"
            return False, info

        if state == "FIST":
            if self.last_open_ts and (0 <= ts - self.last_open_ts <= self.max_transition_time):
                self.last_trigger_ts = ts
                self.last_open_ts = None
                info["note"] = "triggered"
                return True, info
            else:
                info["reason"] = "no_recent_open"
                return False, info

        return False, info
