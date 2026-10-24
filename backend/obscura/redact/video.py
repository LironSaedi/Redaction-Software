"""Video redaction: detect → track → review → render (with optional audio redaction), all local.

Encoding uses the bundled ffmpeg (imageio-ffmpeg) — H.264 video, AAC audio, metadata stripped.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np

from ..detection.vision.detectors import VBox, get_detector
from ..detection.vision.tracker import Track, interpolate_keyframes, track
from .effects import apply_effect

log = logging.getLogger("obscura.video")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


@dataclass
class VideoInfo:
    fps: float
    frames: int
    width: int
    height: int
    duration: float
    has_audio: bool
    rotation: int = 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def probe_duration(path: str | Path) -> float:
    """Duration from ffmpeg's header parse (works for audio-only files OpenCV cannot open)."""
    err = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0


def probe(path: str | Path) -> VideoInfo:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("cannot open video")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    err = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    has_audio = bool(re.search(r"Stream #\d+:\d+.*Audio:", err))
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else (n / fps if fps else 0)
    if n <= 0:
        n = int(dur * fps)
    return VideoInfo(fps, n, w, h, dur, has_audio)


class VideoDocument:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.info = probe(path)
        self.tracks: list[Track] = []

    # ---------------------------------------------------------------------------------------
    MODES = {
        # mode: (face stride, plate stride, object/head stride, imgsz cap, use YuNet)
        "max_accuracy": (1, 1, 1, 1280, True),
        "balanced": (1, 2, 3, 960, True),
        "fast": (2, 3, 4, 640, True),
    }

    def analyze(self, classes: set[str] | None = None, mode: str = "balanced", batch: int = 8, progress=None) -> list[Track]:
        classes = classes or {"face", "license_plate"}
        fs, ps, os_, cap_sz, use_yunet = self.MODES.get(mode, self.MODES["balanced"])
        imgsz = min(cap_sz, 1280 if max(self.info.width, self.info.height) > 1000 else 960)
        if max(self.info.width, self.info.height) >= 2500 and mode != "fast":
            imgsz = 1280  # 4K bodycam: small faces need resolution
        det = get_detector()
        groups = [({"face"} & classes, fs), ({"license_plate"} & classes, ps),
                  (classes & {"head", "person", "vehicle", "screen", "document"}, os_)]
        groups = [(g, st) for g, st in groups if g]
        cap = cv2.VideoCapture(str(self.path))
        dets: dict[int, list[VBox]] = {}
        f = 0
        buf: list[tuple[int, np.ndarray]] = []

        def flush():
            for g, st in groups:
                sel = [(k, fr) for k, fr in buf if k % st == 0]
                if not sel:
                    continue
                want = set(g)
                if "head" in want:
                    want.add("face")  # head fallback needs this frame's faces
                res = det.detect_batch([fr for _, fr in sel], want, use_yunet=use_yunet and "face" in g, imgsz=imgsz)
                for (k, _), r in zip(sel, res):
                    keep = [b for b in r if b.label in g or (b.label == "face" and "face" in classes)]
                    dets.setdefault(k, []).extend(keep)

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            buf.append((f, frame))
            if len(buf) >= batch:
                flush()
                buf = []
                if progress:
                    progress(f + 1, self.info.frames)
            f += 1
        if buf:
            flush()
        cap.release()
        n = max(f, self.info.frames)
        self.info.frames = n
        from ..detection.vision.detectors import merge_union
        dets = {k: merge_union(v) for k, v in dets.items()}
        self.tracks = track(dets, n, self.info.fps, self.info.width, self.info.height)
        return self.tracks

    def add_manual_track(self, frame: int, box: tuple[float, float, float, float], label: str = "manual",
                         mode: str = "track", end_frame: int | None = None, keyframes: dict | None = None,
                         effect: str | None = None, shape: str | None = None) -> Track:
        """mode: "track" (follow the object with CSRT until lost), "static" (fixed box for a range),
        "keyframes" (interpolate between user boxes)."""
        tid = max([t.id for t in self.tracks] + [0]) + 1
        t = Track(tid, label, source=f"manual:{mode}")
        n = self.info.frames
        end = min(n - 1, end_frame if end_frame is not None else n - 1)
        if mode == "full_frame":  # blur / black out the whole picture for a time range
            t.label = "full_frame"
            t.boxes = {k: (0.0, 0.0, float(self.info.width), float(self.info.height)) for k in range(frame, end + 1)}
        elif mode == "keyframes" and keyframes:
            t.boxes = interpolate_keyframes({int(k): tuple(v) for k, v in keyframes.items()}, n)
        elif mode == "static":
            t.boxes = {k: tuple(box) for k in range(frame, end + 1)}
        else:
            t.boxes = self._csrt(frame, box, end)
        t.obs = dict(t.boxes)
        t.scores = {frame: 1.0}
        t.effect, t.shape = effect, shape
        self.tracks.append(t)
        return t

    def _csrt(self, frame: int, box, end: int) -> dict[int, tuple]:
        cap = cv2.VideoCapture(str(self.path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, img = cap.read()
        if not ok:
            return {frame: tuple(box)}
        x0, y0, x1, y1 = box
        tr = None
        for factory in ("TrackerCSRT_create", "TrackerKCF_create", "TrackerMIL_create"):
            for mod in (cv2, getattr(cv2, "legacy", None)):
                if mod is not None and hasattr(mod, factory):
                    tr = getattr(mod, factory)()
                    break
            if tr is not None:
                break
        if tr is None:  # pragma: no cover
            return {k: tuple(box) for k in range(frame, end + 1)}
        tr.init(img, (int(x0), int(y0), int(x1 - x0), int(y1 - y0)))
        out = {frame: tuple(box)}
        f = frame
        lost = 0
        last = tuple(box)
        while f < end:
            ok, img = cap.read()
            if not ok:
                break
            f += 1
            ok, bb = tr.update(img)
            if ok:
                x, y, w, h = bb
                last = (x, y, x + w, y + h)
                lost = 0
            else:
                lost += 1
                if lost > self.info.fps:  # gone for a second: stop following
                    break
            out[f] = last  # hold the last good box while the tracker re-acquires
        cap.release()
        return out

    # ---------------------------------------------------------------------------------------
    def frame(self, f: int) -> np.ndarray | None:
        cap = cv2.VideoCapture(str(self.path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, f))
        ok, img = cap.read()
        cap.release()
        return img if ok else None

    def frame_jpeg(self, f: int, preview: bool = False, effect: str = "blur", max_side: int = 1280) -> bytes:
        img = self.frame(f)
        if img is None:
            raise IndexError(f)
        if preview:
            for t in self.tracks:
                if t.enabled and f in t.boxes:
                    eff = t.effect or effect
                    b = (0, 0, img.shape[1], img.shape[0]) if t.label == "full_frame" else t.boxes[f]
                    shape = t.shape or ("ellipse" if t.label in ("face", "head") and eff in ("blur", "pixelate") else "rect")
                    apply_effect(img, *b, effect=eff, shape=shape)
        h, w = img.shape[:2]
        if max(h, w) > max_side:
            s = max_side / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()

    def boxes_at(self, f: int) -> list[dict]:
        return [{"track": t.id, "label": t.label, "enabled": t.enabled, "box": [round(v, 1) for v in t.boxes[f]]}
                for t in self.tracks if f in t.boxes]

    # ---------------------------------------------------------------------------------------
    def render(self, out_path: str | Path, effect: str = "blur", audio: str | Path | None = "original",
               progress=None, verify: bool = True, crf: int = 18, enhance: dict | None = None,
               captions: list[tuple[float, float, str]] | None = None, padding: float = 0.0) -> dict:
        """audio: "original", "mute", None (drop), or a path to a redacted audio file."""
        info = self.info
        out_path = Path(out_path)
        cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{info.width}x{info.height}", "-r", f"{info.fps:.6f}", "-i", "-"]
        audio_src = None
        if audio == "original" and info.has_audio:
            audio_src = str(self.path)
        elif audio not in (None, "original", "mute") and Path(str(audio)).exists():
            audio_src = str(audio)
        if audio_src:
            cmd += ["-i", audio_src, "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac", "-b:a", "160k", "-shortest"]
        else:
            cmd += ["-map", "0:v:0"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
                "-map_metadata", "-1", "-map_chapters", "-1", "-metadata", "title=", "-movflags", "+faststart",
                str(out_path)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        cap = cv2.VideoCapture(str(self.path))
        enabled = [t for t in self.tracks if t.enabled]
        f = 0
        n_boxes = 0
        try:
            while True:
                ok, img = cap.read()
                if not ok:
                    break
                if enhance:
                    from .effects import enhance_frame
                    img = enhance_frame(img, **enhance)
                for t in enabled:
                    b = t.boxes.get(f)
                    if b is not None:
                        eff = getattr(t, "effect", None) or effect
                        shape = getattr(t, "shape", None) or ("ellipse" if t.label in ("face", "head") and
                                                              eff in ("blur", "pixelate") else "rect")
                        if t.label == "full_frame":
                            b, shape = (0, 0, info.width, info.height), "rect"
                        apply_effect(img, b[0] - padding, b[1] - padding, b[2] + padding, b[3] + padding,
                                     effect=eff, shape=shape)
                        n_boxes += 1
                if captions:
                    _burn_caption(img, captions, f / max(info.fps, 1e-6))
                proc.stdin.write(img.tobytes())
                f += 1
                if progress and f % 15 == 0:
                    progress(f, info.frames)
        finally:
            cap.release()
            proc.stdin.close()
            err = proc.stderr.read().decode("utf-8", "ignore")
            proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {err[-500:]}")
        report = {"frames": f, "boxes_drawn": n_boxes, "tracks": len(enabled), "metadata_removed": True,
                  "audio": "redacted" if audio_src and audio_src != str(self.path) else
                  ("original" if audio_src else "none")}
        if verify:
            report["verification"] = verify_video(out_path, self.tracks, original=self.path)
        return report


def _burn_caption(img: np.ndarray, cues: list[tuple[float, float, str]], t: float) -> None:
    """Draw the (already redacted) caption for time ``t`` near the bottom of the frame."""
    text = next((c for a, b, c in cues if a <= t <= b), None)
    if not text:
        return
    h, w = img.shape[:2]
    scale = max(0.5, w / 1400)
    thick = max(1, int(round(scale * 2)))
    words, lines, cur = text.split(), [], ""
    for wd in words:  # wrap to the frame width
        trial = (cur + " " + wd).strip()
        if cv2.getTextSize(trial, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)[0][0] > w * 0.9 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = trial
    lines.append(cur)
    lh = int(cv2.getTextSize("Ag", cv2.FONT_HERSHEY_SIMPLEX, scale, thick)[0][1] * 1.8)
    y = h - int(h * 0.06) - lh * (len(lines) - 1)
    for ln in lines[-3:]:
        tw = cv2.getTextSize(ln, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)[0][0]
        x = (w - tw) // 2
        cv2.rectangle(img, (x - 8, y - lh + 6), (x + tw + 8, y + 10), (0, 0, 0), -1)
        cv2.putText(img, ln, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick, cv2.LINE_AA)
        y += lh


def verify_video(path: str | Path, tracks: list[Track], sample_every: int = 5, max_samples: int = 600,
                 original: str | Path | None = None) -> dict:
    """Re-detect faces/plates on output frames. A confident detection outside every redaction box is a leak
    — unless the user deliberately kept that track visible."""
    info = probe(path)
    det = get_detector()
    all_tracks = list(tracks)
    step = max(sample_every, info.frames // max_samples if info.frames else 1)
    cap = cv2.VideoCapture(str(path))
    orig_cap = cv2.VideoCapture(str(original)) if original else None
    issues = []
    artifacts = 0
    f = 0
    checked = 0
    frames, idx, origs = [], [], []

    def check(batch, ids, orig_batch):
        nonlocal checked, artifacts
        orig_res = det.detect_batch(orig_batch, {"face", "license_plate"}, use_yunet=True) if orig_batch else None
        for n_, (k, res) in enumerate(zip(ids, det.detect_batch(batch, {"face", "license_plate"}, use_yunet=True))):
            checked += 1
            boxes = [t.boxes[j] for t in all_tracks for j in (k - 1, k, k + 1) if j in t.boxes]
            for vb in res:
                if vb.score < 0.5:
                    continue
                # a detection mostly over redacted/kept regions is the detector reacting to the blur itself
                if covered_fraction((vb.x0, vb.y0, vb.x1, vb.y1), boxes, info.width, info.height) >= 0.3:
                    continue
                # redaction cannot create a face: a real leak is also present in the original frame
                if orig_res is not None and not any(vb.iou(o) > 0.25 for o in orig_res[n_] if o.label == vb.label):
                    artifacts += 1
                    continue
                if True:
                    issues.append({"type": f"{vb.label}_visible", "frame": k, "time": round(k / info.fps, 2),
                                   "score": round(vb.score, 2)})

    while True:
        ok, img = cap.read()
        if not ok:
            break
        orig_img = None
        if orig_cap is not None:
            ok2, orig_img = orig_cap.read()
            if not ok2:
                orig_img = None
        if f % step == 0:
            frames.append(img)
            idx.append(f)
            if orig_img is not None:
                origs.append(orig_img)
            if len(frames) == 8:
                check(frames, idx, origs if len(origs) == len(frames) else None)
                frames, idx, origs = [], [], []
        f += 1
    if frames:
        check(frames, idx, origs if len(origs) == len(frames) else None)
    cap.release()
    if orig_cap is not None:
        orig_cap.release()
    return {"passed": not issues, "issues": issues[:200], "frames_checked": checked,
            "leak_frames": len({i["frame"] for i in issues}), "detector_artifacts_ignored": artifacts}


def covered_fraction(box: tuple, cover: list[tuple], w: int, h: int) -> float:
    """Fraction of `box` (clipped to the frame) covered by the union of `cover` boxes."""
    x0, y0, x1, y1 = max(0, int(box[0])), max(0, int(box[1])), min(w, int(box[2])), min(h, int(box[3]))
    if x1 <= x0 or y1 <= y0:
        return 1.0
    mask = np.zeros((y1 - y0, x1 - x0), bool)
    for c in cover:
        cx0, cy0 = max(x0, int(c[0])), max(y0, int(c[1]))
        cx1, cy1 = min(x1, int(np.ceil(c[2]))), min(y1, int(np.ceil(c[3])))
        if cx1 > cx0 and cy1 > cy0:
            mask[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0] = True
    return float(mask.mean())


def _inside(cx: float, cy: float, b: tuple) -> bool:
    return b[0] <= cx <= b[2] and b[1] <= cy <= b[3]


def extract_audio(video: str | Path, out_wav: str | Path, sr: int | None = None) -> Path:
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn", "-acodec", "pcm_s16le"]
    if sr:
        cmd += ["-ar", str(sr)]
    cmd.append(str(out_wav))
    subprocess.run(cmd, check=True)
    return Path(out_wav)


def save_tracks(tracks: list[Track], path: str | Path) -> None:
    Path(path).write_text(json.dumps([t.to_dict() for t in tracks]))


def load_tracks(path: str | Path) -> list[Track]:
    return [Track.from_dict(d) for d in json.loads(Path(path).read_text())]
