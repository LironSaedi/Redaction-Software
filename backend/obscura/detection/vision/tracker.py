"""Offline multi-object tracking for video redaction.

Because the whole video is available, tracking is done offline and then *post-processed for safety*:

1. ByteTrack-style association (Kalman-predicted boxes, IoU cost, Hungarian matching; low-score
   detections only extend existing tracks)
2. gaps inside a track are interpolated, so a missed detection never leaves a frame unredacted
3. each track is extended backwards/forwards (pre-roll / post-roll) so redaction starts before a face is
   fully detectable and stays on after the detector loses it
4. boxes are temporally smoothed and then *unioned* with the raw boxes (smoothing never shrinks coverage)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from .detectors import VBox


class _Kalman:
    """Constant-velocity Kalman filter on (cx, cy, w, h)."""

    def __init__(self, box: VBox):
        cx, cy, w, h = _xywh(box)
        self.x = np.array([cx, cy, w, h, 0, 0, 0, 0], dtype=float)
        self.P = np.diag([10, 10, 10, 10, 1e3, 1e3, 1e3, 1e3]).astype(float)
        self.F = np.eye(8)
        for i in range(4):
            self.F[i, i + 4] = 1
        self.H = np.eye(4, 8)
        self.Q = np.diag([1, 1, 1, 1, 0.01, 0.01, 0.01, 0.01]) * max(1.0, w * 0.05)
        self.R = np.diag([1, 1, 4, 4]) * max(1.0, w * 0.1)

    def predict(self) -> np.ndarray:
        self.x = self.F @ self.x
        self.x[2:4] = np.maximum(self.x[2:4], 2)
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x[:4]

    def update(self, box: VBox) -> None:
        z = np.array(_xywh(box))
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(8) - K @ self.H) @ self.P


def _xywh(b: VBox) -> tuple[float, float, float, float]:
    return (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, b.x1 - b.x0, b.y1 - b.y0


def _box(cx, cy, w, h) -> tuple[float, float, float, float]:
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def _iou(a, b) -> float:
    ix0, iy0, ix1, iy1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


@dataclass
class Track:
    id: int
    label: str
    obs: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)
    scores: dict[int, float] = field(default_factory=dict)
    boxes: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)  # final, per frame
    enabled: bool = True
    source: str = "auto"
    effect: str | None = None   # per-track override (blur / pixelate / blackout)
    shape: str | None = None    # rect / ellipse

    @property
    def max_score(self) -> float:
        return max(self.scores.values()) if self.scores else 1.0

    @property
    def first(self) -> int:
        return min(self.boxes or self.obs)

    @property
    def last(self) -> int:
        return max(self.boxes or self.obs)

    def to_dict(self, compact: bool = False) -> dict:
        d = {"id": int(self.id), "label": self.label, "enabled": bool(self.enabled), "source": self.source,
             "first": int(self.first), "last": int(self.last), "max_score": round(float(self.max_score), 3),
             "observations": len(self.obs), "effect": self.effect, "shape": self.shape}
        if not compact:
            d["boxes"] = {str(int(k)): [round(float(v), 1) for v in b] for k, b in sorted(self.boxes.items())}
        return d

    @staticmethod
    def from_dict(d: dict) -> "Track":
        t = Track(int(d["id"]), d["label"], enabled=bool(d.get("enabled", True)), source=d.get("source", "auto"),
                  effect=d.get("effect"), shape=d.get("shape"))
        t.boxes = {int(k): tuple(v) for k, v in d.get("boxes", {}).items()}
        t.obs = dict(t.boxes)
        t.scores = {k: float(d.get("max_score", 1)) for k in list(t.boxes)[:1]}
        return t


def track(detections: dict[int, list[VBox]], n_frames: int, fps: float, width: int, height: int,
          high: float = 0.4, low: float = 0.15, iou_gate: float = 0.15, max_age_s: float = 1.0,
          pre_roll_s: float = 0.25, post_roll_s: float = 0.5, min_obs: int = 2,
          pad: dict[str, float] | None = None) -> list[Track]:
    pad = pad or {"face": 0.2, "head": 0.1, "license_plate": 0.15}
    max_age = max(3, int(round(fps * max_age_s)))
    tracks: list[Track] = []
    by_label: dict[str, list[tuple[Track, _Kalman, int]]] = {}
    next_id = 1
    for f in range(n_frames):
        dets = detections.get(f, [])
        for label in {d.label for d in dets} | set(by_label):
            active = by_label.setdefault(label, [])
            preds = [_box(*kf.predict()) for _, kf, _ in active]
            ldets = [d for d in dets if d.label == label]
            hi = [d for d in ldets if d.score >= high]
            lo = [d for d in ldets if low <= d.score < high]
            unmatched_t = list(range(len(active)))
            hi_unused = list(range(len(hi)))
            for is_hi, pool in ((True, hi), (False, lo)):
                if not pool or not unmatched_t:
                    continue
                cost = np.ones((len(unmatched_t), len(pool)))
                for i, ti in enumerate(unmatched_t):
                    for j, d in enumerate(pool):
                        cost[i, j] = 1 - _iou(preds[ti], (d.x0, d.y0, d.x1, d.y1))
                rows, cols = linear_sum_assignment(cost)
                matched, used = set(), set()
                for r, c in zip(rows, cols):
                    if 1 - cost[r, c] < iou_gate:
                        continue
                    ti = unmatched_t[r]
                    t, kf, _ = active[ti]
                    d = pool[c]
                    kf.update(d)
                    t.obs[f] = (d.x0, d.y0, d.x1, d.y1)
                    t.scores[f] = d.score
                    active[ti] = (t, kf, f)
                    matched.add(ti)
                    used.add(c)
                unmatched_t = [ti for ti in unmatched_t if ti not in matched]
                if is_hi:
                    hi_unused = [j for j in range(len(hi)) if j not in used]
            for j in hi_unused:  # unmatched confident detections start new tracks
                d = hi[j]
                t = Track(next_id, label)
                next_id += 1
                t.obs[f] = (d.x0, d.y0, d.x1, d.y1)
                t.scores[f] = d.score
                tracks.append(t)
                active.append((t, _Kalman(d), f))
            by_label[label] = [(t, kf, ls) for t, kf, ls in active if f - ls <= max_age]
    out = []
    for t in tracks:
        if len(t.obs) < min_obs and t.max_score < 0.6:
            continue  # one weak blip is noise; a single confident detection is still redacted
        _finalise(t, n_frames, fps, width, height, pre_roll_s, post_roll_s, pad.get(t.label, 0.1))
        out.append(t)
    return out


def _finalise(t: Track, n_frames: int, fps: float, w: int, h: int, pre_s: float, post_s: float,
              pad_frac: float) -> None:
    frames = sorted(t.obs)
    boxes: dict[int, tuple] = {}
    for a, b in zip(frames, frames[1:] + [None]):
        boxes[a] = t.obs[a]
        if b is None:
            break
        ba, bb = np.array(t.obs[a]), np.array(t.obs[b])
        for k in range(a + 1, b):  # linear interpolation across gaps
            alpha = (k - a) / (b - a)
            boxes[k] = tuple(ba * (1 - alpha) + bb * alpha)
    pre, post = int(round(fps * pre_s)), int(round(fps * post_s))
    first, last = frames[0], frames[-1]
    for k in range(max(0, first - pre), first):
        boxes[k] = t.obs[first]
    # post-roll: extrapolate the last motion a little, then hold
    if len(frames) >= 2:
        v = (np.array(t.obs[last]) - np.array(t.obs[frames[-2]])) / max(1, last - frames[-2])
    else:
        v = np.zeros(4)
    for k in range(last + 1, min(n_frames, last + 1 + post)):
        boxes[k] = tuple(np.array(t.obs[last]) + v * min(k - last, 5))
    # temporal smoothing (window 5), unioned with the raw box so coverage never shrinks
    keys = sorted(boxes)
    arr = np.array([boxes[k] for k in keys])
    sm = arr.copy()
    for i in range(len(keys)):
        lo, hi = max(0, i - 2), min(len(keys), i + 3)
        sm[i] = arr[lo:hi].mean(axis=0)
    final = {}
    for i, k in enumerate(keys):
        x0 = min(arr[i][0], sm[i][0])
        y0 = min(arr[i][1], sm[i][1])
        x1 = max(arr[i][2], sm[i][2])
        y1 = max(arr[i][3], sm[i][3])
        bw, bh = x1 - x0, y1 - y0
        final[k] = (max(0.0, x0 - bw * pad_frac), max(0.0, y0 - bh * pad_frac), min(float(w), x1 + bw * pad_frac),
                    min(float(h), y1 + bh * pad_frac))
    t.boxes = final


def interpolate_keyframes(keyframes: dict[int, tuple], n_frames: int) -> dict[int, tuple]:
    """Manual redaction: linear interpolation between user keyframes, held constant past the ends."""
    ks = sorted(keyframes)
    if not ks:
        return {}
    out = {}
    for a, b in zip(ks, ks[1:]):
        ba, bb = np.array(keyframes[a]), np.array(keyframes[b])
        for k in range(a, b):
            alpha = (k - a) / (b - a)
            out[k] = tuple(ba * (1 - alpha) + bb * alpha)
    out[ks[-1]] = tuple(keyframes[ks[-1]])
    return {k: v for k, v in out.items() if 0 <= k < n_frames}
