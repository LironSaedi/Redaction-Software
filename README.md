# Obscura Redaction Studio

Self-hosted redaction for legal and medical work: PDFs (native and scanned), Word / Excel / PowerPoint,
email (EML / MSG with attachments), images, video and audio. It finds personal, medical (PHI), payment and
privileged information, lets a reviewer accept or reject each finding, and exports files where the
redacted content is **removed**, not just covered up. Each export is then checked for leaks before you can
download it.

**Nothing leaves your machine.** All OCR, language models, face/plate detection and speech recognition run
locally. There are no cloud APIs, no telemetry and no CDN; it works on a computer with no internet at all.

---

## 1. Where it runs

The same install works three ways. Pick one:

| Setup | Who it's for | How people reach it |
|---|---|---|
| **A. One computer** | a solo attorney / one reviewer | `http://127.0.0.1:8600` on that computer only (the default) |
| **B. Office server** (recommended for teams) | a firm or practice, several reviewers | `https://redact.yourfirm.lan:8600` from office computers, over your own network with HTTPS |
| **C. Air-gapped server** | the most sensitive matters | like B, on a machine or network with no internet connection |

In every case, documents, detections, the database and the encryption keys stay in one folder (`backend/data/`)
on that machine.

**Why B for teams:** case files live on one machine your firm controls. Nobody keeps copies on a laptop, and
users, roles and the audit log are shared. Staff use a browser; nothing is installed on their computers.

### What protects the data
- **No outbound traffic:** offline mode is forced for every model library at start-up. Set `OBSCURA_BLOCK_NET=1`
  and the process also refuses every outbound network connection (loopback and incoming browser connections
  still work). The privacy test suite runs the whole pipeline with that block on.
- **Encrypted at rest:** originals, working files and exports are encrypted with AES-256-GCM. Case names, file
  names and notes are also encrypted inside the database. The key is `backend/data/keys/master.key` (mode 0600),
  or you can supply it with `OBSCURA_MASTER_KEY`.
- **Accounts:**
  - No sign-in is needed on the computer running Obscura (configurable). Every other computer signs in.
  - Passwords are hashed with Argon2id and must be 12+ characters. Accounts lock after 5 failed sign-ins.
  - There are four roles: admin / supervisor / redactor / viewer. Viewers only ever see verified redacted exports.
- **Audit log:** every view, change, export and download is recorded in a hash chain, so tampering can be
  detected (Admin → Audit → Verify).
- **Browser:** strict Content-Security-Policy, no third-party scripts or fonts, and tokens are never put in
  URLs.

---

## 2. Install

### Easiest: the installer (macOS and Windows)

Run the installer for your system, `Obscura-<version>-macOS.pkg` or `Obscura-<version>-Windows.exe`. It is a
normal step-by-step wizard and needs no administrator password for a single-user install. It includes everything:
its own Python, the OCR engine, the web interface and, in the *full* edition, the AI models.

Then open **Obscura**. A small control window appears (**Open Obscura · Stop and quit · Uninstall…**), and a setup
assistant opens in the browser:
- this computer or an office server;
- where to keep case files;
- importing or downloading the models, if the installer didn't include them;
- start at login.

**To uninstall,** use any of these. Each asks whether to keep or delete the case files.
- macOS: "Uninstall Obscura" in Applications › Obscura.
- Windows: Settings › Apps.
- Inside the app: the Uninstall button.

How the installers are built, signed and published is described in [packaging/README.md](packaging/README.md).

### From source (developers, Linux servers)

Requirements: macOS or Linux, Python 3.12, [Tesseract OCR](https://github.com/tesseract-ocr/tesseract), and
Node 18+ (only to build the web UI). ffmpeg comes bundled with the Python packages. An Apple-silicon Mac,
or any machine with 16 GB RAM, is enough. An NVIDIA GPU speeds up video and audio work.

```bash
# macOS (Homebrew); on Debian/Ubuntu: sudo apt install tesseract-ocr python3.12-venv nodejs npm
brew install tesseract uv node
```

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt --excludes requirements-exclude.txt
```

Download the models. This is the **only** step that uses the internet (about 5 GB):

```bash
.venv/bin/python scripts/download_models.py
```

Build the web UI:

```bash
cd ../frontend && npm install && npm run build && cd ../backend
```

**Air-gapped (setup C):** do the steps above on a connected machine, then copy the whole project folder,
including `backend/.venv` and `backend/models/`, to the offline server. Use the same OS and CPU type.
Nothing else needs downloading.

---

## 3. Run

### A. One computer
```bash
cd backend
.venv/bin/python -m obscura.main          # http://127.0.0.1:8600
```

### B / C. Office server with HTTPS
Create a certificate. Pass the names and IPs staff will type in the browser:
```bash
scripts/make_cert.sh redact.yourfirm.lan 192.168.1.50
```
Install `data/tls/ca.crt` once on each staff computer as a trusted root certificate. Then start the server:
```bash
OBSCURA_BLOCK_NET=1 .venv/bin/python -m obscura.main --host 0.0.0.0 \
    --cert data/tls/server.crt --key data/tls/server.key
```
Allow port 8600 only from your office network in the firewall. To run it as a service, use your OS service
manager (systemd / launchd) with the same command and `WorkingDirectory=…/backend`.

### Signing in
**By default there is no sign-in on the computer running Obscura.** A browser on that computer opens straight into
the app as the built-in administrator "This computer".

Other computers on the network always need a user name and password. Requests that come through a proxy, from a
foreign host name (DNS rebinding) or from another web site's page are refused too.

To require sign-in on this computer as well, choose one of:
- the setup assistant's *Require a password* option;
- **System → This installation → Require sign-in**;
- the environment variable `OBSCURA_REQUIRE_LOGIN=1`.

With sign-in required and no accounts yet, the server creates an `admin` account on first start. Its one-time
password goes to `backend/data/INITIAL_ADMIN_PASSWORD.txt`, readable by the owner only. Sign in, choose a new
password (the app requires it), delete that file, then add users under **Admin → Users**.

### Back up
Back up `backend/data/` (database, encrypted files, `keys/`). **Without `data/keys/master.key` the encrypted
files cannot be read**, so keep a copy of the key somewhere safe, separate from the data backup.

### Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `OBSCURA_HOST` / `OBSCURA_PORT` | `127.0.0.1` / `8600` | listen address (`0.0.0.0` for an office server) |
| `OBSCURA_TLS_CERT` / `OBSCURA_TLS_KEY` | — | same as `--cert` / `--key` |
| `OBSCURA_BLOCK_NET` | off | `1` = refuse every outbound connection |
| `OBSCURA_DATA` | `backend/data` | data folder |
| `OBSCURA_MASTER_KEY` | key file | encryption key supplied from a secrets manager instead of the key file |
| `OBSCURA_DB_URL` | SQLite in data folder | e.g. a local PostgreSQL for large teams |
| `OBSCURA_THRESHOLD` | `0.5` | confidence at which a finding is pre-selected for redaction |
| `OBSCURA_SUGGEST_THRESHOLD` | `0.3` | lower findings are shown as suggestions only |
| `OBSCURA_WORKERS` | `2` | background jobs running at the same time |
| `OBSCURA_DEVICE` | `auto` | `cpu`, `mps` (Apple) or `cuda` |
| `OBSCURA_WATCHER` | `1` | hot-folder auto-redaction service on/off |
| `OBSCURA_REQUIRE_LOGIN` | `0` | `1` = sign-in also required on the computer running Obscura |
| `OBSCURA_CONFIG` | — | settings file written by the setup assistant (installed copies use it automatically) |

---

## 4. What it detects

Everything below is on by default in the **Standard** profile. Profiles change the set: HIPAA, FOIA, CJIS,
PCI, PI litigation, victim privacy, FRCP 5.2 (last-4 / year / initials), sensitive medical, privilege,
settlement, GDPR special categories, **Financial**, **Financial for court filing** (keeps last 4 digits) and Strict.

- **Financial documents**: bank, credit-union and card statements, brokerage and retirement statements, W-2 /
  1099 / 1040, pay stubs, loan applications and closing disclosures, credit reports, checks, wires, collection
  letters and bankruptcy schedules. Obscura reads:
  - transaction lines that name people ("ZELLE TO MARIA GOMEZ", "ONLINE TRANSFER TO DAVID CHEN XXXXXX8812",
    "VENMO *JSMITH1987", "CHECK 1042 PAID TO …", ACH "IND NAME / IND ID");
  - every masked account style ("x-8812", "XXXXXX8812", "517805XXXXXX", "6045****1188", "ending in 4417");
  - check MICR lines (routing checked with the ABA check digit), "Pay to the order of" and endorsements;
  - form name boxes and W-2 columns, state tax IDs, MERS MINs, FHA case and loan numbers;
  - security-question answers, credit scores and net-worth / income statements.

  Form numbers, box and line labels, OMB numbers, CUSIPs, tickers, rates and amounts stay readable.

- **Identifiers**, checked with each number's real check digits or rules wherever one exists: SSN / ITIN /
  EIN, cards (Luhn) and expiry / CVV, bank accounts and ABA routing, IBAN / SWIFT, driver's licences, passports,
  plates, VINs, MRNs, health-plan / Medicare (MBI) / Medicaid IDs, NPI, DEA, claim, policy and case numbers,
  immigration (A-numbers, USCIS receipts), Canadian SIN, UK NINO, Aadhaar / PAN, phones, emails, usernames,
  IPs, GPS, crypto wallets, device IDs.
- **People**: names in prose, forms, tables, captions, signatures, Q&A transcripts, spelled-out
  ("P-A-R-K") and nicknames, then every other mention of the same person. Minors are flagged.
- **Indirect identifiers**: the details that point to one person in context, such as "the McDonald's on
  Bank Street", "the night manager", "her 8-year-old daughter", an employer, a school, a vehicle, tattoos and
  scars, an apartment unit. Stronger combinations get higher scores.
- **Sensitive content**: diagnoses, medications, procedures, labs, mental health, substance use (42 CFR
  Part 2), sexual / reproductive health, HIV, genetics, disability, injuries, criminal history, immigration
  status, attorney-client privilege, settlement figures and financial details.
- **Pictures inside documents**: every photo, exhibit, chart, screenshot, scanned insert, ID card, signature,
  X-ray and logo in a PDF, Word or PowerPoint file is found and classified. Each one can be redacted whole with
  one click. ID cards and signatures are pre-selected. Text inside pictures (a chart title, a text-message
  screenshot, a card) is read with OCR and redacted in place, and faces in photos are redacted individually.
- **Charts and tables**: medical charts, flowsheets, MARs, lab and billing tables, and chart graphics are read
  with their column headers. Table lines are removed before OCR so every cell is read.
- **Images and video**: faces (two detectors combined), people, licence plates, screens and documents, with
  tracking across frames.
- **Audio**: speech is transcribed locally in 99 languages, with automatic language detection. Names and
  numbers are bleeped, muted or replaced with noise, with optional voice disguise and redacted captions.
  Speakers are labelled ("Speaker 1", "Speaker 2"). Labels are anonymous, and the tool never guesses who
  someone is. Transcripts and captions can be translated locally into 100 languages, always from the redacted
  text.

Every finding comes with its reason. The redaction log and the reason text never repeat the redacted value.

**Second opinion: Microsoft Presidio.** Microsoft's open-source PII detector runs locally as an independent check,
twice:
- **After analysis,** it re-reads the text. Anything it finds that the main engine did not is listed as a
  "Second opinion" suggestion for the reviewer.
- **After export,** it scans the redacted file and lists anything that still looks personal.

It reuses the spaCy model Obscura already loaded, never downloads anything, and never redacts on its own.
On the 60 development documents:
- Presidio alone scores 56% recall and 72% precision.
- It found 12 values the main engine had missed; the main engine now catches all of them.
- Adding its findings automatically would cost about 1,200 false redactions, which is why they are only suggested.

### Manual redaction and review tools
- Draw rectangles, ellipses or free polygons; select text to redact it; Find & Redact (one or all matches,
  regular expressions); custom term lists, templates and the hot-folder Watcher.
- **Redact additional text across a case.** Type any words, names, numbers or phrases (one per line, or regular
  expressions). Obscura previews the matches in every file, redacts them everywhere, and remembers them for files
  added later. Matching suggestions are switched on, and exported files that need re-exporting are flagged.
- Each redaction can have its own reason code (FOIA/PA exemptions or your own), label text, colour and, for
  images and video, its own effect (blur, pixelate, blackout, whiteout) and shape.
- Edit view, which shows content under each box, and a redacted preview; undo/redo; zoom; thumbnails; keyboard
  shortcuts.
- Video: automatic face/plate tracking, manual tracker, keyframes, stationary boxes, full-frame effect for a
  time range, "keep visible" per track, frame-by-frame stepping, enhancement for dark footage
  (brightness/contrast/sharpen/denoise), and burned-in redacted captions.
- Exports: true redaction plus metadata scrubbing and leak verification. Options include Bates numbering,
  watermark, password, an extra margin around boxes, and a **review copy** that outlines every redaction with its
  type and reason. The review copy is for internal QC only: viewers can never open it.
- Reports: a redaction log, an AI confidence report (type, confidence, detector, decision and reason, never the
  value), a case report and a tamper-evident audit trail.
- Files: PDF (native and scanned), Word, Excel, PowerPoint, email (EML, MSG and mailboxes: MBOX, plus Outlook PST
  when the open-source `readpst` tool is installed), images including TIFF, video and audio. Also merge, split
  and organise pages.

---

## 5. Models (all local) and why these

Chosen by measuring them on the held-out documents (`benchmarks/model_shootout_heldout.sh`):

Text detection, 38 held-out documents:

| Setup | Recall | Precision | F1 |
|---|---|---|---|
| **spaCy en_core_web_trf + NVIDIA GLiNER-PII + rules (shipped)** | **99.25%** | **98.61%** | **98.93%** |
| NVIDIA GLiNER-PII + rules | 98.70% | 98.62% | 98.66% |
| spaCy trf + Knowledgator GLiNER + rules | 97.88% | 96.64% | 97.26% |
| Knowledgator GLiNER + rules | 95.90% | 96.58% | 96.24% |
| spaCy trf + rules | 91.87% | 98.61% | 95.12% |
| rules only | 79.02% | 98.55% | 87.71% |

Knowledgator GLiNER lost in every combination and has been removed. spaCy `en_core_web_lg` had been removed
earlier: it caused 10× the false positives.

Speech (`benchmarks/whisper_compare.py`, synthesized speech with clean and telephone-quality versions):
`medium.en` has the lower word-error rate (14.3% vs 17.6% on clean speech), so it does the transcription.
`small.en` re-transcribes every redacted export as an independent leak check. The multilingual `small` model
handles the other 98 languages. Translation uses M2M100-418M (MIT licence), converted to a local int8 model. Speaker labels come from
WeSpeaker ResNet34 (Apache-2.0, 26 MB, ONNX).
Faces use YOLOv11m-face plus OpenCV YuNet combined. Plates use a YOLOv11m plate model. People, vehicles and
screens use YOLO11m.

Losing models are removed from disk and from `scripts/download_models.py`. `--candidates` fetches them again
if you want to re-run the comparison.

---

## 6. Accuracy

Measured on documents, not marketing. "Recall" means the share of sensitive values that ended up fully under a
redaction. "Precision" means the share of redactions that were actually sensitive.

| Document set | What it is | Recall | Precision |
|---|---|---|---|
| **Sealed test set** (18 docs, ~44 pages) | legal / medical / police, written independently, never tuned on, totals only | **90.4%** | **95.2%** |
| **Sealed financial set** (12 docs, ~75 pages) | statements, tax forms, pay stubs, loans, crypto, child support; never inspected; 86.9% / 84.7% before financial tuning | **88.9%** | **86.1%** |
| Financial development set (32 docs, ~135 pages) | three independent authors; first score before tuning 80.0% / 87.3% | 87.8% | 88.0% |
| Second development set (22 docs) | separate author across 15+ states; first score before tuning 79.9% / 95.5% | 91.7% | 98.8% |
| First development set (38 docs, ~108 pages) | police, medical, legal, financial, OCR scans | 99.2% | 99.0% |
| Synthetic PI case files (4 seeds × 6 cases, ~2,200 pages) | generated corpus, rules only | 99.7% | 99.9–100% |
| Spoken PII (100 synthesized recordings) | full audio pipeline, clean + telephone-quality | 98.1% | — |

Notes on the measurements:
- Precision on the two financial rows uses the original scoring. A version that ignores mask characters inside a
  redaction ("***-**-7046" when the annotator marked only "7046") gives 87.6% (sealed) and 91.3% (development).
  The benchmark now reports that mask-aware number by default. The other rows use it too (it changes them by
  0.2 points or less).
- **Financial records are the hardest set.** They are dense with numbers, and with names written in ALL CAPS on
  transaction lines. Expect to review more suggestions there.

On the sealed set:
- **100%:** SSNs, phones, emails, dates of birth, addresses, driver's licences, cards, bank and routing numbers,
  plates, VINs, passports, GPS, IP addresses and device IDs.
- **96%:** names.
- **60–90%:** record numbers (MRN, claim, generic ID numbers) and usernames.
- **Lowest:** descriptive context, such as "the regular at the bar on 5th", a tattoo described in a sentence,
  or a role that singles someone out.

These lower categories are exactly what a reviewer must check. They are shown as suggestions where the tool is
less sure, and every export is leak-checked for the values that were selected.

**A person must still review every document before release.** The tool pre-selects confident findings and
lists lower-confidence suggestions. On export it re-reads the output and blocks the download if any
redacted value can still be found.

---

## 7. Tests

```bash
cd backend
.venv/bin/python -m pytest tests/unit -q                 # ~2,600 detector / engine tests, seconds
.venv/bin/python -m pytest tests/integration -q          # PDF integrity, Office/email, API & roles, media, offline,
                                                         # setup wizard, launcher, uninstall script, second opinion
.venv/bin/python -m pytest tests/accuracy -q             # accuracy gates on the synthetic case files
.venv/bin/python benchmarks/run_heldout.py --split dev   # development documents, errors listed (also: dev2)
.venv/bin/python benchmarks/run_heldout.py --split fin --profile financial      # financial development documents
.venv/bin/python benchmarks/run_audio_benchmark.py       # 100 synthesized recordings through the audio pipeline (macOS)
.venv/bin/python benchmarks/run_heldout.py --split test  # sealed documents, totals only (also: fintest)
.venv/bin/python benchmarks/presidio_crosscheck.py --split devall   # what Microsoft Presidio finds that Obscura misses
cd ../frontend && npx vitest run
```

The held-out documents (`backend/tests/heldout/docs/`) were written separately from the detection rules. The
`test` split is sealed: it reports totals only, so it cannot be tuned against.
