"""One process-wide lock around every PyTorch model (spaCy transformer, GLiNER, YOLO).

Background jobs run in a thread pool. Loading or running two torch models at the same time from different
threads can crash the whole process on some backends (seen as a segfault with Apple's MPS while two analyses
started together), so model loading and inference are serialised. Rules, OCR, ffmpeg and Whisper (its own
process) still run in parallel.
"""
import threading

TORCH_LOCK = threading.RLock()
