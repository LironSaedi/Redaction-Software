"""True-redaction guarantees for PDFs: every hiding place for PII must be emptied."""
import io
import re

import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

from obscura.detection.text.engine import AnalyzeOptions, SearchTerm
from obscura.redact.model import ExportOptions, RedactionStyle
from obscura.redact.pdf import PdfDocument, verify_pdf

SSN = "523-71-9921"
NAME = "Maria Delgado"
RULES = AnalyzeOptions(use_spacy=False, use_gliner=False)


def all_text(path, password=None) -> str:
    d = fitz.open(str(path))
    if password:
        d.authenticate(password)
    txt = " ".join(p.get_text("text", flags=fitz.TEXT_PRESERVE_WHITESPACE) for p in d)
    for p in d:
        for a in p.annots() or []:
            txt += " " + (a.info.get("content") or "")
        for w in p.widgets() or []:
            txt += " " + str(w.field_value or "")
    txt += " " + " ".join(str(v) for v in (d.metadata or {}).values() if v)
    txt += " " + (d.get_xml_metadata() or "")
    txt += " " + " ".join(t[1] for t in d.get_toc())
    for name in d.embfile_names():
        txt += " " + d.embfile_get(name).decode("latin-1", "ignore")
    d.close()
    return txt


def raw_bytes(path) -> bytes:
    """Every stream decompressed — what a forensic tool would see."""
    d = fitz.open(str(path))
    out = bytearray()
    for x in range(1, d.xref_length()):
        try:
            out += d.xref_object(x).encode("latin-1", "ignore")
            if d.xref_is_stream(x):
                out += d.xref_stream(x) or b""
        except Exception:
            pass
    d.close()
    return bytes(out)


def redact(src, out, terms=None, opts=None):
    doc = PdfDocument(src)
    doc.extract(ocr="auto")
    dets = doc.analyze(RULES)
    if terms:
        dets += doc.search(terms)
    rep = doc.apply(dets, out, opts or ExportOptions())
    doc.close()
    return rep, dets


@pytest.fixture
def base_pdf(tmp_path):
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), f"Patient: {NAME}", fontsize=11)
    p.insert_text((72, 90), f"SSN: {SSN}", fontsize=11)
    p.insert_text((72, 108), "Diagnosis: cervical strain. Follow up in two weeks.", fontsize=11)
    path = tmp_path / "base.pdf"
    doc.set_metadata({"author": NAME, "title": f"Records of {NAME}", "subject": SSN, "keywords": "PI"})
    doc.save(str(path))
    return path


def test_visible_text_removed_and_rest_kept(base_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    rep, _ = redact(base_pdf, out)
    t = all_text(out)
    assert SSN not in t and NAME not in t and "Delgado" not in t
    assert "cervical strain" in t and "Follow up in two weeks" in t
    assert rep["verification"]["passed"], rep["verification"]


def test_metadata_scrubbed(base_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    redact(base_pdf, out)
    meta = fitz.open(str(out)).metadata
    assert not any(v for k, v in meta.items() if k not in ("format", "encryption"))


def test_forensic_bytes_clean(base_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    redact(base_pdf, out)
    raw = raw_bytes(out)
    assert SSN.encode() not in raw and b"Delgado" not in raw and b"9921" not in raw


def test_invisible_ocr_layer_text(tmp_path):
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), "Visible heading only", fontsize=11)
    p.insert_text((72, 200), f"SSN {SSN} hidden", fontsize=11, render_mode=3)  # invisible text
    src = tmp_path / "inv.pdf"
    doc.save(str(src))
    out = tmp_path / "o.pdf"
    redact(src, out)
    assert SSN not in all_text(out) and SSN.encode() not in raw_bytes(out)


def test_white_and_tiny_text(tmp_path):
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), f"SSN {SSN}", fontsize=11, color=(1, 1, 1))
    p.insert_text((72, 100), f"Patient: {NAME}", fontsize=1)
    src = tmp_path / "white.pdf"
    doc.save(str(src))
    out = tmp_path / "o.pdf"
    redact(src, out)
    t = all_text(out)
    assert SSN not in t and "Delgado" not in t


def test_annotations_and_comments(tmp_path, base_pdf):
    doc = fitz.open(str(base_pdf))
    p = doc[0]
    a = p.add_text_annot((300, 300), f"Reviewer note: call {NAME} at 512-555-0187")
    a.set_info(title="Paralegal Jane", content=f"call {NAME} at 512-555-0187")
    p.add_freetext_annot(fitz.Rect(300, 400, 500, 440), f"SSN {SSN}")
    src = tmp_path / "annots.pdf"
    doc.save(str(src))
    out = tmp_path / "o.pdf"
    rep, _ = redact(src, out)
    t = all_text(out)
    assert "512-555-0187" not in t and SSN not in t and "Paralegal Jane" not in t
    assert not list(fitz.open(str(out))[0].annots())


def test_form_fields(tmp_path):
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), "Patient intake form", fontsize=12)
    for i, (name, val) in enumerate([("patient_name", NAME), ("ssn", SSN), ("phone", "512-555-0187")]):
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.rect = fitz.Rect(150, 100 + i * 30, 400, 120 + i * 30)
        w.field_value = val
        p.add_widget(w)
        p.insert_text((72, 115 + i * 30), {"patient_name": "Name:", "ssn": "SSN:", "phone": "Phone:"}[name], fontsize=10)
    src = tmp_path / "form.pdf"
    doc.save(str(src))
    out = tmp_path / "o.pdf"
    redact(src, out)
    t = all_text(out)
    assert SSN not in t and NAME not in t and "512-555-0187" not in t
    assert not list(fitz.open(str(out))[0].widgets())


def test_bookmarks_embedded_files_js_xmp(base_pdf, tmp_path):
    doc = fitz.open(str(base_pdf))
    doc.set_toc([[1, f"Records — {NAME}", 1], [2, f"SSN {SSN}", 1]])
    doc.embfile_add("notes.txt", f"client {NAME} ssn {SSN}".encode())
    doc.set_xml_metadata(f"<x:xmpmeta xmlns:x='adobe:ns:meta/'><rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>"
                         f"<rdf:Description><dc:creator xmlns:dc='http://purl.org/dc/elements/1.1/'>{NAME}</dc:creator>"
                         f"</rdf:Description></rdf:RDF></x:xmpmeta>")
    xref = doc.get_new_xref()
    doc.update_object(xref, "<< /S /JavaScript /JS (app.alert('523-71-9921')) >>")
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"{xref} 0 R")
    src = tmp_path / "carriers.pdf"
    doc.save(str(src))
    out = tmp_path / "o.pdf"
    rep, _ = redact(src, out)
    d = fitz.open(str(out))
    assert d.get_toc() == [] and d.embfile_count() == 0 and not d.get_xml_metadata()
    assert SSN.encode() not in raw_bytes(out) and b"Delgado" not in raw_bytes(out)
    assert rep["verification"]["passed"], rep["verification"]


def test_hidden_optional_content_layer(tmp_path):
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), "Public layer text", fontsize=11)
    ocg = doc.add_ocg("Confidential", on=False)
    p.insert_text((72, 120), f"SSN {SSN} in a hidden layer", fontsize=11, oc=ocg)
    src = tmp_path / "ocg.pdf"
    doc.save(str(src))
    out = tmp_path / "o.pdf"
    redact(src, out)
    assert SSN.encode() not in raw_bytes(out)


def test_text_outside_visible_area(tmp_path):
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), "Visible", fontsize=11)
    p.set_cropbox(fitz.Rect(0, 0, p.rect.width, 400))
    p.insert_text((72, 600), f"SSN {SSN} below the crop box", fontsize=11)
    src = tmp_path / "crop.pdf"
    doc.save(str(src))
    out = tmp_path / "o.pdf"
    redact(src, out)
    assert SSN.encode() not in raw_bytes(out)


def _scan_page_pdf(tmp_path, lines, angle=0.0):
    img = Image.new("L", (1700, 2200), 255)
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    for i, ln in enumerate(lines):
        dr.text((150, 200 + i * 90), ln, fill=0, font=font)
    if angle:
        img = img.rotate(angle, fillcolor=255, resample=Image.BICUBIC)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    doc = fitz.open()
    p = doc.new_page(width=612, height=792)
    p.insert_image(p.rect, stream=buf.getvalue())
    path = tmp_path / f"scan_{angle}.pdf"
    doc.save(str(path))
    return path


@pytest.mark.parametrize("angle", [0.0, 1.2, -2.0])
def test_scanned_page_pixels_destroyed(tmp_path, angle):
    src = _scan_page_pdf(tmp_path, ["MEDICAL RECORD", f"Patient: {NAME}", f"SSN: {SSN}", "Phone: (512) 555-0187",
                                    "Assessment: lumbar strain"], angle)
    out = tmp_path / "o.pdf"
    rep, dets = redact(src, out)
    assert any(d.entity == "SSN" for d in dets), [(d.entity, d.text) for d in dets]
    from obscura.redact import ocr
    d = fitz.open(str(out))
    pix = d[0].get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72))
    words = " ".join(w.text for w in ocr.ocr_image(Image.open(io.BytesIO(pix.tobytes("png"))), dpi=300))
    norm = re.sub(r"[^0-9a-z]", "", words.lower())
    assert "523719921" not in norm and "delgado" not in norm and "5125550187" not in norm
    assert "lumbar" in norm  # unredacted content survives
    assert rep["verification"]["passed"], rep["verification"]


def test_partial_redaction_keeps_last4(base_pdf, tmp_path):
    doc = PdfDocument(base_pdf)
    doc.extract()
    dets = doc.analyze(AnalyzeOptions(profile="frcp_5_2", use_spacy=False, use_gliner=False))
    out = tmp_path / "o.pdf"
    doc.apply(dets, out)
    t = all_text(out)
    assert "9921" in t and "523-71" not in t


def test_labels_bates_watermark_password(base_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    opts = ExportOptions(style=RedactionStyle(label="exemption"), bates_prefix="DELG_", bates_start=7,
                         watermark="CONFIDENTIAL", password="Pa55word!x")
    rep, _ = redact(base_pdf, out, opts=opts)
    d = fitz.open(str(out))
    assert d.needs_pass and d.authenticate("Pa55word!x")
    t = d[0].get_text()
    assert "DELG_000007" in t and "(b)(6)" in t and SSN not in t
    assert rep["verification"]["passed"]


def test_flatten_to_image(base_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    redact(base_pdf, out, opts=ExportOptions(flatten_to_image=True))
    d = fitz.open(str(out))
    assert d[0].get_text().strip() == "" and len(d[0].get_images()) == 1


def test_search_terms_redact_all_instances(tmp_path):
    doc = fitz.open()
    for i in range(3):
        p = doc.new_page()
        p.insert_text((72, 72 + i * 20), "Project Falcon status update", fontsize=11)
    src = tmp_path / "s.pdf"
    doc.save(str(src))
    out = tmp_path / "o.pdf"
    rep, dets = redact(src, out, terms=[SearchTerm("Project Falcon")])
    assert "Falcon" not in all_text(out) and "status update" in all_text(out)


def test_rotated_page(tmp_path):
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), f"SSN: {SSN}", fontsize=11)
    p.set_rotation(90)
    src = tmp_path / "rot.pdf"
    doc.save(str(src))
    out = tmp_path / "o.pdf"
    rep, _ = redact(src, out)
    assert SSN not in all_text(out) and rep["verification"]["passed"]


def test_verifier_flags_unredacted_output(base_pdf, tmp_path):
    doc = PdfDocument(base_pdf)
    doc.extract()
    dets = doc.analyze(RULES)
    rep = verify_pdf(base_pdf, dets, doc.pages)  # verify the ORIGINAL as if it were the export
    assert not rep["passed"]
    kinds = {i["type"] for i in rep["issues"]}
    assert "value_still_present" in kinds and "metadata_present" in kinds


def test_many_pages_performance(tmp_path):
    import time
    doc = fitz.open()
    for i in range(150):
        p = doc.new_page()
        p.insert_text((72, 72), f"Patient: {NAME}   MRN: 00483921   Page {i + 1}", fontsize=10)
        p.insert_text((72, 100), "Daily note: patient tolerated therapy well.", fontsize=10)
    src = tmp_path / "big.pdf"
    doc.save(str(src))
    t = time.perf_counter()
    out = tmp_path / "o.pdf"
    rep, dets = redact(src, out)
    assert time.perf_counter() - t < 60
    assert "Delgado" not in all_text(out) and "00483921" not in all_text(out)
    assert len(rep["pages_touched"]) == 150
