"""Data model shared by every document handler (PDF, image, office, email)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class Box:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float

    def to_dict(self) -> dict:
        return {"page": int(self.page), "x0": round(float(self.x0), 2), "y0": round(float(self.y0), 2),
                "x1": round(float(self.x1), 2), "y1": round(float(self.y1), 2)}

    @staticmethod
    def from_dict(d: dict) -> "Box":
        return Box(int(d["page"]), float(d["x0"]), float(d["y0"]), float(d["x1"]), float(d["y1"]))

    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


@dataclass
class Detection:
    entity: str
    text: str
    score: float
    source: str
    boxes: list[Box]
    page: int = 0
    start: int = -1          # offset in the page text (-1 for visual / manual boxes)
    end: int = -1
    explanation: str = ""
    selected: bool = True
    exemption: str = ""
    partial: str | None = None
    kind: str = "text"       # text | visual | manual | template
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "entity": self.entity, "text": self.text, "score": round(float(self.score), 4),
                "source": self.source, "boxes": [b.to_dict() for b in self.boxes], "page": self.page,
                "start": self.start, "end": self.end, "explanation": self.explanation, "selected": self.selected,
                "exemption": self.exemption, "partial": self.partial, "kind": self.kind, "meta": self.meta}

    @staticmethod
    def from_dict(d: dict) -> "Detection":
        return Detection(entity=d["entity"], text=d.get("text", ""), score=float(d.get("score", 1)),
                         source=d.get("source", "manual"), boxes=[Box.from_dict(b) for b in d.get("boxes", [])],
                         page=int(d.get("page", 0)), start=int(d.get("start", -1)), end=int(d.get("end", -1)),
                         explanation=d.get("explanation", ""), selected=bool(d.get("selected", True)),
                         exemption=d.get("exemption", ""), partial=d.get("partial"), kind=d.get("kind", "text"),
                         id=d.get("id") or uuid.uuid4().hex[:12], meta=d.get("meta", {}))


@dataclass
class PageText:
    """Text of one page plus geometry for every character (None for synthetic separators)."""
    page: int
    text: str
    boxes: list[tuple[float, float, float, float] | None]
    lines: list[int]
    width: float
    height: float
    source: str = "native"  # native | ocr | hybrid
    ocr_conf: float | None = None


@dataclass
class RedactionStyle:
    fill: tuple[float, float, float] = (0, 0, 0)
    label: str = "none"           # none | entity | exemption | custom
    custom_text: str = "REDACTED"
    text_color: tuple[float, float, float] = (1, 1, 1)
    outline_only_preview: bool = False


@dataclass
class ExportOptions:
    style: RedactionStyle = field(default_factory=RedactionStyle)
    bates_prefix: str | None = None
    bates_start: int = 1
    bates_digits: int = 6
    watermark: str | None = None
    password: str | None = None
    flatten_to_image: bool = False   # rasterise every page after redaction (belt and braces)
    remove_metadata: bool = True
    verify: bool = True
    redaction_log: bool = True
    padding: float = 0.0             # extra margin around every box, in points
    marked_copy: bool = False        # review copy: outlines + labels, nothing removed (never for release)
