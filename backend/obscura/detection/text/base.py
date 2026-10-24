"""Core types shared by every text detector."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class Span:
    start: int
    end: int
    entity: str
    score: float
    source: str
    text: str = ""
    explanation: str = ""
    meta: dict = field(default_factory=dict)

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: "Span") -> bool:
        return self.start <= other.start and other.end <= self.end

    @property
    def length(self) -> int:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "start": self.start, "end": self.end, "entity": self.entity, "score": round(self.score, 4),
            "source": self.source, "text": self.text, "explanation": self.explanation, "meta": self.meta,
        }


# Characters removed before matching (zero-width, soft hyphen, BOM, bidi controls).
_DROP = {"​", "‌", "‍", "⁠", "﻿", "­", "‎", "‏", "‪", "‫",
         "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩"}
_DASHES = set("‐‑‒–—―−﹘﹣－")
_SPACES = set("               　\t")
_QUOTES = {"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "´": "'", "`": "'",
           "“": '"', "”": '"', "„": '"', "″": '"'}


class NormText:
    """A matching-friendly copy of a text with an exact map back to original offsets.

    * zero-width / invisible characters are removed (so "123​-45-6789" still matches)
    * every dash variant becomes "-", every space variant becomes " ", smart quotes become ASCII
    * full-width / compatibility forms are folded with NFKC when they fold to a single char
    """

    def __init__(self, text: str):
        self.original = text
        out: list[str] = []
        idx: list[int] = []
        for i, ch in enumerate(text):
            if ch in _DROP:
                continue
            if ch in _DASHES:
                ch = "-"
            elif ch in _SPACES:
                ch = " "
            elif ch in _QUOTES:
                ch = _QUOTES[ch]
            elif ord(ch) > 127:
                folded = unicodedata.normalize("NFKC", ch)
                if len(folded) == 1:
                    ch = folded
            out.append(ch)
            idx.append(i)
        self.text = "".join(out)
        self._idx = idx
        self.lower = self.text.lower()

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        if not self._idx:
            return 0, 0
        s = self._idx[min(start, len(self._idx) - 1)]
        e = self._idx[min(end, len(self._idx)) - 1] + 1 if end > 0 else s
        return s, e


# OCR commonly confuses these letters with digits inside numbers.
_OCR_DIGIT = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "i": "1",
                            "Z": "2", "z": "2", "S": "5", "s": "5", "B": "8", "G": "6", "b": "6", "g": "9",
                            "q": "9", "T": "7"})
# a run may start or end with a confusable letter only at a word edge, so "(cell) 2l0-455" does not swallow
# "ll" and "...0117 SRC19" does not take the "S"
_NUMERICISH = re.compile(r"(?:[0-9]|(?<![A-Za-z'’])[OoDQIl|iZzSsBGbgqT])[0-9OoDQIl|iZzSsBGbgqT \-./()]{6,24}"
                         r"(?:[0-9]|[OoDQIl|iZzSsBGbgqT](?![A-Za-z]))")


_ID_SHAPES = re.compile(r"\d{3}-\d{2}-\d{4}|(?:1[ .-])?\(?\d{3}\)?[ .-]?\d{3}[ .-]\d{4}|(?:\d{4}[ -]){3}\d{4}|"
                        r"\d{1,2}/\d{1,2}/\d{2,4}|\d{9,12}")


def ocr_digit_variant(text: str) -> str:
    """Same-length copy of ``text`` where letter/digit OCR confusions inside mostly-numeric runs
    are mapped to digits. Used for a second pass of the numeric recognizers on scanned pages."""
    chars = list(text)
    for m in _NUMERICISH.finditer(text):
        seg = m.group()
        if _numeric_run(seg):
            chars[m.start():m.end()] = list(_to_digits(seg))
            continue
        # "O4/Ol/2O25 - O4/3O/2O25": judge each space-separated piece on its own
        for p in re.finditer(r"\S+", seg):
            if len(p.group()) >= 6 and _numeric_run(p.group()):
                a = m.start() + p.start()
                chars[a:a + len(p.group())] = list(_to_digits(p.group()))
    return "".join(chars)


def _to_digits(seg: str) -> str:
    # whole words between the numbers stay words: "00847721 DOB 04/17/1986", "SSN 523-71-99Z1"
    # ("Ol" / "lI" — only 0/1 look-alikes — are still digits)
    return re.sub(r"[A-Za-z0-9|]+", lambda t: t.group() if (len(t.group()) >= 2 and t.group().isalpha() and
                                                            re.search(r"[^OolI|]", t.group()))
                  else t.group().translate(_OCR_DIGIT), seg)


def _numeric_run(seg: str) -> bool:
    n_digits = sum(c.isdigit() for c in seg)
    n_alnum = sum(c.isalnum() or c == "|" for c in seg)
    if not n_alnum:
        return False
    fixed = seg.translate(_OCR_DIGIT)
    # at least 70% real digits and few confusable letters avoids turning words into numbers;
    # a run that becomes a well-known identifier shape (SSN, phone, card, date) may have up to 4
    shape = bool(_ID_SHAPES.fullmatch(fixed.strip(" .-/()")))
    return (n_digits / n_alnum >= 0.7 and n_alnum - n_digits <= max(2, n_alnum // 3)) or \
        (shape and n_digits / n_alnum >= 0.5 and n_alnum - n_digits <= 4)


# Latin letters incl. accents (Python's re has no \p{Lu}); used by every name pattern.
UP = "A-ZÀ-ÖØ-ÞĀĂĄĆĈĊČĎĐĒĔĖĘĚĜĞĠĢĤĦĨĪĬĮİĴĶĹĻĽĿŁŃŅŇŊŌŎŐŒŔŖŘŚŜŞŠŢŤŦŨŪŬŮŰŲŴŶŸŹŻŽ"
LO = "a-zß-öø-ÿāăąćĉċčďđēĕėęěĝğġģĥħĩīĭįıĵķĺļľŀłńņňŋōŏőœŕŗřśŝşšţťŧũūŭůűųŵŷźżž"
# ---- OCR noise ---------------------------------------------------------------------------------
_OCR_LETTER = str.maketrans({"0": "o", "1": "l", "5": "s", "|": "l", "$": "s", "3": "e", "4": "a", "7": "t", "8": "B"})
_WORDISH = re.compile(r"[A-Za-z0-9|$]{2,}")
_NOISE = re.compile(r"(?<![0-9])[A-Za-z]+[0O1l|][A-Za-z]+|\b[A-Za-z]*[0-9][A-Za-z]{2,}\b|\b\d+[lIO]\d+\b|\b[lIO]\d{2,}")


_LINE_NO = re.compile(r"(?m)^([ \t]{0,4})([1-9]|1\d|2[0-8])(?=[ \t]{2,}\S|[ \t]*$)")


def blank_line_numbers(text: str) -> str:
    """Transcript pages number every line ("14        Q.   Did Swiftline …"). Phrases that wrap onto the next
    line ("I started\n 4   at Swiftline") only match once the numbers are gone, so a transcript gets a
    same-length copy with its line numbers replaced by spaces. Other documents are returned unchanged."""
    hits = list(_LINE_NO.finditer(text))
    lines = text.count("\n") + 1
    if len(hits) < 8 or len(hits) < lines * 0.3:
        return text
    nums = [int(m.group(2)) for m in hits]
    steps = sum(1 for a, b in zip(nums, nums[1:]) if b == a + 1 or (b == 1 and a >= 20))
    if steps < len(nums) * 0.6:
        return text  # not a running 1..25 sequence: a numbered list or a table
    chars = list(text)
    for m in hits:
        chars[m.start(2):m.end(2)] = " " * (m.end(2) - m.start(2))
    return "".join(chars)


def looks_ocr_noisy(text: str) -> bool:
    """Heuristic: words with embedded digits ("Ph0ne", "f0r", "S5N") or numbers with embedded letters
    ("2l0-455", "1-8OO") at a rate real typing never produces."""
    sample = text[:200_000]
    words = len(re.findall(r"[A-Za-z]{2,}", sample)) or 1
    noisy = 0
    for m in _NOISE.finditer(sample):
        tok = m.group()
        if re.fullmatch(r"[A-Za-z]+\d+", tok) or re.fullmatch(r"\d+[A-Za-z]{1,3}", tok):
            continue  # "COVID19", "B12", "4th", "2nd", "10mg" are normal
        if re.search(r"[a-z]0[a-z]|[a-z]1[a-z]|\d[lO]\d|[A-Za-z]5[A-Za-z]", tok):
            noisy += 1
    return noisy >= 3 and noisy / words > 0.004


def ocr_clean_variant(text: str) -> str:
    """Same-length copy of OCR text with both kinds of confusion undone: digits inside words become letters
    ("Ph0ne" → "Phone", "Li1y" → "Lily", "1itt1e gir1" → "little girl") and letters inside numbers become
    digits ("2l0-455-09l2")."""
    chars = list(ocr_digit_variant(text))
    for m in _WORDISH.finditer(text):
        tok = m.group()
        if 3 <= len(tok) <= 8 and re.fullmatch(r"[0-9OoIl|]+", tok):
            # short numbers too small for the run rule: "45l2", "O47l", "2O418"
            n = sum(c.isdigit() for c in tok)
            if n >= 2 and n >= len(tok) - n:
                chars[m.start():m.end()] = list(tok.translate(_OCR_DIGIT))
            continue
        if re.fullmatch(r"[lI|][0-9]{1,4}[A-Z]?", tok):
            chars[m.start()] = "1"  # unit / room numbers: "Apt l2C"
            continue
        if re.fullmatch(r"[A-Z]*l[A-Zl]*", tok) and sum(c.isupper() for c in tok) >= 2:
            chars[m.start():m.end()] = list(tok.replace("l", "I"))  # "AUSTlN", "CLAlM", "lNS" in caps lines
            continue
        if _ocr_word(tok):
            fixed = tok.translate(_OCR_LETTER)
            # keep case style: an all-caps word stays all caps
            if tok.upper() == tok:
                fixed = fixed.upper()
            chars[m.start():m.end()] = list(fixed)
    # a state code before a ZIP code: "P0RTLAND 0R 97202" → "OR", "C0 80202" → "CO"
    for m in _OCR_STATE.finditer(text):
        fixed = m.group(1).translate(_OCR_LETTER).upper()
        if fixed in _US_STATES:
            chars[m.start(1):m.end(1)] = list(fixed)
    return "".join(chars)


_OCR_STATE = re.compile(r"(?<![A-Za-z0-9])([A-Z0-9|]{2})(?=[ \t,]+[0-9OIl]{5}(?:-[0-9OIl]{4})?(?![0-9]))")
_US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
                 "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR GU VI".split())


def _ocr_word(tok: str) -> bool:
    """Is this token a word with OCR digit confusions (rather than a real code such as "B12", "COVID19",
    "A04418277" or "SFD-0117")?"""
    letters = sum(c.isalpha() for c in tok)
    digits = [c for c in tok if not c.isalpha()]
    if not digits or not letters:
        return False
    confusable = all(c in "01|$5" for c in digits)
    lower = sum(c.islower() for c in tok)
    if len(tok) == 2:  # "0f", "t0", "0n", "1t"
        return lower == 1 and digits[0] in "01"
    if tok[0].isdigit() or tok[0] in "|$":
        # "1itt1e", "1ock", "0ff1ce": a leading 1/0 only when lowercase letters follow
        return confusable and tok[0] in "01|" and tok[1].islower() and lower >= 2
    if re.fullmatch(r"[A-Za-z]+\d+", tok):
        # trailing digits are usually real ("B12", "COVID19", "bluejay55"); a single trailing 0/1 after a
        # lowercase word is OCR ("wh0", "gir1", "margina1", "wa11"), as is "W00" in an all-caps line
        tail = len(tok) - letters
        return (tail <= 2 and set(digits) <= set("01") and tok[-tail - 1].islower() and lower >= 2) or \
            (len(tok) == 3 and letters == 1 and set(digits) == {"0"} and tok[0].isupper())
    if confusable:
        return len(digits) <= letters  # "D0y1e", "Vi11al0b0s", "SE0UL", "F00D"
    return letters >= 2 and len(digits) <= max(1, letters // 2)


_WORD = re.compile(r"\w+(?:['’]\w+)?", re.UNICODE)


def line_bounds(text: str, pos: int) -> tuple[int, int]:
    s = text.rfind("\n", 0, pos) + 1
    e = text.find("\n", pos)
    return s, (len(text) if e < 0 else e)


def window(text: str, start: int, end: int, before: int = 60, after: int = 30, prev_line: bool = True) -> str:
    """Context window around a match: the preceding text on the same line, the line above
    (table headers / form labels usually sit there) and a little trailing text."""
    ls, le = line_bounds(text, start)
    b = max(ls, start - before)
    left = text[b:start]
    if prev_line and ls > 0:
        pls, ple = line_bounds(text, ls - 1)
        left = text[max(pls, ple - 120):ple] + "\n" + left
    right = text[end:min(le, end + after)]
    return left + " \x00 " + right


def is_title_word(w: str) -> bool:
    return bool(w) and w[0].isupper() and (len(w) == 1 or not w[1:].isupper() or len(w) <= 3)
