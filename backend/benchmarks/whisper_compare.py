"""Compare the local Whisper models on spoken PII (macOS text-to-speech, clean and telephone-quality noisy).

    python benchmarks/whisper_compare.py                # small.en vs medium.en
    python benchmarks/whisper_compare.py --models small.en

For every clip it measures word error rate against the script and whether each spoken identifier (name, SSN,
phone, address, date of birth, plate) ends up inside a detection of the redaction pipeline — the number that
matters for audio redaction. Needs the `say` command (macOS); clips are written to a temporary folder only.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCRIPTS = [
    ("My name is Rosalind Pham and my social security number is 523 71 9921.",
     [("PERSON", "Rosalind Pham"), ("SSN", "523719921")]),
    ("You can reach me at 512 398 0047, that's my cell phone.",
     [("PHONE", "5123980047")]),
    ("I live at 3318 Wagon Trail Road in Lockhart, Texas 78644.",
     [("ADDRESS", "3318 Wagon Trail Road")]),
    ("My date of birth is November 2nd, 1979, and my husband is Hunter Wells.",
     [("DATE_OF_BIRTH", "November 2nd, 1979"), ("PERSON", "Hunter Wells")]),
    ("The other driver's plate was S F D 4 4 1 7 and he works at Swiftline Freight.",
     [("LICENSE_PLATE", "SFD4417")]),
    ("This is Officer Jennifer Castaneda, badge number 4127, calling about case 25 187734.",
     [("PERSON", "Jennifer Castaneda")]),
]
VOICES = ["Samantha", "Daniel", "Karen", "Moira", "Rishi", "Tessa"]


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower())


def wer(ref: str, hyp: str) -> float:
    r, h = _words(ref), _words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


def make_clips(tmp: Path) -> list[tuple[Path, str, list, str]]:
    import numpy as np
    import soundfile as sf
    clips = []
    rng = np.random.default_rng(7)
    for vi, voice in enumerate(VOICES):
        for si, (text, gold) in enumerate(SCRIPTS):
            if (vi + si) % 2:  # every voice says half the scripts: 18 clips, all scripts covered 3x
                continue
            aiff = tmp / f"{voice}_{si}.aiff"
            subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True, capture_output=True)
            clips.append((aiff, text, gold, "clean"))
            # telephone quality: 8 kHz band-limit, light compression and noise at ~12 dB SNR
            data, sr = sf.read(str(aiff), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            step = max(1, int(round(sr / 8000)))
            tel = np.repeat(data[::step], step)[: len(data)]
            tel = np.tanh(tel * 2.0) / 2.0
            noise = rng.normal(0, np.sqrt(np.mean(tel ** 2)) / 4.0, len(tel)).astype(np.float32)
            noisy = tmp / f"{voice}_{si}_phone.wav"
            sf.write(str(noisy), tel + noise, sr)
            clips.append((noisy, text, gold, "phone"))
    return clips


def covered(gold_val: str, ent: str, transcript: str, spans) -> bool:
    if ent in ("SSN", "PHONE", "LICENSE_PLATE"):
        target = re.sub(r"[^0-9a-z]", "", gold_val.lower())
        for sp in spans:
            if re.sub(r"[^0-9a-z]", "", transcript[sp.start:sp.end].lower()).find(target[-4:]) >= 0:
                return True
        return False
    toks = _words(gold_val)
    det = " ".join(transcript[sp.start:sp.end].lower() for sp in spans)
    return sum(t in det for t in toks) >= max(1, int(len(toks) * 0.75))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="small.en,medium.en")
    ap.add_argument("--verbose", action="store_true", help="print each missed identifier with its transcript")
    args = ap.parse_args()
    if not shutil.which("say"):
        print("needs macOS `say` for the test clips")
        return
    from obscura.detection.audio.transcribe import transcribe
    from obscura.detection.text.engine import AnalyzeOptions, TextAnalyzer
    an = TextAnalyzer()
    opts = AnalyzeOptions(transcript=True, include_suggestions=False)
    with tempfile.TemporaryDirectory() as d:
        clips = make_clips(Path(d))
        print(f"{len(clips)} clips ({len(clips) // 2} voices×scripts, clean + telephone-noisy)\n")
        for model in args.models.split(","):
            stats = {"clean": [0, 0, 0.0], "phone": [0, 0, 0.0]}
            t0 = time.perf_counter()
            audio_s = 0.0
            for path, text, gold, kind in clips:
                tr = transcribe(path, model=model)
                audio_s += tr.duration if hasattr(tr, "duration") else 0
                spans = an.analyze(tr.text, opts)
                st = stats[kind]
                st[2] += wer(text, tr.text)
                for ent, val in gold:
                    st[1] += 1
                    ok = covered(val, ent, tr.text, spans)
                    st[0] += ok
                    if not ok and args.verbose:
                        print(f"   MISS {model} {kind} {path.name} [{ent}] {val!r}\n      heard: {tr.text.strip()!r}\n"
                              f"      found: {[(sp.entity, tr.text[sp.start:sp.end]) for sp in spans]}")
            dt = time.perf_counter() - t0
            n = len(clips) // 2
            print(f"== {model}  ({dt:.0f}s for {len(clips)} clips)")
            for kind, (hit, tot, w) in stats.items():
                print(f"   {kind:6s} PII caught {hit}/{tot} ({100 * hit / tot:.1f}%)   mean WER {100 * w / n:.1f}%")


if __name__ == "__main__":
    main()
