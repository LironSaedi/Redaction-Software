"""Parse the independently written held-out documents: inline ``[[TYPE|value]]`` markup → text + gold."""
from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent / "docs"
_MARK = re.compile(r"\[\[([A-Z_]+)(\?)?(?:\s+(MINOR))?(\?)?\|(.*?)\]\]", re.S)
ALWAYS_OPTIONAL = {"ORGANIZATION", "MONEY", "LOCATION"}


def parse(raw: str) -> dict:
    text_parts, gold = [], []
    pos = 0
    out_len = 0
    for m in _MARK.finditer(raw):
        chunk = raw[pos:m.start()]
        text_parts.append(chunk)
        out_len += len(chunk)
        ent, value = m.group(1), m.group(5)
        optional = bool(m.group(2) or m.group(4)) or ent in ALWAYS_OPTIONAL
        gold.append({"start": out_len, "end": out_len + len(value), "entity": ent, "value": value,
                     "optional": optional, "minor": bool(m.group(3))})
        text_parts.append(value)
        out_len += len(value)
        pos = m.end()
    text_parts.append(raw[pos:])
    return {"text": "".join(text_parts), "gold": gold, "negatives": []}


DOCS2 = Path(__file__).resolve().parent / "docs2"  # second development batch (101+), written by a separate author
DEV_MAX = 38  # documents 01–38: development (errors may be inspected); 39–56: sealed test (aggregate only)


DOCS3 = Path(__file__).resolve().parent / "docs3"                # financial documents, development (201+)
DOCS3_SEALED = Path(__file__).resolve().parent / "docs3_sealed"  # financial documents, sealed (251+): totals only
DOCS4 = Path(__file__).resolve().parent / "docs4"                # indirect identifiers, development (301+)


def load_all(split: str = "all") -> list[dict]:
    """Splits: dev (01–38), dev2 (101+), devall (both), test (39–56, sealed), fin (201+, financial),
    fintest (251+, financial, sealed), ind (301+, dense in indirect identifiers), all (everything)."""
    docs = []
    files = sorted(DOCS.glob("*.txt")) + (sorted(DOCS2.glob("*.txt")) if DOCS2.exists() else [])
    if split in ("fin", "all"):
        files += sorted(DOCS3.glob("*.txt")) if DOCS3.exists() else []
    if split in ("fintest", "all"):
        files += sorted(DOCS3_SEALED.glob("*.txt")) if DOCS3_SEALED.exists() else []
    if split in ("ind", "all"):
        files += sorted(DOCS4.glob("*.txt")) if DOCS4.exists() else []
    for p in files:
        n = int(p.stem.split("_")[0])
        part = "ind" if n > 300 else ("fintest" if n > 250 else "fin") if n > 200 else \
            ("dev2" if n > 100 else ("dev" if n <= DEV_MAX else "test"))
        if split in ("dev", "dev2", "test", "fin", "fintest", "ind") and part != split or split == "devall" and part in ("test",):
            continue
        if split == "devall" and part in ("fin", "fintest"):
            continue
        d = parse(p.read_text(encoding="utf-8"))
        d["kind"] = p.stem
        d["title"] = p.stem
        docs.append(d)
    return docs
