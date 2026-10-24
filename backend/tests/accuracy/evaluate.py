"""Redaction-accuracy scoring.

Metrics (computed per entity type and overall):

* **redaction recall** — a gold span counts as caught when >= 90% of its non-space characters are
  covered by *selected* predicted spans of any type. This is what matters legally: was it blacked out?
* **typed recall** — caught by a prediction whose entity is compatible with the gold type.
* **precision** — a selected prediction is a true positive when >= 50% of its characters overlap
  any gold span (optional gold included); otherwise it is over-redaction. Runs of masking characters
  inside a prediction ("***-**-7046", "XXXXXX8812") are not counted: annotators differ on whether the
  mask belongs to the value, and covering a mask hides nothing a reader could use.
* **negative hits** — selected predictions overlapping a deliberate hard negative (CPT codes, page
  numbers, statute citations…). These are the over-redactions that hurt document usability.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

COMPATIBLE = {
    "PERSON": {"PERSON", "MINOR", "SIGNATURE"},
    "ADDRESS": {"ADDRESS", "INDIRECT_LOCATION", "LOCATION", "ZIP_CODE"},
    "DATE_OF_BIRTH": {"DATE_OF_BIRTH", "DATE"},
    "DATE": {"DATE", "DATE_OF_BIRTH"},
    "MRN": {"MRN", "ID_NUMBER", "BANK_ACCOUNT", "HEALTH_PLAN_ID"},
    "HEALTH_PLAN_ID": {"HEALTH_PLAN_ID", "ID_NUMBER", "MRN", "MEDICARE_ID"},
    "LAW_ENFORCEMENT_ID": {"LAW_ENFORCEMENT_ID", "CASE_NUMBER", "ID_NUMBER"},
    "CASE_NUMBER": {"CASE_NUMBER", "LAW_ENFORCEMENT_ID", "ID_NUMBER"},
    "INDIRECT_ROLE": {"INDIRECT_ROLE"},
    "INDIRECT_LOCATION": {"INDIRECT_LOCATION", "ADDRESS", "LOCATION", "ORGANIZATION"},
    "EMPLOYER": {"EMPLOYER", "ORGANIZATION"},
    "AGE": {"AGE", "DEMOGRAPHIC"},
    "DEMOGRAPHIC": {"DEMOGRAPHIC", "AGE"},
    "BANK_ACCOUNT": {"BANK_ACCOUNT", "ID_NUMBER"},
    "USERNAME": {"USERNAME", "EMAIL"},
    "SSN": {"SSN", "ITIN"},
}


_MASK_RUN = re.compile(r"[Xx*•]{2,}")


def _cover_pred(intervals: list[tuple[int, int]], s: int, e: int, text: str) -> float:
    """Coverage of a prediction by gold, ignoring runs of mask characters when the prediction holds digits."""
    seg = text[s:e]
    if not any(c.isdigit() for c in seg):
        return _cover(intervals, s, e, text)
    skip = {s + i for m in _MASK_RUN.finditer(seg) for i in range(m.start(), m.end())}
    need = [i for i in range(s, e) if not text[i].isspace() and i not in skip]
    if not need:
        return 1.0
    hit = sum(1 for i in need if any(a <= i < b for a, b in intervals))
    return hit / len(need)


def _cover(intervals: list[tuple[int, int]], s: int, e: int, text: str) -> float:
    need = [i for i in range(s, e) if not text[i].isspace()]
    if not need:
        return 1.0
    covered = 0
    for i in need:
        for a, b in intervals:
            if a <= i < b:
                covered += 1
                break
    return covered / len(need)


@dataclass
class TypeStats:
    gold: int = 0
    caught: int = 0
    typed: int = 0
    misses: list = field(default_factory=list)


@dataclass
class Report:
    per_type: dict[str, TypeStats]
    predicted: int
    true_pos: int
    false_pos: list
    negative_hits: list
    docs: int
    chars: int

    @property
    def recall(self) -> float:
        g = sum(t.gold for t in self.per_type.values())
        return sum(t.caught for t in self.per_type.values()) / g if g else 1.0

    @property
    def precision(self) -> float:
        return self.true_pos / self.predicted if self.predicted else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def table(self) -> str:
        rows = [f"{'entity':<26}{'gold':>7}{'caught':>8}{'recall':>9}{'typed':>8}"]
        for ent, st in sorted(self.per_type.items(), key=lambda kv: -kv[1].gold):
            rec = st.caught / st.gold if st.gold else 1
            typ = st.typed / st.gold if st.gold else 1
            rows.append(f"{ent:<26}{st.gold:>7}{st.caught:>8}{rec:>9.2%}{typ:>8.1%}")
        rows.append("-" * 58)
        rows.append(f"{'REDACTION RECALL':<26}{'':>7}{'':>8}{self.recall:>9.3%}")
        rows.append(f"{'PRECISION':<26}{'':>7}{'':>8}{self.precision:>9.3%}   ({len(self.false_pos)} FP of {self.predicted})")
        rows.append(f"{'F1':<26}{'':>7}{'':>8}{self.f1:>9.3%}")
        rows.append(f"{'hard-negative hits':<26}{len(self.negative_hits):>7}")
        return "\n".join(rows)


def evaluate(docs: list[dict], predictions: list[list], enabled: set[str]) -> Report:
    per_type: dict[str, TypeStats] = defaultdict(TypeStats)
    predicted = tp = 0
    fps, neg_hits = [], []
    chars = 0
    for doc, preds in zip(docs, predictions):
        text = doc["text"]
        chars += len(text)
        sel = [p for p in preds if p.meta.get("selected", True)]
        all_iv = [(p.start, p.end) for p in sel]
        by_ent: dict[str, list] = defaultdict(list)
        for p in sel:
            by_ent[p.entity].append((p.start, p.end))
        for g in doc["gold"]:
            if g["optional"] or g["entity"] not in enabled:
                continue
            st = per_type[g["entity"]]
            st.gold += 1
            cov = _cover(all_iv, g["start"], g["end"], text)
            if cov >= 0.9:
                st.caught += 1
                comp = COMPATIBLE.get(g["entity"], {g["entity"]})
                comp_iv = [iv for e in comp for iv in by_ent.get(e, [])]
                if _cover(comp_iv, g["start"], g["end"], text) >= 0.9:
                    st.typed += 1
            else:
                ctx = text[max(0, g["start"] - 50):g["end"] + 30].replace("\n", "⏎")
                st.misses.append({"doc": doc["kind"], "value": g["value"], "coverage": round(cov, 2), "context": ctx})
        gold_iv = [(g["start"], g["end"]) for g in doc["gold"]]
        for p in sel:
            predicted += 1
            ov = _cover_pred(gold_iv, p.start, p.end, text)
            if ov >= 0.5:
                tp += 1
            else:
                ctx = text[max(0, p.start - 40):p.end + 25].replace("\n", "⏎")
                fps.append({"doc": doc["kind"], "entity": p.entity, "text": p.text, "score": round(p.score, 2),
                            "source": p.source, "context": ctx})
            for s, e, kind, val in ((n["start"], n["end"], n["kind"], n["value"]) for n in doc["negatives"]):
                if p.start < e and s < p.end:
                    neg_hits.append({"doc": doc["kind"], "negative": val, "kind": kind, "entity": p.entity,
                                     "pred": p.text, "source": p.source})
    return Report(dict(per_type), predicted, tp, fps, neg_hits, len(docs), chars)
