"""Document utilities: merge, split, re-order / rotate / delete pages, Bates-number a set."""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz


def merge(paths: list[Path], out: Path) -> Path:
    dst = fitz.open()
    for p in paths:
        with fitz.open(str(p)) as src:
            dst.insert_pdf(src)
    dst.save(str(out), garbage=4, deflate=True)
    return out


def split(path: Path, ranges: list[tuple[int, int]], out_dir: Path, stem: str) -> list[Path]:
    """ranges are 1-based inclusive page ranges."""
    outs = []
    with fitz.open(str(path)) as src:
        for a, b in ranges:
            a, b = max(1, a), min(len(src), b)
            if a > b:
                continue
            d = fitz.open()
            d.insert_pdf(src, from_page=a - 1, to_page=b - 1)
            p = out_dir / f"{stem}_p{a}-{b}.pdf"
            d.save(str(p), garbage=4, deflate=True)
            outs.append(p)
    return outs


def organize(path: Path, out: Path, order: list[int] | None = None, rotate: dict[int, int] | None = None,
             delete: list[int] | None = None) -> Path:
    """order: new page order (0-based indices); rotate: {page: degrees}; delete: pages to drop."""
    with fitz.open(str(path)) as doc:
        keep = [i for i in (order if order else range(len(doc))) if i not in set(delete or [])]
        doc.select(keep)
        for old_idx, deg in (rotate or {}).items():
            if int(old_idx) in keep:
                page = doc[keep.index(int(old_idx))]
                page.set_rotation((page.rotation + int(deg)) % 360)
        doc.save(str(out), garbage=4, deflate=True)
    return out


def bates(path: Path, out: Path, prefix: str, start: int = 1, digits: int = 6, position: str = "br") -> tuple[Path, int]:
    with fitz.open(str(path)) as doc:
        for k, page in enumerate(doc):
            stamp = f"{prefix}{start + k:0{digits}d}"
            r = page.rect
            w = fitz.get_text_length(stamp, fontname="helv", fontsize=9)
            x = r.x1 - 14 - w if position.endswith("r") else r.x0 + 14
            y = r.y1 - 12 if position.startswith("b") else r.y0 + 20
            page.insert_text(fitz.Point(x, y), stamp, fontsize=9, fontname="helv")
        doc.save(str(out), garbage=4, deflate=True)
        return out, start + len(doc)
