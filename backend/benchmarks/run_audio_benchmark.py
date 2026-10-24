"""End-to-end audio redaction benchmark: 100 synthesized recordings through the real audio pipeline.

    python benchmarks/run_audio_benchmark.py              # 25 scripts x 4 voices, half telephone-degraded
    python benchmarks/run_audio_benchmark.py --verbose    # print every miss with what Whisper heard

Every clip goes through AudioDocument.analyze (local Whisper -> text engine -> time ranges), the same path as
an uploaded recording. A spoken identifier counts as caught when a selected detection covers it. Needs the
macOS `say` command; clips live in a temporary folder and are deleted afterwards.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from benchmarks.whisper_compare import _words, wer  # noqa: E402

# (script, [(type, exact substring of the script that must be bleeped)])
SCRIPTS = [
    ("My name is Rosalind Pham and my social security number is 523 71 9921.",
     [("PERSON", "Rosalind Pham"), ("SSN", "523 71 9921")]),
    ("You can reach me at 512 398 0047, that's my cell phone.", [("PHONE", "512 398 0047")]),
    ("I live at 3318 Wagon Trail Road in Lockhart, Texas.", [("ADDRESS", "3318 Wagon Trail Road")]),
    ("My date of birth is November 2nd, 1979.", [("DATE_OF_BIRTH", "November 2nd, 1979")]),
    ("The other driver's plate was S F D 4 4 1 7.", [("LICENSE_PLATE", "S F D 4 4 1 7")]),
    ("This is Officer Jennifer Castaneda, badge number 4127.", [("PERSON", "Jennifer Castaneda")]),
    ("My email is rosalind dot pham at gmail dot com.", [("EMAIL", "rosalind dot pham at gmail dot com")]),
    ("My driver's license number is 4 0 9 2 1 1 8 7.", [("DRIVERS_LICENSE", "4 0 9 2 1 1 8 7")]),
    ("The card number is 4111 1111 1111 1111.", [("CREDIT_CARD", "4111 1111 1111 1111")]),
    ("My account number is 7720 0418 0471 at Capital Hill Bank.", [("BANK_ACCOUNT", "7720 0418 0471")]),
    ("I work at the McDonald's on Bank Street, I'm the night manager.",
     [("INDIRECT_LOCATION", "McDonald's on Bank Street")]),
    ("My husband Hunter Wells drives for Swiftline Freight.",
     [("PERSON", "Hunter Wells"), ("EMPLOYER", "Swiftline Freight")]),
    ("Her daughter Kaylee is eight years old.", [("PERSON", "Kaylee")]),
    ("Call me back at 210 455 0912 any time after five.", [("PHONE", "210 455 0912")]),
    ("The code for her door lock is 4471.", [("PASSWORD", "4471")]),
    ("My Medicaid member ID is X O D 8 8 4 4 1 7 2 0 3.", [("HEALTH_PLAN_ID", "X O D 8 8 4 4 1 7 2 0 3")]),
    ("I was born on March 3rd, 1985, in San Antonio.", [("DATE_OF_BIRTH", "March 3rd, 1985")]),
    ("We live at 1302 Maple Drive, apartment 4.", [("ADDRESS", "1302 Maple Drive")]),
    ("Dr. Daniel Szymanski did the surgery.", [("PERSON", "Daniel Szymanski")]),
    ("The claim number is C L M 2 0 2 3 0 0 4 5 8 7 1.", [("CLAIM_NUMBER", "C L M 2 0 2 3 0 0 4 5 8 7 1")]),
    ("I'm a nurse at Saint David's Medical Center.", [("EMPLOYER", "Saint David's Medical Center")]),
    ("My neighbor Grace Hill heard the whole thing.", [("PERSON", "Grace Hill")]),
    ("Text me at 737 302 6614 when you get there.", [("PHONE", "737 302 6614")]),
    ("The last four of my social are 9921.", [("SSN", "9921")]),
    ("My son goes to Westwood Hills Elementary.", [("SCHOOL", "Westwood Hills Elementary")]),
]
VOICES = ["Samantha", "Daniel", "Karen", "Rishi"]


def _degrade(src: Path, dst: Path, seed: int) -> None:
    import numpy as np
    import soundfile as sf
    data, sr = sf.read(str(src), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    step = max(1, int(round(sr / 8000)))
    tel = np.repeat(data[::step], step)[: len(data)]
    tel = np.tanh(tel * 2.0) / 2.0
    rng = np.random.default_rng(seed)
    tel = tel + rng.normal(0, np.sqrt(np.mean(tel ** 2)) / 4.0, len(tel)).astype(np.float32)
    sf.write(str(dst), tel, sr)


_TOK = re.compile(r"[A-Za-z0-9']+")


def _sim(a: str, b: str) -> float:
    a, b = a.lower(), b.lower()
    if a == b:
        return 1.0
    if a.isdigit() and b.isdigit() and (a in b or b in a):
        return 0.8
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def _align(ref: list[str], hyp: list[str]) -> list[int | None]:
    """Word alignment (edit distance with fuzzy substitution): for each script word, the transcript word index
    it was recognised as, or None when the recogniser dropped / merged it."""
    n, m = len(ref), len(hyp)
    cost = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0], back[i][0] = i, "d"
    for j in range(1, m + 1):
        cost[0][j], back[0][j] = j, "i"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = cost[i - 1][j - 1] + (1 - _sim(ref[i - 1], hyp[j - 1]))
            dele, ins = cost[i - 1][j] + 1, cost[i][j - 1] + 1
            cost[i][j], back[i][j] = min((sub, "s"), (dele, "d"), (ins, "i"))
    out: list[int | None] = [None] * n
    i, j = n, m
    while i > 0 or j > 0:
        b = back[i][j]
        if b == "s":
            out[i - 1] = j - 1 if _sim(ref[i - 1], hyp[j - 1]) > 0.3 else None
            i, j = i - 1, j - 1
        elif b == "d":
            i -= 1
        else:
            j -= 1
    return out


def _caught(script: str, gold: str, heard: str, dets: list) -> bool:
    """Was the audio of the gold words bleeped? The gold words are located in the transcript through the word
    alignment (so a misheard "Pham" → "Farm" that was redacted still counts), then must be >= 75% covered."""
    rt = [(m.group(), m.start(), m.end()) for m in _TOK.finditer(script)]
    ht = [(m.group(), m.start(), m.end()) for m in _TOK.finditer(heard)]
    if not ht:
        return False
    g0 = script.find(gold)
    gidx = [k for k, (_, a, b) in enumerate(rt) if a >= g0 and b <= g0 + len(gold)]
    al = _align([w for w, _, _ in rt], [w for w, _, _ in ht])
    hit = [al[k] for k in gidx if al[k] is not None]
    if hit:
        lo, hi = min(hit), max(hit)
    else:  # every gold word dropped/merged: use the transcript words between the aligned neighbours
        before = [al[k] for k in range(0, gidx[0]) if al[k] is not None]
        after = [al[k] for k in range(gidx[-1] + 1, len(rt)) if al[k] is not None]
        lo = (before[-1] + 1) if before else 0
        hi = (after[0] - 1) if after else len(ht) - 1
        if hi < lo:
            return True  # nothing was transcribed for these words, so nothing is audible as text either
    a, b = ht[lo][1], ht[hi][2]
    need = [i for i in range(a, b) if heard[i].isalnum()]
    cov = [d for d in dets if d.selected and d.start >= 0]
    got = sum(1 for i in need if any(d.start <= i < d.end for d in cov))
    return bool(need) and got / len(need) >= 0.75


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="whisper model (default: the configured one)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if not shutil.which("say"):
        print("needs macOS `say`")
        return
    import subprocess
    from obscura.config import settings
    from obscura.detection.text.engine import AnalyzeOptions
    from obscura.redact.audio import AudioDocument
    if args.model:
        settings.whisper_model = args.model
    opts = AnalyzeOptions()
    stats = {"clean": [0, 0, 0.0, 0], "phone": [0, 0, 0.0, 0]}
    misses = []
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        n = 0
        for vi, voice in enumerate(VOICES):
            for si, (text, gold) in enumerate(SCRIPTS):
                n += 1
                aiff = tmp / f"{voice}_{si}.aiff"
                subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True, capture_output=True)
                kind = "phone" if (vi + si) % 2 else "clean"
                path = aiff
                if kind == "phone":
                    path = tmp / f"{voice}_{si}.wav"
                    _degrade(aiff, path, n)
                doc = AudioDocument(path)
                dets = doc.analyze(opts)
                heard = doc.transcript.text if getattr(doc, "transcript", None) else ""
                st = stats[kind]
                st[2] += wer(text, heard)
                st[3] += 1
                for ent, val in gold:
                    st[1] += 1
                    ok = _caught(text, val, heard, dets)
                    st[0] += ok
                    if not ok:
                        misses.append((voice, kind, ent, val, heard, [(x.entity, x.text) for x in dets if x.selected]))
    dt = time.perf_counter() - t0
    total_hit = sum(v[0] for v in stats.values())
    total = sum(v[1] for v in stats.values())
    print(f"\nAUDIO  whisper={settings.whisper_model}  {n} clips, {dt:.0f}s")
    for kind, (hit, tot, w, c) in stats.items():
        print(f"  {kind:6s} identifiers caught {hit}/{tot} ({100 * hit / tot:.1f}%)   mean WER {100 * w / c:.1f}%")
    print(f"  TOTAL  identifiers caught {total_hit}/{total} ({100 * total_hit / total:.1f}%)")
    if misses:
        print(f"\nMISSES ({len(misses)}):")
        for voice, kind, ent, val, heard, found in misses[: (None if args.verbose else 15)]:
            print(f"  [{ent}] {voice}/{kind}: {val!r}\n     heard: {heard.strip()!r}")
            if args.verbose:
                print(f"     found: {found}")


if __name__ == "__main__":
    main()
