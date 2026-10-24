"""Encrypted storage, field encryption, audit chain, passwords."""
import os
import secrets
import struct

import pytest

from obscura.storage import CHUNK, MAGIC, FieldCipher, Storage


@pytest.fixture
def st(tmp_path):
    return Storage(root=tmp_path / "data" / "blobs", key=secrets.token_bytes(32), encrypt=True)


@pytest.mark.parametrize("n", [0, 1, 17, CHUNK - 1, CHUNK, CHUNK + 1, 2 * CHUNK, 3 * CHUNK + 5])
def test_roundtrip(st, tmp_path, n):
    src = tmp_path / "s.bin"
    data = os.urandom(n)
    src.write_bytes(data)
    bid, sha, size = st.put_file(src)
    assert st.get_bytes(bid) == data and size == n
    import hashlib
    assert sha == hashlib.sha256(data).hexdigest()


def test_ciphertext_has_no_plaintext(st, tmp_path):
    src = tmp_path / "s.txt"
    src.write_bytes(b"SSN 523-71-9921 Patient Mary Johnson " * 1000)
    bid, _, _ = st.put_file(src)
    raw = st._path(bid).read_bytes()
    assert raw.startswith(MAGIC) and b"523-71-9921" not in raw and b"Johnson" not in raw


def test_wrong_key_fails(st, tmp_path):
    src = tmp_path / "s.bin"
    src.write_bytes(b"secret")
    bid, _, _ = st.put_file(src)
    other = Storage(root=st.root, key=secrets.token_bytes(32), encrypt=True)
    with pytest.raises(ValueError):
        other.get_bytes(bid)


@pytest.mark.parametrize("pos", [5, 9, 20, 40])
def test_bitflip_detected(st, tmp_path, pos):
    src = tmp_path / "s.bin"
    src.write_bytes(os.urandom(5000))
    bid, _, _ = st.put_file(src)
    p = st._path(bid)
    b = bytearray(p.read_bytes())
    b[pos] ^= 0x01
    p.write_bytes(bytes(b))
    with pytest.raises((ValueError, struct.error)):
        st.get_bytes(bid)


def test_chunk_swap_detected(st, tmp_path):
    src = tmp_path / "s.bin"
    src.write_bytes(os.urandom(3 * CHUNK))
    bid, _, _ = st.put_file(src)
    raw = st._path(bid).read_bytes()
    pos, chunks = len(MAGIC), []
    while pos < len(raw):
        n = struct.unpack(">I", raw[pos:pos + 4])[0]
        chunks.append(raw[pos:pos + 16 + n])
        pos += 16 + n
    st._path(bid).write_bytes(MAGIC + chunks[1] + chunks[0] + b"".join(chunks[2:]))
    with pytest.raises(ValueError):
        st.get_bytes(bid)


def test_plain_context_wipes(st, tmp_path):
    src = tmp_path / "s.bin"
    src.write_bytes(b"x" * 100)
    bid, _, _ = st.put_file(src)
    with st.plain(bid, ".bin") as p:
        assert p.read_bytes() == b"x" * 100
        saved = p
    assert not saved.exists()


def test_delete_removes(st, tmp_path):
    src = tmp_path / "s.bin"
    src.write_bytes(b"abc")
    bid, _, _ = st.put_file(src)
    st.delete(bid)
    assert not st.exists(bid)


def test_json_roundtrip(st):
    obj = {"a": [1, 2, {"b": "Ž"}]}
    assert st.get_json(st.put_json(obj)) == obj


@pytest.mark.parametrize("s", ["", "Smith v. Jones", "Ñandú — 日本", "x" * 5000])
def test_field_cipher(s):
    fc = FieldCipher(secrets.token_bytes(32))
    c = fc.enc(s)
    assert c.startswith("e1:") and (s == "" or s not in c) and fc.dec(c) == s


def test_field_cipher_is_randomised():
    fc = FieldCipher(secrets.token_bytes(32))
    assert fc.enc("same") != fc.enc("same")


@pytest.mark.parametrize("pw,ok", [("Str0ng!Passphrase", True), ("short1!A", False), ("alllowercaseletters", False),
                                   ("NoDigitsOrSymbolsHere", False), ("admin-Password1!", False), ("Correct Horse 9 Battery", True)])
def test_password_policy(pw, ok):
    from obscura.security import password_problems
    assert (not password_problems(pw, "admin")) is ok


def test_hash_verify():
    from obscura.security import hash_password, verify_password
    h = hash_password("Str0ng!Passphrase")
    assert h.startswith("$argon2id$") and verify_password("Str0ng!Passphrase", h) and not verify_password("wrong", h)
    assert not verify_password("x", "garbage")


def test_audit_chain_detects_tampering(tmp_path):
    from obscura import db as dbm
    from obscura.audit import record, verify_chain
    dbm.init_db(f"sqlite:///{tmp_path / 'a.db'}")
    for i in range(10):
        record("test_event", None, "x", i, None, {"n": i})
    with dbm.tx() as s:
        assert verify_chain(s)["valid"]
    with dbm.tx() as s:
        ev = s.get(dbm.AuditEvent, 5)
        ev.details = {"n": 999}
    with dbm.tx() as s:
        res = verify_chain(s)
        assert not res["valid"] and res["broken_at"] == 5
    with dbm.tx() as s:
        ev = s.get(dbm.AuditEvent, 5)
        ev.details = {"n": 4}
    with dbm.tx() as s:
        assert verify_chain(s)["valid"]
        s.delete(s.get(dbm.AuditEvent, 7))
    with dbm.tx() as s:
        res = verify_chain(s)
        assert not res["valid"] and res["broken_at"] == 8
    dbm.init_db()  # back to the test-run default
