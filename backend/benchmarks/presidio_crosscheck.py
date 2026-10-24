"""Double-check Obscura against Microsoft Presidio on the held-out documents.

    python benchmarks/presidio_crosscheck.py --split devall      # lists what Presidio caught that Obscura missed
    python benchmarks/presidio_crosscheck.py --split test        # sealed split: totals only

Reports Presidio on its own, Obscura on its own, and Obscura + Presidio's extra findings (what the "second
opinion" would add), with per-recognizer counts of useful vs. noisy extra findings.
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="devall", choices=["dev", "dev2", "devall", "test", "fin", "fintest", "all"])
    ap.add_argument("--profile", default="standard")
    ap.add_argument("--min-score", type=float, default=0.4)
    ap.add_argument("--show", type=int, default=80)
    args = ap.parse_args()
    sealed = args.split in ("test", "fintest", "all")
    from obscura.detection.text import second_opinion as so
    from obscura.detection.text.engine import AnalyzeOptions, TextAnalyzer
    from obscura.detection.text.entities import entities_for_profile
    from tests.accuracy.evaluate import _cover, evaluate
    from tests.heldout.load import load_all

    docs = load_all(args.split)
    enabled = entities_for_profile(args.profile)
    opts = AnalyzeOptions(profile=args.profile, include_suggestions=False)
    an = TextAnalyzer()
    an.analyze("warm up John Smith 1 Main St", opts)
    print(so.status()["version"], "recognizers loaded")
    t0 = time.perf_counter()
    ours, theirs, extra = [], [], []
    t_pres = 0.0
    for d in docs:
        o = an.analyze(d["text"], opts)
        t1 = time.perf_counter()
        p = so.analyze(d["text"], min_score=args.min_score)
        t_pres += time.perf_counter() - t1
        for sp in p:
            sp.meta["selected"] = True
        ours.append(o)
        theirs.append(p)
        iv = [(s.start, s.end) for s in o if s.meta.get("selected", True)]
        extra.append([sp for sp in p if not so._covered(sp, iv, d["text"])])
    dt = time.perf_counter() - t0
    r_o, r_p = evaluate(docs, ours, enabled), evaluate(docs, theirs, enabled)
    r_u = evaluate(docs, [o + x for o, x in zip(ours, extra)], enabled)
    print(f"\n{len(docs)} documents ({args.split}), {dt:.0f}s total, Presidio {t_pres:.0f}s")
    print(f"{'':<26}{'recall':>9}{'precision':>11}")
    for name, r in (("Presidio alone", r_p), ("Obscura", r_o), ("Obscura + Presidio extras", r_u)):
        print(f"{name:<26}{r.recall:>9.2%}{r.precision:>11.2%}")

    # extra findings: useful (overlaps a gold value Obscura missed) vs noise, by recognizer
    useful, noise = Counter(), Counter()
    rescued = []
    for d, o, x in zip(docs, ours, extra):
        gold = [g for g in d["gold"] if not g["optional"] and g["entity"] in enabled]
        oiv = [(s.start, s.end) for s in o if s.meta.get("selected", True)]
        all_gold_iv = [(g["start"], g["end"]) for g in d["gold"]]
        for sp in x:
            rec = sp.source.split(":", 1)[1] + "/" + sp.meta["presidio_entity"]
            (useful if _cover(all_gold_iv, sp.start, sp.end, d["text"]) >= 0.5 else noise)[rec] += 1
        xiv = [(s.start, s.end) for s in x]
        for g in gold:
            if _cover(oiv, g["start"], g["end"], d["text"]) < 0.9 and \
                    _cover(oiv + xiv, g["start"], g["end"], d["text"]) >= 0.9:
                rescued.append((d["kind"], g["entity"], g["value"]))
    print(f"\nObscura misses that Presidio caught: {len(rescued)}")
    print(f"extra Presidio findings: {sum(useful.values())} on real PII, {sum(noise.values())} not PII")
    print(f"\n{'recognizer/entity':<44}{'useful':>8}{'noise':>8}")
    for rec in sorted(set(useful) | set(noise), key=lambda k: -(useful[k] + noise[k])):
        print(f"{rec:<44}{useful[rec]:>8}{noise[rec]:>8}")
    if sealed:
        print("\n(sealed split: values withheld)")
        return
    print("\nRESCUED (Obscura missed, Presidio caught):")
    for kind, ent, val in rescued[:args.show]:
        print(f"  [{ent}] {kind}: {val!r}")
    by_rec = defaultdict(list)
    for d, x in zip(docs, extra):
        all_gold_iv = [(g["start"], g["end"]) for g in d["gold"]]
        for sp in x:
            if _cover(all_gold_iv, sp.start, sp.end, d["text"]) < 0.5:
                by_rec[sp.source].append(f"{sp.text!r}")
    print("\nNOISE SAMPLES:")
    for rec, vals in sorted(by_rec.items(), key=lambda kv: -len(kv[1])):
        print(f"  {rec} ({len(vals)}): {', '.join(vals[:12])}")


if __name__ == "__main__":
    main()
