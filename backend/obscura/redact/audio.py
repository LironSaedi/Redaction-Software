"""Audio redaction: transcript → PII spans → time ranges → bleep / mute / noise, plus captions.

Also used for the audio track of videos. Output keeps the original sample rate and channels; all
container metadata is dropped.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import soundfile as sf

from ..detection.audio.transcribe import Transcript, transcribe
from ..detection.text.engine import AnalyzeOptions, SearchTerm, TextAnalyzer, get_analyzer
from ..detection.text.entities import ENTITIES
from .model import Detection

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
AUDIO_EFFECTS = ("bleep", "mute", "noise")


class AudioDocument:
    def __init__(self, path: str | Path, transcript: Transcript | None = None):
        self.path = Path(path)
        self.transcript = transcript

    def transcribe(self, model: str | None = None, language: str | None = None) -> Transcript:
        if self.transcript is None:
            self.transcript = transcribe(self.path, model=model, language=language)
        return self.transcript

    def analyze(self, options: AnalyzeOptions | None = None, analyzer: TextAnalyzer | None = None,
                pad: float = 0.12) -> list[Detection]:
        tr = self.transcribe()
        opts = options or AnalyzeOptions()
        opts.transcript = True
        spans = (analyzer or get_analyzer()).analyze(tr.text, opts)
        return [d for d in (self._span_to_det(sp, pad) for sp in spans) if d]

    def search(self, terms: list[SearchTerm], pad: float = 0.12) -> list[Detection]:
        tr = self.transcribe()
        spans = TextAnalyzer._user_rules(tr.text, terms)
        for s in spans:
            s.meta["selected"] = True
        return [d for d in (self._span_to_det(sp, pad) for sp in spans) if d]

    def _span_to_det(self, sp, pad: float) -> Detection | None:
        ws = [w for w in self.transcript.words if w.char_start < sp.end and sp.start < w.char_end]
        if not ws:
            return None
        t0, t1 = max(0.0, ws[0].start - pad), ws[-1].end + pad
        ent = ENTITIES.get(sp.entity)
        return Detection(entity=sp.entity, text=sp.text, score=sp.score, source=sp.source, boxes=[], start=sp.start,
                         end=sp.end, explanation=sp.explanation, selected=bool(sp.meta.get("selected", True)),
                         exemption=sp.meta.get("exemption") or (ent.exemption if ent else ""), kind="audio",
                         meta={"t0": round(t0, 3), "t1": round(t1, 3), "words": [w.text for w in ws]})

    def apply(self, detections: list[Detection], out_path: str | Path, effect: str = "bleep",
              voice_disguise: bool = False, verify: bool = True) -> dict:
        ranges = merge_ranges([(d.meta["t0"], d.meta["t1"]) for d in detections
                               if d.selected and "t0" in d.meta])
        tmp_in = Path(str(out_path) + ".src.wav")
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(self.path), "-vn",
                        "-acodec", "pcm_s16le", str(tmp_in)], check=True)
        data, sr = sf.read(str(tmp_in), always_2d=True, dtype="float32")
        tmp_in.unlink(missing_ok=True)
        data = redact_samples(data, sr, ranges, effect)
        out_path = Path(out_path)
        tmp_wav = Path(str(out_path) + ".tmp.wav")
        sf.write(str(tmp_wav), data, sr, subtype="PCM_16")
        filters = []
        if voice_disguise:  # pitch up ~25% with tempo preserved: speaker becomes harder to recognise
            filters = ["-af", f"asetrate={int(sr * 1.25)},aresample={sr},atempo=0.8"]
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp_wav), *filters,
                        "-map_metadata", "-1", *(_codec_for(out_path)), str(out_path)], check=True)
        tmp_wav.unlink(missing_ok=True)
        report = {"segments_redacted": len(ranges), "seconds_redacted": round(sum(b - a for a, b in ranges), 2),
                  "effect": effect, "metadata_removed": True, "voice_disguise": voice_disguise}
        if verify:
            report["verification"] = verify_audio(out_path, [d for d in detections if d.selected], language=(self.transcript.language if self.transcript else "en") or "en")
        return report

    def cues(self, detections: list[Detection], redact: bool = True) -> list[tuple[float, float, str]]:
        """Caption cues (start, end, text) with redacted words replaced by [REDACTED]."""
        tr = self.transcribe()
        hidden = [(d.start, d.end) for d in detections if d.selected and d.start >= 0] if redact else []
        out = []
        for seg in _caption_segments(tr):
            words = []
            for w in seg["words"]:
                if any(w.char_start < b and a < w.char_end for a, b in hidden):
                    if not words or words[-1] != "[REDACTED]":
                        words.append("[REDACTED]")
                else:
                    words.append(w.text)
            out.append((seg["start"], seg["end"], " ".join(words)))
        return out

    def captions(self, detections: list[Detection], fmt: str = "srt", redact: bool = True) -> str:
        tr = self.transcribe()
        hidden = [(d.start, d.end) for d in detections if d.selected and d.start >= 0] if redact else []
        lines = []
        for i, seg in enumerate(_caption_segments(tr), 1):
            words = []
            for w in seg["words"]:
                if any(w.char_start < b and a < w.char_end for a, b in hidden):
                    if not words or words[-1] != "[REDACTED]":
                        words.append("[REDACTED]")
                else:
                    words.append(w.text)
            text = " ".join(words)
            if fmt == "vtt":
                lines.append(f"{_ts(seg['start'], '.')} --> {_ts(seg['end'], '.')}\n{text}\n")
            else:
                lines.append(f"{i}\n{_ts(seg['start'], ',')} --> {_ts(seg['end'], ',')}\n{text}\n")
        return ("WEBVTT\n\n" if fmt == "vtt" else "") + "\n".join(lines)

    def redacted_transcript(self, detections: list[Detection]) -> str:
        tr = self.transcribe()
        text = tr.text
        for d in sorted((d for d in detections if d.selected and d.start >= 0), key=lambda d: -d.start):
            text = text[:d.start] + f"[{d.entity}]" + text[d.end:]
        return text


def merge_ranges(ranges: list[tuple[float, float]], gap: float = 0.05) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def redact_samples(data: np.ndarray, sr: int, ranges: list[tuple[float, float]], effect: str = "bleep") -> np.ndarray:
    out = data.copy()
    fade = max(1, int(sr * 0.005))
    for a, b in ranges:
        i0, i1 = max(0, int(a * sr)), min(len(out), int(np.ceil(b * sr)))
        n = i1 - i0
        if n <= 0:
            continue
        if effect == "mute":
            seg = np.zeros((n, out.shape[1]), np.float32)
        elif effect == "noise":
            seg = (np.random.default_rng(0).standard_normal((n, out.shape[1])) * 0.05).astype(np.float32)
        else:
            t = np.arange(n) / sr
            tone = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
            seg = np.repeat(tone[:, None], out.shape[1], axis=1)
        if n > 2 * fade:  # short fades avoid clicks; the original speech is fully replaced either way
            ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
            seg[:fade] *= ramp
            seg[-fade:] *= ramp[::-1]
        out[i0:i1] = seg
    return out


def _codec_for(path: Path) -> list[str]:
    ext = path.suffix.lower()
    return {".mp3": ["-c:a", "libmp3lame", "-q:a", "2"], ".m4a": ["-c:a", "aac", "-b:a", "160k"],
            ".aac": ["-c:a", "aac", "-b:a", "160k"], ".ogg": ["-c:a", "libvorbis", "-q:a", "5"],
            ".flac": ["-c:a", "flac"], ".wav": ["-c:a", "pcm_s16le"]}.get(ext, ["-c:a", "pcm_s16le"])


def _ts(t: float, sep: str) -> str:
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}{sep}{int(round((s % 1) * 1000)):03d}"


def _caption_segments(tr: Transcript, max_words: int = 12, max_dur: float = 5.0) -> list[dict]:
    segs, cur = [], []
    for w in tr.words:
        if cur and (len(cur) >= max_words or w.end - cur[0].start > max_dur):
            segs.append({"start": cur[0].start, "end": cur[-1].end, "words": cur})
            cur = []
        cur.append(w)
    if cur:
        segs.append({"start": cur[0].start, "end": cur[-1].end, "words": cur})
    return segs


_NUMW = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
         "seven": "7", "eight": "8", "nine": "9"}


def _digits_of(text: str) -> str:
    toks = re.findall(r"[a-z]+|\d", text.lower())
    return "".join(_NUMW.get(t, t if t.isdigit() else "") for t in toks)


def verify_audio(path: str | Path, detections: list[Detection], language: str = "en") -> dict:
    """Re-transcribe the output (a different model from the one that found the values) and confirm no redacted
    value is still audible."""
    try:
        tr = transcribe(path, model="small.en") if language == "en" else transcribe(path, language=language)
    except FileNotFoundError:
        tr = transcribe(path)
    heard = tr.text.lower()
    heard_digits = _digits_of(tr.text)
    issues = []
    for d in detections:
        v = d.text.strip()
        dg = _digits_of(v)
        if len(dg) >= 4 and dg in heard_digits:
            issues.append({"type": "still_audible", "entity": d.entity, "t0": d.meta.get("t0")})
        elif len(dg) < 4 and len(v) >= 4 and re.search(r"\b" + re.escape(v.lower()) + r"\b", heard):
            issues.append({"type": "still_audible", "entity": d.entity, "t0": d.meta.get("t0")})
    return {"passed": not issues, "issues": issues, "retranscript_chars": len(tr.text)}
