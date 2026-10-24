"""Email (.eml / .msg) redaction.

An email is converted to a PDF "print" (headers + body) which then goes through the normal PDF
pipeline, so reviewers see exactly what will be released. Every attachment is extracted and processed
by its own handler. Transport headers that are never shown in a print (Received, Message-ID,
X-Originating-IP, DKIM…) are dropped entirely — they carry IP addresses and host names.
"""
from __future__ import annotations

import email
import html
import re
from dataclasses import dataclass, field
from email import policy
from pathlib import Path

import pymupdf as fitz

SHOWN_HEADERS = ("From", "Sent", "Date", "To", "Cc", "Bcc", "Reply-To", "Subject")


@dataclass
class ParsedEmail:
    headers: list[tuple[str, str]]
    body: str
    attachments: list[tuple[str, bytes]] = field(default_factory=list)


def _html_to_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", h)
    h = re.sub(r"(?i)</t[dh]>", "\t", h)
    h = re.sub(r"<[^>]+>", "", h)
    h = html.unescape(h)
    h = re.sub(r"[ \t ]+", " ", h)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", h).strip()


def parse_eml(data: bytes) -> ParsedEmail:
    msg = email.message_from_bytes(data, policy=policy.default)
    headers = [(h, str(msg.get(h))) for h in SHOWN_HEADERS if msg.get(h)]
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        content = body_part.get_content()
        body = _html_to_text(content) if body_part.get_content_type() == "text/html" else content
    atts = []
    for part in msg.iter_attachments():
        name = part.get_filename() or f"attachment-{len(atts) + 1}"
        payload = part.get_payload(decode=True) or b""
        if part.get_content_type() == "message/rfc822":
            inner = part.get_payload(0) if part.is_multipart() else None
            payload = inner.as_bytes() if inner is not None else payload
            name = name if name.endswith(".eml") else name + ".eml"
        atts.append((Path(name).name, payload))
    return ParsedEmail(headers, body, atts)


def parse_msg(path: str | Path) -> ParsedEmail:
    import extract_msg
    m = extract_msg.openMsg(str(path))
    headers = [("From", m.sender or ""), ("Sent", str(m.date or "")), ("To", m.to or ""), ("Cc", m.cc or ""),
               ("Bcc", getattr(m, "bcc", "") or ""), ("Subject", m.subject or "")]
    headers = [(k, v) for k, v in headers if v]
    body = m.body or ""
    if not body.strip() and getattr(m, "htmlBody", None):
        hb = m.htmlBody
        body = _html_to_text(hb.decode("utf-8", "ignore") if isinstance(hb, bytes) else hb)
    atts = []
    for a in m.attachments:
        data = a.data
        name = a.longFilename or a.shortFilename or f"attachment-{len(atts) + 1}"
        if hasattr(data, "asBytes"):
            data = data.asBytes()
        if isinstance(data, bytes):
            atts.append((Path(name).name, data))
    m.close()
    return ParsedEmail(headers, body, atts)


def email_to_pdf(parsed: ParsedEmail, out: str | Path) -> Path:
    """Render an email to a clean, paginated PDF print."""
    doc = fitz.open()
    W, H, M = 612, 792, 54
    fs, lh = 9.5, 13.0
    page = doc.new_page(width=W, height=H)
    y = M

    def line(text: str, bold: bool = False) -> None:
        nonlocal page, y
        import textwrap
        for ln in textwrap.wrap(text, 100, replace_whitespace=False, drop_whitespace=False) or [""]:
            if y + lh > H - M:
                page = doc.new_page(width=W, height=H)
                y = M
            if ln.strip():
                page.insert_text(fitz.Point(M, y + fs), ln.replace("\t", "    "), fontsize=fs,
                                 fontname="hebo" if bold else "helv")
            y += lh

    for k, v in parsed.headers:
        line(f"{k}: {v}", bold=False)
    if parsed.attachments:
        line("Attachments: " + "; ".join(n for n, _ in parsed.attachments))
    line("-" * 96)
    for para in parsed.body.replace("\r\n", "\n").split("\n"):
        line(para)
    out = Path(out)
    doc.save(str(out), garbage=3, deflate=True)
    doc.close()
    return out


def load_email(path: str | Path) -> ParsedEmail:
    path = Path(path)
    if path.suffix.lower() == ".msg":
        return parse_msg(path)
    return parse_eml(path.read_bytes())
