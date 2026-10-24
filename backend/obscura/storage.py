"""Encrypted blob storage.

Every original, working file, export, extracted text, detection list and transcript is stored with
AES-256-GCM in 1 MiB chunks (each chunk has its own nonce and is authenticated, so truncation or
tampering is detected). The master key lives in ``data/keys/master.key`` (mode 0600) or the
``OBSCURA_MASTER_KEY`` environment variable (base64) — keep it on separate storage for servers.

Processing tools (OCR, ffmpeg) need plaintext files: :func:`Storage.plain` decrypts to a private
0700 scratch directory and wipes the file afterwards.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
import shutil
import struct
import tempfile
import threading
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import DATA_DIR, settings

MAGIC = b"OBSC1"
CHUNK = 1 << 20


def _private_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    os.chmod(p, 0o700)
    return p


def load_master_key() -> bytes:
    env = os.environ.get("OBSCURA_MASTER_KEY")
    if env:
        key = base64.b64decode(env)
        if len(key) != 32:
            raise ValueError("OBSCURA_MASTER_KEY must be 32 bytes (base64)")
        return key
    kdir = _private_dir(DATA_DIR / "keys")
    kf = kdir / "master.key"
    if not kf.exists():
        kf.write_bytes(secrets.token_bytes(32))
        os.chmod(kf, 0o600)
    return kf.read_bytes()


class Storage:
    def __init__(self, root: Path | None = None, key: bytes | None = None, encrypt: bool | None = None):
        self.root = _private_dir(root or DATA_DIR / "blobs")
        self.tmp = _private_dir((root or DATA_DIR).parent / "tmp" if root else DATA_DIR / "tmp")
        self.encrypt = settings.encrypt_at_rest if encrypt is None else encrypt
        self.aead = AESGCM(key or load_master_key()) if self.encrypt else None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------------------------------
    def _path(self, blob_id: str) -> Path:
        if not blob_id or "/" in blob_id or ".." in blob_id:
            raise ValueError("bad blob id")
        return self.root / blob_id[:2] / blob_id

    def put_file(self, src: str | Path) -> tuple[str, str, int]:
        """Store a plaintext file. Returns (blob_id, sha256 of plaintext, size)."""
        blob_id = uuid.uuid4().hex
        dst = self._path(blob_id)
        dst.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        size = 0
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            if self.aead:
                fout.write(MAGIC)
            cur = fin.read(CHUNK)
            idx = 0
            while True:
                nxt = fin.read(CHUNK) if len(cur) == CHUNK else b""
                final = not nxt
                h.update(cur)
                size += len(cur)
                if self.aead:
                    nonce = secrets.token_bytes(12)
                    aad = blob_id.encode() + struct.pack(">IB", idx, 1 if final else 0)
                    ct = self.aead.encrypt(nonce, cur, aad)
                    fout.write(struct.pack(">I", len(ct)) + nonce + ct)
                else:
                    fout.write(cur)
                if final:
                    break
                cur = nxt
                idx += 1
        os.chmod(dst, 0o600)
        return blob_id, h.hexdigest(), size

    def put_bytes(self, data: bytes) -> str:
        with self.scratch(suffix=".bin") as p:
            p.write_bytes(data)
            return self.put_file(p)[0]

    def put_json(self, obj) -> str:
        return self.put_bytes(json.dumps(obj, separators=(",", ":"), default=_json_default).encode())

    def get_json(self, blob_id: str):
        return json.loads(self.get_bytes(blob_id))

    def get_bytes(self, blob_id: str) -> bytes:
        return b"".join(self._iter(blob_id))

    def _iter(self, blob_id: str):
        p = self._path(blob_id)
        with open(p, "rb") as f:
            head = f.read(len(MAGIC))
            if head != MAGIC:  # stored unencrypted
                yield head
                while chunk := f.read(CHUNK):
                    yield chunk
                return
            if not self.aead:
                raise RuntimeError("blob is encrypted but encryption is disabled")
            idx = 0
            saw_final = False
            while True:
                hdr = f.read(4)
                if not hdr:
                    break
                if len(hdr) < 4:
                    raise ValueError("blob truncated")
                (n,) = struct.unpack(">I", hdr)
                nonce = f.read(12)
                ct = f.read(n)
                if len(nonce) < 12 or len(ct) < n:
                    raise ValueError("blob truncated")
                plain = None
                for final in (0, 1):
                    try:
                        plain = self.aead.decrypt(nonce, ct, blob_id.encode() + struct.pack(">IB", idx, final))
                        saw_final = bool(final)
                        break
                    except Exception:
                        continue
                if plain is None:
                    raise ValueError("blob integrity check failed (tampered or wrong key)")
                yield plain
                idx += 1
            if not saw_final:
                raise ValueError("blob truncated")

    def stream(self, blob_id: str):
        yield from self._iter(blob_id)

    @contextlib.contextmanager
    def plain(self, blob_id: str, suffix: str = ""):
        """Decrypt to a private scratch file for tools that need a path; wiped afterwards."""
        with self.scratch(suffix=suffix) as p:
            with open(p, "wb") as f:
                for chunk in self._iter(blob_id):
                    f.write(chunk)
            yield p

    @contextlib.contextmanager
    def scratch(self, suffix: str = ""):
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        os.chmod(d, 0o700)
        p = d / f"f{suffix}"
        try:
            yield p
        finally:
            _wipe_tree(d)

    def scratch_dir(self) -> Path:
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        os.chmod(d, 0o700)
        return d

    def delete(self, blob_id: str | None) -> None:
        if not blob_id:
            return
        p = self._path(blob_id)
        if p.exists():
            _overwrite(p)
            p.unlink()

    def exists(self, blob_id: str) -> bool:
        return self._path(blob_id).exists()

    def wipe_tmp(self) -> None:
        for child in self.tmp.iterdir():
            _wipe_tree(child)


def _json_default(o):
    """numpy scalars / arrays and sets from the detectors."""
    if hasattr(o, "item") and callable(o.item):
        try:
            return o.item()
        except (ValueError, TypeError):
            pass
    if hasattr(o, "tolist"):
        return o.tolist()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def _overwrite(p: Path) -> None:
    try:
        n = p.stat().st_size
        with open(p, "r+b") as f:
            f.write(b"\0" * min(n, 1 << 24))
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass


def _wipe_tree(p: Path) -> None:
    if p.is_file():
        _overwrite(p)
        p.unlink(missing_ok=True)
        return
    if p.is_dir():
        for child in p.rglob("*"):
            if child.is_file():
                _overwrite(child)
        shutil.rmtree(p, ignore_errors=True)


# --- field-level encryption for DB columns holding names (case titles, filenames) --------------

class FieldCipher:
    def __init__(self, key: bytes | None = None):
        k = hashlib.sha256((key or load_master_key()) + b"field-v1").digest()
        self.aead = AESGCM(k)

    def enc(self, s: str | None) -> str | None:
        if s is None:
            return None
        nonce = secrets.token_bytes(12)
        return "e1:" + base64.urlsafe_b64encode(nonce + self.aead.encrypt(nonce, s.encode(), None)).decode()

    def dec(self, s: str | None) -> str | None:
        if s is None or not s.startswith("e1:"):
            return s
        raw = base64.urlsafe_b64decode(s[3:])
        return self.aead.decrypt(raw[:12], raw[12:], None).decode()


_STORAGE: Storage | None = None
_CIPHER: FieldCipher | None = None


def get_storage() -> Storage:
    global _STORAGE
    if _STORAGE is None:
        _STORAGE = Storage()
    return _STORAGE


def get_cipher() -> FieldCipher:
    global _CIPHER
    if _CIPHER is None:
        _CIPHER = FieldCipher()
    return _CIPHER
