"""Local visual detectors: faces, license plates, people, vehicles, screens, documents.

Recall is what matters for redaction (a missed face in one frame is a disclosure), so:

* faces come from an *ensemble* — YOLOv11m-face and OpenCV YuNet — merged by union, never by vote;
* large frames are also scanned in overlapping tiles so distant/small faces are found;
* a head-region fallback covers people seen from behind or in profile (no detectable face);
* every box is padded before redaction.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

from ... import config  # noqa: F401
from ...config import disable_ultralytics_network, torch_device, vision_model

log = logging.getLogger("obscura.vision")

COCO_MAP = {0: "person", 2: "vehicle", 3: "vehicle", 5: "vehicle", 7: "vehicle", 1: "vehicle",
            62: "screen", 63: "screen", 67: "screen", 73: "document", 65: "screen"}
VISUAL_CLASSES = {
    "face": "Faces", "head": "Heads (no visible face)", "license_plate": "License plates", "person": "People (full body)",
    "vehicle": "Vehicles", "screen": "Screens / monitors / phones", "document": "Papers / notepads / books",
    "text": "Visible text containing PII",
}


@dataclass
class VBox:
    x0: float
    y0: float
    x1: float
    y1: float
    score: float
    label: str
    source: str

    def __post_init__(self):  # detectors hand back numpy scalars; keep plain floats everywhere downstream
        self.x0, self.y0, self.x1, self.y1, self.score = (float(self.x0), float(self.y0), float(self.x1),
                                                          float(self.y1), float(self.score))

    def iou(self, o: "VBox") -> float:
        ix0, iy0, ix1, iy1 = max(self.x0, o.x0), max(self.y0, o.y0), min(self.x1, o.x1), min(self.y1, o.y1)
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        if inter <= 0:
            return 0.0
        return inter / (self.area() + o.area() - inter)

    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)

    def padded(self, frac: float, w: int, h: int) -> "VBox":
        bw, bh = self.x1 - self.x0, self.y1 - self.y0
        return VBox(max(0, self.x0 - bw * frac), max(0, self.y0 - bh * frac), min(w, self.x1 + bw * frac),
                    min(h, self.y1 + bh * frac), self.score, self.label, self.source)


from ..ml_lock import TORCH_LOCK as _lock  # shared with the text models
_models: dict[str, object] = {}


def _yolo(name: str):
    with _lock:
        if name not in _models:
            disable_ultralytics_network()
            from ultralytics import YOLO
            path = vision_model(name)
            if not path.exists():
                raise FileNotFoundError(f"vision model missing: {path} (run scripts/download_models.py)")
            _models[name] = YOLO(str(path))
        return _models[name]


def _yunet(w: int, h: int):
    import cv2
    with _lock:
        if "yunet" not in _models:
            path = vision_model("face_yunet_2023mar.onnx")
            _models["yunet"] = cv2.FaceDetectorYN.create(str(path), "", (320, 320), score_threshold=0.55,
                                                         nms_threshold=0.3, top_k=5000)
        det = _models["yunet"]
    return det


def _device() -> str:
    d = torch_device()
    return d if d in ("cuda", "mps") else "cpu"


def merge_union(boxes: list[VBox], iou_thr: float = 0.4) -> list[VBox]:
    """Merge overlapping detections of the same label into their *union* (larger is safer)."""
    out: list[VBox] = []
    for b in sorted(boxes, key=lambda b: -b.score):
        for o in out:
            if o.label == b.label and (o.iou(b) > iou_thr or _contains(o, b) or _contains(b, o)):
                o.x0, o.y0, o.x1, o.y1 = min(o.x0, b.x0), min(o.y0, b.y0), max(o.x1, b.x1), max(o.y1, b.y1)
                o.score = max(o.score, b.score)
                if b.source not in o.source:
                    o.source += "+" + b.source
                break
        else:
            out.append(VBox(b.x0, b.y0, b.x1, b.y1, b.score, b.label, b.source))
    return out


def _contains(a: VBox, b: VBox) -> bool:
    inter = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0)) * max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    return b.area() > 0 and inter / b.area() > 0.8


class VisionDetector:
    """Thread-safe wrapper; models load lazily on first use."""

    def __init__(self, face_conf: float = 0.25, plate_conf: float = 0.25, obj_conf: float = 0.3,
                 imgsz: int = 1280, tiles: bool = True):
        self.face_conf, self.plate_conf, self.obj_conf = face_conf, plate_conf, obj_conf
        self.imgsz = imgsz
        self.tiles = tiles

    # ---------------------------------------------------------------------------------------
    def faces(self, img: np.ndarray, fast: bool = False) -> list[VBox]:
        """img: BGR uint8."""
        h, w = img.shape[:2]
        out: list[VBox] = []
        model = _yolo("face_yolov11m.pt")
        crops = [(0, 0, img)]
        if self.tiles and not fast and max(w, h) >= 1400:
            crops += _tiles(img, 2 if max(w, h) < 2800 else 3)
        for ox, oy, crop in crops:
            res = model.predict(crop, imgsz=self.imgsz if (ox, oy) == (0, 0) else 960, conf=self.face_conf,
                                device=_device(), verbose=False)[0]
            for (x0, y0, x1, y1), s in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy()):
                out.append(VBox(x0 + ox, y0 + oy, x1 + ox, y1 + oy, float(s), "face", "yolo-face"))
        if not fast:
            out += self._yunet_faces(img)
        return merge_union(out)

    def _yunet_faces(self, img: np.ndarray) -> list[VBox]:
        import cv2
        h, w = img.shape[:2]
        scale = 1.0
        if max(h, w) > 1920:
            scale = 1920 / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))
        det = _yunet(img.shape[1], img.shape[0])
        with _lock:
            det.setInputSize((img.shape[1], img.shape[0]))
            _, faces = det.detect(img)
        out = []
        if faces is not None:
            for f in faces:
                x, y, fw, fh, s = f[0], f[1], f[2], f[3], f[-1]
                out.append(VBox(x / scale, y / scale, (x + fw) / scale, (y + fh) / scale, float(s), "face", "yunet"))
        return out

    def plates(self, img: np.ndarray) -> list[VBox]:
        model = _yolo("plate_yolov11m.pt")
        res = model.predict(img, imgsz=self.imgsz, conf=self.plate_conf, device=_device(), verbose=False)[0]
        return merge_union([VBox(*map(float, b), float(s), "license_plate", "yolo-plate")
                            for b, s in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy())])

    def objects(self, img: np.ndarray, want: set[str]) -> list[VBox]:
        model = _yolo("yolo11m.pt")
        classes = [k for k, v in COCO_MAP.items() if v in want or (v == "person" and "head" in want)]
        if not classes:
            return []
        res = model.predict(img, imgsz=self.imgsz, conf=self.obj_conf, classes=classes, device=_device(),
                            verbose=False)[0]
        out = []
        for b, s, c in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(), res.boxes.cls.cpu().numpy()):
            out.append(VBox(*map(float, b), float(s), COCO_MAP[int(c)], "yolo11"))
        return out

    def detect_batch(self, frames: list[np.ndarray], classes: set[str], use_yunet: bool = True,
                     imgsz: int | None = None) -> list[list[VBox]]:
        """Video path: batched YOLO on the GPU, YuNet per frame. Returns detections per frame."""
        out: list[list[VBox]] = [[] for _ in frames]
        sz = imgsz or self.imgsz
        dev = _device()
        if "face" in classes or "head" in classes:
            res = _yolo("face_yolov11m.pt").predict(frames, imgsz=sz, conf=self.face_conf, device=dev, verbose=False)
            for i, r in enumerate(res):
                for b, sc in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()):
                    out[i].append(VBox(*map(float, b), float(sc), "face", "yolo-face"))
            if use_yunet:
                for i, fr in enumerate(frames):
                    out[i] += self._yunet_faces(fr)
        if "license_plate" in classes:
            res = _yolo("plate_yolov11m.pt").predict(frames, imgsz=sz, conf=self.plate_conf, device=dev, verbose=False)
            for i, r in enumerate(res):
                for b, sc in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()):
                    out[i].append(VBox(*map(float, b), float(sc), "license_plate", "yolo-plate"))
        obj_want = classes & {"person", "vehicle", "screen", "document", "head"}
        if obj_want:
            cls = [k for k, v in COCO_MAP.items() if v in obj_want or (v == "person" and "head" in obj_want)]
            res = _yolo("yolo11m.pt").predict(frames, imgsz=sz, conf=self.obj_conf, classes=cls, device=dev,
                                              verbose=False)
            for i, r in enumerate(res):
                objs = [VBox(*map(float, b), float(sc), COCO_MAP[int(c)], "yolo11") for b, sc, c in
                        zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy())]
                if "head" in classes:
                    out[i] += heads_without_faces([o for o in objs if o.label == "person"],
                                                  [o for o in out[i] if o.label == "face"])
                out[i] += [o for o in objs if o.label in classes]
        return [merge_union(o) for o in out]

    def detect(self, img: np.ndarray, classes: set[str], fast: bool = False) -> list[VBox]:
        h, w = img.shape[:2]
        out: list[VBox] = []
        faces: list[VBox] = []
        if "face" in classes or "head" in classes:
            faces = self.faces(img, fast=fast)
            if "face" in classes:
                out += faces
        if "license_plate" in classes:
            out += self.plates(img)
        obj_want = classes & {"person", "vehicle", "screen", "document", "head"}
        if obj_want:
            objs = self.objects(img, obj_want)
            people = [o for o in objs if o.label == "person"]
            if "head" in classes:
                out += heads_without_faces(people, faces)
            out += [o for o in objs if o.label in classes]
        return out


def heads_without_faces(people: list[VBox], faces: list[VBox]) -> list[VBox]:
    """Head region for every person whose upper body contains no detected face (turned away, profile,
    motion blur). Head ≈ top 22% of the person box, centred, ~55% of its width."""
    out = []
    for p in people:
        pw, ph = p.x1 - p.x0, p.y1 - p.y0
        if ph < 24:
            continue
        head = VBox(p.x0 + pw * 0.2, p.y0, p.x1 - pw * 0.2, p.y0 + ph * 0.24, p.score * 0.9, "head", "person-head")
        if any(_overlap_frac(f, head) > 0.3 for f in faces):
            continue
        # a face anywhere in the upper half of the person box means the face detector already has them
        if any(p.x0 <= (f.x0 + f.x1) / 2 <= p.x1 and p.y0 <= (f.y0 + f.y1) / 2 <= p.y0 + ph * 0.55 for f in faces):
            continue
        out.append(head)
    return out


def _overlap_frac(a: VBox, b: VBox) -> float:
    inter = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0)) * max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    return inter / a.area() if a.area() else 0.0


def _tiles(img: np.ndarray, n: int) -> list[tuple[int, int, np.ndarray]]:
    h, w = img.shape[:2]
    tw, th = int(w / n * 1.25), int(h / n * 1.25)
    out = []
    for i in range(n):
        for j in range(n):
            x0 = min(max(0, int(i * w / n - tw * 0.1)), max(0, w - tw))
            y0 = min(max(0, int(j * h / n - th * 0.1)), max(0, h - th))
            out.append((x0, y0, img[y0:y0 + th, x0:x0 + tw]))
    return out


_DET: VisionDetector | None = None


class _Locked:
    """Every call into the detector holds the process-wide model lock."""

    def __init__(self, det: VisionDetector):
        self._det = det

    def __getattr__(self, name):
        attr = getattr(self._det, name)
        if not callable(attr):
            return attr

        def call(*a, **kw):
            with _lock:
                return attr(*a, **kw)
        return call


def get_detector() -> VisionDetector:
    global _DET
    if _DET is None:
        with _lock:
            if _DET is None:
                _DET = _Locked(VisionDetector())
    return _DET
