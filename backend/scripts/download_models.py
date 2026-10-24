"""One-time model download for Obscura.

Run this on a machine with internet access. Afterwards the whole `models/` folder can be
copied to an air-gapped server; Obscura never touches the network at runtime.

    python scripts/download_models.py            # default set
    python scripts/download_models.py --whisper medium.en
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
HF_HOME = MODELS / "hf"

os.environ["HF_HOME"] = str(HF_HOME)
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

SPACY_WHEELS = {
    "en_core_web_trf": "https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.8.0/en_core_web_trf-3.8.0-py3-none-any.whl",
}

GLINER_MODELS = {
    "nvidia/gliner-PII": "gliner/nvidia-gliner-pii",
}
# Models that lost the held-out comparison (benchmarks/results/shootout_heldout.txt). Not installed by default;
# `--candidates` fetches them only to re-run benchmarks/model_shootout_heldout.sh.
CANDIDATE_GLINER_MODELS = {
    "knowledgator/gliner-pii-base-v1.0": "gliner/knowledgator-gliner-pii-base",
}

FILES = {
    # (hf repo, filename) -> local name
    ("Wespeaker/wespeaker-voxceleb-resnet34-LM", "voxceleb_resnet34_LM.onnx"): "speaker/wespeaker_resnet34_lm.onnx",
    ("deepghs/yolo-face", "yolov11m-face/model.pt"): "vision/face_yolov11m.pt",
    ("morsetechlab/yolov11-license-plate-detection", "license-plate-finetune-v1m.pt"): "vision/plate_yolov11m.pt",
}

URLS = {
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx": "vision/face_yunet_2023mar.onnx",
    "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11m.pt": "vision/yolo11m.pt",
}


def _fetch(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  ok   {dest.relative_to(MODELS)}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  get  {url}")
    with urllib.request.urlopen(url) as r, open(dest.with_suffix(".part"), "wb") as f:
        shutil.copyfileobj(r, f)
    dest.with_suffix(".part").rename(dest)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--whisper", nargs="*", default=["small.en", "medium.en", "small"])  # "small": 99 languages
    ap.add_argument("--skip-translation", action="store_true", help="skip the M2M100 translation model (~0.5 GB)")
    ap.add_argument("--skip-spacy", action="store_true")
    ap.add_argument("--candidates", action="store_true", help="also fetch the models that lost the comparison")
    ap.add_argument("--dest", default=None, help="models folder (default: backend/models)")
    args = ap.parse_args()
    global MODELS, HF_HOME
    if args.dest:
        MODELS = Path(args.dest).expanduser().resolve()
        HF_HOME = MODELS / "hf"
        os.environ["HF_HOME"] = str(HF_HOME)
    MODELS.mkdir(parents=True, exist_ok=True)

    from huggingface_hub import hf_hub_download, snapshot_download

    print("[vision / speaker]")
    for url, local in URLS.items():
        _fetch(url, MODELS / local)
    for (repo, fname), local in FILES.items():
        dest = MODELS / local
        if dest.exists():
            print(f"  ok   {local}")
            continue
        p = hf_hub_download(repo, fname)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, dest)
        print(f"  got  {local}")

    print("[gliner]")
    for repo, local in (GLINER_MODELS | (CANDIDATE_GLINER_MODELS if args.candidates else {})).items():
        snapshot_download(repo, local_dir=MODELS / local,
                          allow_patterns=["*.json", "*.bin", "*.model", "*.txt", "*.md"])
        print(f"  ok   {local}")

    print("[whisper]")
    for size in args.whisper:
        snapshot_download(f"Systran/faster-whisper-{size}", local_dir=MODELS / "whisper" / size)
        print(f"  ok   whisper/{size}")

    if not args.skip_translation:
        print("[translation]")
        dest = MODELS / "translate" / "m2m100_418m"
        if (dest / "model.bin").exists():
            print("  ok   translate/m2m100_418m")
        else:
            # official facebook/m2m100_418M (MIT licence), converted locally to CTranslate2 int8 (~0.5 GB)
            src = MODELS / "translate" / "_m2m100_hf"
            snapshot_download("facebook/m2m100_418M", local_dir=src,
                              allow_patterns=["*.json", "*.bin", "*.model", "*.txt", "sentencepiece*"])
            import ctranslate2.converters
            ctranslate2.converters.TransformersConverter(str(src)).convert(str(dest), quantization="int8", force=True)
            for f in ("sentencepiece.bpe.model", "vocab.json", "tokenizer_config.json", "special_tokens_map.json"):
                if (src / f).exists():
                    shutil.copy(src / f, dest / f)
            shutil.rmtree(src, ignore_errors=True)
            print("  got  translate/m2m100_418m")
    shutil.rmtree(HF_HOME, ignore_errors=True)  # plain folders only; nothing needs the hub cache
    if not args.skip_spacy:
        print("[spacy]")
        for name, url in SPACY_WHEELS.items():
            try:
                __import__(name)
                print(f"  ok   {name}")
                continue
            except ImportError:
                pass
            uv = shutil.which("uv")
            cmd = [uv, "pip", "install", "--python", sys.executable, url] if uv else [sys.executable, "-m", "pip", "install", url]
            subprocess.check_call(cmd)
    print("done. models in", MODELS)


if __name__ == "__main__":
    main()
