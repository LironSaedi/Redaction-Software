"""Local speech-to-text with word timestamps (faster-whisper / CTranslate2).

Runs in a *separate process*: faster-whisper's PyAV and OpenCV each bundle their own libav and must
not share an address space. Audio is decoded with the bundled ffmpeg to 16 kHz mono float32.
"""
from __future__ import annotations

import multiprocessing as mp
import subprocess
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float
    char_start: int = 0
    char_end: int = 0
    speaker: str | None = None


@dataclass
class Transcript:
    text: str
    words: list[Word]
    segments: list[dict] = field(default_factory=list)
    language: str = "en"
    duration: float = 0.0
    model: str = ""

    def to_dict(self) -> dict:
        return {"text": self.text, "language": self.language, "duration": self.duration, "model": self.model,
                "segments": self.segments,
                "words": [w.__dict__ for w in self.words]}

    @staticmethod
    def from_dict(d: dict) -> "Transcript":
        return Transcript(d["text"], [Word(**w) for w in d["words"]], d.get("segments", []), d.get("language", "en"),
                          d.get("duration", 0.0), d.get("model", ""))


def decode_16k(path: str | Path) -> np.ndarray:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    raw = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def _worker(path: str, model_dir: str, device: str, task: str, initial_prompt: str | None,
            language: str | None = "en") -> dict:
    import os
    os.environ["HF_HUB_OFFLINE"] = "1"
    from ... import netguard
    netguard.maybe_block()  # the worker process inherits the parent's network policy
    from faster_whisper import WhisperModel
    audio = decode_16k(path)
    compute = "int8" if device == "cpu" else "float16"
    model = WhisperModel(model_dir, device=device, compute_type=compute, local_files_only=True)
    segs, info = model.transcribe(audio, language=language, task=task, beam_size=5,
                                  word_timestamps=True, vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
                                  condition_on_previous_text=False, temperature=0.0, initial_prompt=initial_prompt)
    words, segments = [], []
    for s in segs:
        segments.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        for w in (s.words or []):
            words.append({"text": w.word, "start": float(w.start), "end": float(w.end), "prob": float(w.probability)})
    return {"words": words, "segments": segments, "language": info.language, "duration": float(info.duration)}


def _detect_worker(path: str, model_dir: str, device: str) -> tuple[str, float]:
    import os
    os.environ["HF_HUB_OFFLINE"] = "1"
    from ... import netguard
    netguard.maybe_block()
    from faster_whisper import WhisperModel
    audio = decode_16k(path)[: 16000 * 30]
    model = WhisperModel(model_dir, device=device, compute_type="int8" if device == "cpu" else "float16",
                         local_files_only=True)
    lang, prob, _ = model.detect_language(audio)
    return lang, float(prob)


_POOL: ProcessPoolExecutor | None = None


def _pool() -> ProcessPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))
    return _POOL


MULTILINGUAL = "small"  # the 99-language model; English audio uses the more accurate English-only model


def detect_language(path: str | Path) -> tuple[str, float]:
    from ...config import MODELS_DIR
    d = MODELS_DIR / "whisper" / MULTILINGUAL
    if not d.exists():
        return "en", 0.0
    return _pool().submit(_detect_worker, str(path), str(d), "cuda" if _has_cuda() else "cpu").result()


def transcribe(path: str | Path, model: str | None = None, task: str = "transcribe",
               initial_prompt: str | None = None, language: str | None = None) -> Transcript:
    """language: an ISO code, "auto" (detect; English goes to the English model) or None (= English).
    task "translate" gives an English translation of non-English speech, with timestamps."""
    from ...config import MODELS_DIR, settings
    lang = language or "en"
    if lang == "auto":
        lang, _ = detect_language(path)
    if task == "translate" or lang != "en":
        model = MULTILINGUAL if (MODELS_DIR / "whisper" / MULTILINGUAL).exists() else (model or settings.whisper_model)
    model = model or settings.whisper_model
    model_dir = MODELS_DIR / "whisper" / model
    if not model_dir.exists():
        raise FileNotFoundError(f"whisper model missing: {model_dir}")
    if model.endswith(".en"):
        lang = "en"  # English-only models cannot do anything else
    # CTranslate2 has no Metal backend; CPU int8 on Apple Silicon is fast. CUDA when present.
    device = "cuda" if _has_cuda() else "cpu"
    res = _pool().submit(_worker, str(path), str(model_dir), device, task, initial_prompt,
                         None if task == "translate" else lang).result()
    return build_transcript(res, model)


def _has_cuda() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def build_transcript(res: dict, model: str = "") -> Transcript:
    """Join words into text, remembering each word's character span."""
    words: list[Word] = []
    parts: list[str] = []
    pos = 0
    for w in res["words"]:
        token = w["text"]
        if not token.strip():
            continue
        lead = " " if parts and not token.startswith(" ") else ""
        token = token if parts else token.lstrip()
        text = lead + token
        stripped = text.lstrip()
        start = pos + (len(text) - len(stripped))
        parts.append(text)
        pos += len(text)
        words.append(Word(stripped, w["start"], w["end"], w["prob"], start, pos))
    return Transcript("".join(parts), words, res.get("segments", []), res.get("language", "en"),
                      res.get("duration", 0.0), model)
