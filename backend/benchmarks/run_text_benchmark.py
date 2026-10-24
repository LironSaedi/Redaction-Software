"""Text-detection accuracy benchmark on the synthetic PI corpus.

    python benchmarks/run_text_benchmark.py --cases 6 --profile standard
    python benchmarks/run_text_benchmark.py --cases 3 --no-ml          # rules only
    python benchmarks/run_text_benchmark.py --gliner knowledgator-gliner-pii-base --spacy en_core_web_lg
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--profile", default="standard")
    ap.add_argument("--no-ml", action="store_true")
    ap.add_argument("--no-gliner", action="store_true")
    ap.add_argument("--no-spacy", action="store_true")
    ap.add_argument("--gliner", default=None)
    ap.add_argument("--spacy", default=None)
    ap.add_argument("--show", type=int, default=25, help="misses / false positives to print")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    from obscura.config import settings
    if args.gliner is not None:
        settings.gliner_model = args.gliner
    if args.spacy is not None:
        settings.spacy_model = args.spacy
    from obscura.detection.text.engine import AnalyzeOptions, TextAnalyzer
    from obscura.detection.text.entities import entities_for_profile
    from tests.accuracy.evaluate import evaluate
    from tests.corpus.templates import case_file

    docs = []
    for i in range(args.cases):
        docs += [d.to_dict() for d in case_file(args.seed + i, scale=args.scale)]
    enabled = entities_for_profile(args.profile)
    opts = AnalyzeOptions(profile=args.profile, use_spacy=not (args.no_ml or args.no_spacy),
                          use_gliner=not (args.no_ml or args.no_gliner), include_suggestions=False)
    an = TextAnalyzer()
    # warm-up so model load time is excluded from throughput
    an.analyze("Warm up text for John Smith at 1 Main St.", opts)
    t0 = time.perf_counter()
    preds = [an.analyze(d["text"], opts) for d in docs]
    dt = time.perf_counter() - t0
    rep = evaluate(docs, preds, enabled)
    chars = sum(len(d["text"]) for d in docs)
    pages = sum(d["text"].count("\f") + 1 for d in docs)
    print(f"\nprofile={args.profile}  spacy={settings.spacy_model if opts.use_spacy else '-'}  "
          f"gliner={settings.gliner_model if opts.use_gliner else '-'}")
    print(f"{len(docs)} documents, {pages} pages, {chars:,} chars, {dt:.1f}s ({pages / dt:.1f} pages/s)\n")
    print(rep.table())
    misses = [m | {"entity": e} for e, st in rep.per_type.items() for m in st.misses]
    print(f"\nMISSES ({len(misses)}):")
    for m in misses[:args.show]:
        print(f"  [{m['entity']}] {m['value']!r} cov={m['coverage']}  …{m['context']}…")
    print(f"\nFALSE POSITIVES ({len(rep.false_pos)}) by entity:", dict(Counter(f["entity"] for f in rep.false_pos)))
    for f in rep.false_pos[:args.show]:
        print(f"  [{f['entity']} {f['score']} {f['source']}] {f['text']!r}  …{f['context']}…")
    print(f"\nHARD-NEGATIVE HITS ({len(rep.negative_hits)}):", dict(Counter(n["kind"] for n in rep.negative_hits)))
    for n in rep.negative_hits[:args.show]:
        print(f"  {n}")
    if args.json:
        Path(args.json).write_text(json.dumps({
            "profile": args.profile, "recall": rep.recall, "precision": rep.precision, "f1": rep.f1,
            "pages": pages, "seconds": dt, "per_type": {k: {"gold": v.gold, "caught": v.caught, "typed": v.typed}
                                                        for k, v in rep.per_type.items()},
            "misses": misses, "false_positives": rep.false_pos, "negative_hits": rep.negative_hits}, indent=1))


if __name__ == "__main__":
    main()
