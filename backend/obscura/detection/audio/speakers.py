"""Speaker identification ("who spoke when") for transcripts — local, no extra Python packages.

Each transcript segment gets a voice embedding from WeSpeaker ResNet34 (Apache-2.0, ONNX, 26 MB, run with the
onnxruntime already installed); segments are grouped by agglomerative clustering on cosine distance, and every
segment / word is labelled "Speaker 1", "Speaker 2", … in order of first appearance. Labels are anonymous by design:
the tool never guesses who a speaker is.
"""
from __future__ import annotations

import threading

import numpy as np

from ...config import MODELS_DIR

_LOCK = threading.Lock()
_SESSION = None
SR = 16000


def model_path():
    return MODELS_DIR / "speaker" / "wespeaker_resnet34_lm.onnx"


def available() -> bool:
    return model_path().exists()


def _session():
    global _SESSION
    with _LOCK:
        if _SESSION is None:
            import onnxruntime as ort
            _SESSION = ort.InferenceSession(str(model_path()), providers=["CPUExecutionProvider"])
    return _SESSION


def _mel_banks(n_fft: int = 512, n_mels: int = 80, low: float = 20.0, high: float = SR / 2) -> np.ndarray:
    def mel(f):
        return 1127.0 * np.log(1.0 + f / 700.0)
    n_bins = n_fft // 2
    fft_freqs = np.arange(n_bins) * SR / n_fft
    m_lo, m_hi = mel(low), mel(high)
    centers = np.linspace(m_lo, m_hi, n_mels + 2)
    fm = mel(fft_freqs)
    banks = np.zeros((n_mels, n_bins + 1), np.float32)
    for i in range(n_mels):
        l, c, r = centers[i], centers[i + 1], centers[i + 2]
        up = (fm - l) / (c - l)
        down = (r - fm) / (r - c)
        banks[i, :n_bins] = np.maximum(0.0, np.minimum(up, down))
    return banks


_BANKS = None


def fbank(wave: np.ndarray) -> np.ndarray:
    """Kaldi-style 80-dim log Mel filter bank (25 ms window, 10 ms shift, Povey window, pre-emphasis 0.97),
    with per-utterance mean normalisation — the features WeSpeaker models are trained on."""
    global _BANKS
    if _BANKS is None:
        _BANKS = _mel_banks()
    x = wave.astype(np.float32) * 32768.0
    win, hop, n_fft = 400, 160, 512
    if len(x) < win:
        x = np.pad(x, (0, win - len(x)))
    n = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx]
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1] - 0.97 * frames[:, :1], frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    povey = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(win) / (win - 1))) ** 0.85
    spec = np.abs(np.fft.rfft(frames * povey, n=n_fft)) ** 2
    feats = np.log(np.maximum(spec @ _BANKS.T, np.finfo(np.float32).eps))
    return (feats - feats.mean(axis=0, keepdims=True)).astype(np.float32)


def embed(wave: np.ndarray) -> np.ndarray:
    feats = fbank(wave)[None]
    e = _session().run(None, {"feats": feats})[0][0]
    return e / (np.linalg.norm(e) + 1e-9)


def diarize(audio: np.ndarray, segments: list[dict], threshold: float = 0.55, max_speakers: int = 8) -> list[str]:
    """Speaker label for each transcript segment ({start, end}). Very short segments take the label of the
    nearest segment in time."""
    from scipy.cluster.hierarchy import fcluster, linkage
    usable, embs = [], []
    for i, s in enumerate(segments):
        a, b = int(s["start"] * SR), int(s["end"] * SR)
        if b - a >= int(0.7 * SR):
            usable.append(i)
            embs.append(embed(audio[a:b]))
    labels = [""] * len(segments)
    if not usable:
        return ["Speaker 1"] * len(segments)
    if len(usable) == 1:
        cl = [1]
    else:
        Z = linkage(np.stack(embs), method="average", metric="cosine")
        cl = list(fcluster(Z, t=threshold, criterion="distance"))
        if len(set(cl)) > max_speakers:
            cl = list(fcluster(Z, t=max_speakers, criterion="maxclust"))
    order: dict[int, str] = {}
    for i, c in zip(usable, cl):
        order.setdefault(c, f"Speaker {len(order) + 1}")
        labels[i] = order[c]
    for i, s in enumerate(segments):  # short segments: nearest labelled neighbour
        if not labels[i]:
            j = min(usable, key=lambda k: abs(segments[k]["start"] - s["start"]))
            labels[i] = labels[j]
    return labels


def label_transcript(path, transcript) -> int:
    """Add a "speaker" field to every segment (and word) of a Transcript in place. Returns the speaker count."""
    from .transcribe import decode_16k
    if not available() or not transcript.segments:
        return 0
    audio = decode_16k(path)
    labels = diarize(audio, transcript.segments)
    for seg, lab in zip(transcript.segments, labels):
        seg["speaker"] = lab
    for w in transcript.words:
        seg = next((s for s in transcript.segments if s["start"] - 0.05 <= w.start <= s["end"] + 0.05), None)
        if seg is not None:
            w.speaker = seg.get("speaker")
    return len(set(labels))
