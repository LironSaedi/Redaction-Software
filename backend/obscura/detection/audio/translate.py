"""Local machine translation (M2M100-418M, MIT licence, CTranslate2 int8) — 100 languages, nothing leaves the host.

Used for transcripts and captions. For anything that may be released, translate the *redacted* text: redacted
words are replaced by a placeholder before translation, so a name or number never reaches the model output.
"""
from __future__ import annotations

import re
import threading

from ...config import MODELS_DIR

# ISO 639-1 codes M2M100 supports (subset shown in the UI; all 100 work)
LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
    "nl": "Dutch", "pl": "Polish", "ru": "Russian", "uk": "Ukrainian", "ro": "Romanian", "el": "Greek",
    "tr": "Turkish", "ar": "Arabic", "he": "Hebrew", "fa": "Persian", "ur": "Urdu", "hi": "Hindi", "bn": "Bengali",
    "pa": "Punjabi", "gu": "Gujarati", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam", "mr": "Marathi",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese", "th": "Thai", "id": "Indonesian",
    "ms": "Malay", "tl": "Tagalog", "km": "Khmer", "lo": "Lao", "my": "Burmese", "so": "Somali", "sw": "Swahili",
    "am": "Amharic", "yo": "Yoruba", "ig": "Igbo", "ha": "Hausa", "ht": "Haitian Creole", "cs": "Czech",
    "sk": "Slovak", "hu": "Hungarian", "bg": "Bulgarian", "sr": "Serbian", "hr": "Croatian", "bs": "Bosnian",
    "sq": "Albanian", "hy": "Armenian", "ka": "Georgian", "az": "Azerbaijani", "kk": "Kazakh", "uz": "Uzbek",
    "ps": "Pashto", "ne": "Nepali", "si": "Sinhala", "sv": "Swedish", "no": "Norwegian", "da": "Danish",
    "fi": "Finnish", "et": "Estonian", "lv": "Latvian", "lt": "Lithuanian", "ga": "Irish", "cy": "Welsh",
}
PLACEHOLDER = "[REDACTED]"
_LOCK = threading.Lock()
_MODEL = None


def model_dir():
    return MODELS_DIR / "translate" / "m2m100_418m"


def available() -> bool:
    return (model_dir() / "model.bin").exists()


def _load():
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            import ctranslate2
            import sentencepiece as spm
            d = model_dir()
            sp = spm.SentencePieceProcessor(model_file=str(d / "sentencepiece.bpe.model"))
            _MODEL = (ctranslate2.Translator(str(d), device="cpu", compute_type="int8"), sp)
    return _MODEL


def translate(texts: list[str], source: str, target: str, beam_size: int = 4) -> list[str]:
    """Translate a batch of sentences/segments. ``[REDACTED]`` placeholders are protected and restored."""
    if source == target:
        return list(texts)
    if not available():
        raise FileNotFoundError("translation model missing: run scripts/download_models.py")
    tr, sp = _load()
    batch, keep = [], []
    for t in texts:
        # protect placeholders: the model sees a neutral token, which is put back afterwards
        n = t.count(PLACEHOLDER)
        keep.append(n)
        src = t.replace(PLACEHOLDER, "XXXX")
        batch.append([f"__{source}__"] + sp.encode(src, out_type=str) + ["</s>"])
    res = tr.translate_batch(batch, target_prefix=[[f"__{target}__"]] * len(batch), beam_size=beam_size,
                             max_decoding_length=256)
    out = []
    for r, n in zip(res, keep):
        toks = [x for x in r.hypotheses[0] if not (x.startswith("__") and x.endswith("__"))]
        text = sp.decode(toks)
        text = re.sub(r"\bX{3,}\b", PLACEHOLDER, text)
        if n and PLACEHOLDER not in text:
            text = (PLACEHOLDER + " ") * n + text  # never drop a redaction marker silently
        out.append(text.strip())
    return out
