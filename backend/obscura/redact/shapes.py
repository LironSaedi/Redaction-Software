"""Redaction shapes beyond rectangles: ellipses and free polygons drawn by a reviewer.

PDF redaction annotations are rectangles, so a shape becomes a stack of thin horizontal strips that follow
its outline (everything inside is removed; the over-cover at the edges is at most one strip high). Pixel
formats (images, video frames) use an exact mask.
"""
from __future__ import annotations

import math

import numpy as np


def polygon_strips(points: list[tuple[float, float]], step: float = 1.5) -> list[tuple[float, float, float, float]]:
    """Cover a polygon (page coordinates) with horizontal strips ``step`` high."""
    if len(points) < 3:
        return []
    ys = [p[1] for p in points]
    y, ymax = min(ys), max(ys)
    out = []
    n = len(points)
    while y < ymax:
        y1 = min(ymax, y + step)
        xs = []
        for yy in (y, (y + y1) / 2, y1):  # sample the strip at three heights so nothing pokes out
            for i in range(n):
                (ax, ay), (bx, by) = points[i], points[(i + 1) % n]
                if (ay <= yy < by) or (by <= yy < ay):
                    xs.append(ax + (yy - ay) * (bx - ax) / (by - ay))
        if len(xs) >= 2:
            out.append((min(xs), y, max(xs), y1))
        y = y1
    return out


def ellipse_points(x0: float, y0: float, x1: float, y1: float, n: int = 48) -> list[tuple[float, float]]:
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    return [(cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n)) for k in range(n)]


def polygon_mask(shape: tuple[int, int], points: list[tuple[float, float]]) -> np.ndarray:
    import cv2
    mask = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(mask, [np.array([[int(round(x)), int(round(y))] for x, y in points], np.int32)], 255)
    return mask.astype(bool)
