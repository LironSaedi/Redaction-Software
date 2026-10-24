# Obscura Redaction Studio — Build Plan

A self-hosted, privacy-first redaction platform modelled on the CaseGuard feature set.
**Everything runs locally** (laptop, workstation, or your own on-prem server). No cloud APIs,
no telemetry, works fully air-gapped once models are downloaded.

## 1. Privacy & deployment model

| Concern | Approach |
|---|---|
| Where processing happens | 100% on the host: OCR (Tesseract), NER (spaCy + GLiNER), vision (YOLO / YuNet), speech (faster-whisper). |
| Network egress | Offline mode forced at startup (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, Ultralytics `sync=False`, telemetry off). Test suite blocks sockets and runs the full pipeline. |
| Data at rest | Originals and working files encrypted with AES-256-GCM; key in a local key file (0600) or env var. |
| Network exposure | Binds `127.0.0.1` by default; set `OBSCURA_HOST=0.0.0.0` for an on-prem LAN server. |
| Frontend | No CDNs, no web fonts, no analytics — static bundle served by the backend. |
| Output | True redaction (content removed, not covered) + metadata scrubbed + automated leak check. |

## 2. Redaction accuracy strategy (the core)

### Text / documents — layered ensemble
1. **Validated pattern recognizers** (35+ types). Every structured identifier is checked with the
   real algorithm, not just a regex: SSN (SSA allocation rules), credit cards (Luhn + issuer ranges),
   IBAN (mod-97), ABA routing (3-7-1 checksum), VIN (ISO 3779 check digit), NPI (Luhn w/ 80840),
   DEA (checksum), Canadian SIN (Luhn), UK NINO, EIN prefixes, IPv4/IPv6 (`ipaddress`), phone numbers
   (Google `libphonenumber`), BTC (base58check/bech32), ETH, MAC, email, URL, dates, ZIP, GPS…
2. **Context scoring** — nearby keywords ("DOB", "acct", "MRN", "plate"…) raise confidence; hard-negative
   cues ("order #", "invoice", "ref") lower it. Context-only types (bank account, MRN, CVV, PIN, driver's
   license, passport, plate) only fire with supporting context so we don't redact every number.
3. **ML NER ensemble** — spaCy transformer NER + GLiNER PII zero-shot model for PERSON, ORG, LOCATION,
   ADDRESS, etc. Spans merged with score fusion; agreement between models raises confidence.
4. **Address parser** — `usaddress` CRF + street-suffix grammar for full street addresses.
5. **Coreference / propagation** — once "John Smith" is found, every "Smith", "John Smith's", "J. Smith"
   in the document is also flagged (catches the mentions NER misses).
6. **User rules** — exact search, custom term lists, regex patterns, templates (fixed-zone redaction).
7. **Verification pass** — after redaction the output is re-extracted (and re-OCR'd for scans) and searched
   for every redacted value; any survivor fails the export.

### Images & video
- Faces: ensemble of YOLO-face + OpenCV YuNet, fused with weighted-box fusion, tiled inference for small
  faces, generous padding.
- Persons, vehicles, screens/monitors/phones, papers/notepads: YOLO11 COCO.
- License plates: dedicated YOLO plate detector + OCR confirmation.
- Video: detection on every frame, ByteTrack-style tracking with Kalman prediction, gap interpolation,
  track persistence (no single-frame "flash" leaks), manual box + CSRT tracker, per-track "keep visible".
- Effects: Gaussian blur, pixelate, solid box; all with feathered padding.
- Leak check: re-detect faces/plates on the redacted output.

### Audio
- faster-whisper with word-level timestamps → text engine → spans mapped to time ranges (with padding)
  → bleep / mute / voice-scramble. SRT/VTT captions, transcript export, Whisper translate-to-English.

## 3. Platform features
- Users & roles: Admin, Supervisor, Redactor, Viewer (RBAC on every endpoint), Argon2 passwords, JWT, lockout.
- Cases / projects ("TeamSpace"): members, assignment, status, notes, due dates.
- Files: PDF, DOCX, XLSX, PPTX, EML/MSG (+ attachments), TXT/CSV/JSON, PNG/JPG/TIFF, MP4/MOV/AVI, WAV/MP3/M4A.
- Review UI: page viewer with overlay boxes, entity list with accept/reject, filter by category, keyboard shortcuts.
- FOIA / PA exemption codes on every redaction, exemption log export.
- Templates (zone redaction), custom lists, regex patterns, Watcher (hot-folder auto-redaction).
- Document tools: Bates stamping, watermark, password protection, merge, split, rotate/reorder/delete pages, OCR.
- Tamper-evident audit log (SHA-256 hash chain) + chain-of-custody hashes of originals and exports.
- Background job queue with progress.

## 4. Tests
- Unit tests for every validator and recognizer.
- **Accuracy benchmark**: synthetic labelled corpus (police reports, medical forms, bank statements, emails,
  resumes) with gold spans → precision / recall / F1 per entity type, with minimum-recall gates.
- Hard-negative set (order numbers, invoice IDs, timestamps, versions) to measure over-redaction.
- Redaction integrity tests: underlying text removed, images under boxes destroyed, metadata stripped,
  OCR'd scans redacted, DOCX headers/footers/comments cleaned.
- Video/image tests with real faces; audio tests using macOS `say` TTS.
- API tests: auth, RBAC, cases, upload → detect → apply → export, audit chain integrity.
- Privacy test: socket egress blocked during the whole pipeline.

## 5. Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy + SQLite (swap to Postgres for multi-user servers).
- Frontend: React + TypeScript + Vite, served as static files by the backend.
