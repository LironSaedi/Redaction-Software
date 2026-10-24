"""Score the engine on the independent held-out documents (tests/heldout/docs/*.txt).

    python benchmarks/run_heldout.py                 # full ML ensemble, standard profile
    python benchmarks/run_heldout.py --no-ml --profile strict
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
    ap.add_argument("--profile", default="standard")
    ap.add_argument("--no-ml", action="store_true")
    ap.add_argument("--no-spacy", action="store_true")
    ap.add_argument("--no-gliner", action="store_true")
    ap.add_argument("--gliner", default=None)
    ap.add_argument("--spacy", default=None)
    ap.add_argument("--show", type=int, default=40)
    ap.add_argument("--json", default=None)
    ap.add_argument("--only", default=None, help="comma-separated substrings of document names (dev split only)")
    ap.add_argument("--cache-ml", action="store_true",
                    help="reuse spaCy / GLiNER results from earlier runs (they depend only on the text), so rule "
                         "changes can be measured in seconds")
    ap.add_argument("--split", default="dev", choices=["dev", "dev2", "devall", "test", "fin", "fintest", "ind", "all"],
                    help="dev: errors shown; test: sealed — only aggregate numbers are printed; "
                         "ind: indirect-identifier development set (docs4)")
    args = ap.parse_args()
    from obscura.config import settings
    if args.gliner is not None:
        settings.gliner_model = args.gliner
    if args.spacy is not None:
        settings.spacy_model = args.spacy
    if args.cache_ml:
        _install_ml_cache(settings)
    from obscura.detection.text.engine import AnalyzeOptions, TextAnalyzer
    from obscura.detection.text.entities import entities_for_profile
    from tests.accuracy.evaluate import evaluate
    from tests.heldout.load import load_all

    docs = load_all(args.split)
    if args.only and args.split in ("dev", "dev2", "devall", "fin", "ind"):
        keys = args.only.split(",")
        docs = [d for d in docs if any(k in d["kind"] for k in keys)]
    if not docs:
        print("no held-out documents found")
        return
    enabled = entities_for_profile(args.profile)
    opts = AnalyzeOptions(profile=args.profile, use_spacy=not (args.no_ml or args.no_spacy),
                          use_gliner=not (args.no_ml or args.no_gliner), include_suggestions=False)
    an = TextAnalyzer()
    an.analyze("warm up John Smith 1 Main St", opts)
    t0 = time.perf_counter()
    preds = [an.analyze(d["text"], opts) for d in docs]
    dt = time.perf_counter() - t0
    rep = evaluate(docs, preds, enabled)
    chars = sum(len(d["text"]) for d in docs)
    print(f"\nHELD-OUT  profile={args.profile}  spacy={settings.spacy_model if opts.use_spacy else '-'}  "
          f"gliner={settings.gliner_model if opts.use_gliner else '-'}")
    print(f"{len(docs)} documents, {chars:,} chars (~{chars // 2500} pages), {dt:.1f}s\n")
    print(rep.table())
    misses = [m | {"entity": e} for e, st in rep.per_type.items() for m in st.misses]
    if args.split not in ("dev", "dev2", "devall", "fin", "ind"):
        print(f"\n(sealed split: {len(misses)} misses, {len(rep.false_pos)} false positives — details withheld)")
        return
    print(f"\nMISSES ({len(misses)}):")
    for m in misses[:args.show]:
        print(f"  [{m['entity']}] {m['doc']}: {m['value']!r} cov={m['coverage']}  …{m['context']}…")
    print(f"\nFALSE POSITIVES ({len(rep.false_pos)}):", dict(Counter(f["entity"] for f in rep.false_pos)))
    for f in rep.false_pos[:args.show]:
        print(f"  [{f['entity']} {f['score']} {f['source']}] {f['doc']}: {f['text']!r}  …{f['context']}…")
    if args.json:
        Path(args.json).write_text(json.dumps({"recall": rep.recall, "precision": rep.precision, "f1": rep.f1,
                                               "per_type": {k: {"gold": v.gold, "caught": v.caught}
                                                            for k, v in rep.per_type.items()},
                                               "misses": misses, "false_positives": rep.false_pos}, indent=1))


def _install_ml_cache(settings) -> None:
    import copy
    import hashlib
    import pickle

    from obscura.detection.text import ner
    cache_dir = ROOT / "benchmarks" / ".mlcache"
    cache_dir.mkdir(exist_ok=True)

    def wrap(name, fn):
        def cached(text, *a, **kw):
            key = hashlib.sha1(f"{name}|{settings.spacy_model}|{settings.gliner_model}|{a}|{sorted(kw.items())}|{text}"
                               .encode()).hexdigest()
            f = cache_dir / f"{key}.pkl"
            if f.exists():
                return copy.deepcopy(pickle.loads(f.read_bytes()))
            out = fn(text, *a, **kw)
            f.write_bytes(pickle.dumps(out))
            return copy.deepcopy(out)
        return cached
    ner.spacy_entities = wrap("spacy", ner.spacy_entities)
    ner.gliner_entities = wrap("gliner", ner.gliner_entities)


if __name__ == "__main__":
    main()
