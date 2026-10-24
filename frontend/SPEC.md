# Obscura Redaction Studio — Web UI specification

A single-page app (React 18 + TypeScript + Vite) served by the FastAPI backend from `frontend/dist`.
It is used by law firms (personal-injury attorneys, paralegals), hospital release-of-information staff,
police records units and FOIA officers to review and redact sensitive files. Professional, calm,
dense-but-clear UI — think a document-review tool, not a marketing site.

## Hard constraints (privacy — non-negotiable)
- **No external network requests at runtime.** No CDNs, no Google Fonts, no analytics, no remote
  icons/images. Everything is bundled by Vite. System font stack only. The server sends
  `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:`
  so inline `<script>` and eval are blocked — do not use them.
- Never log detection values or document text to the console. Never put PII in URLs (use ids only).
- Keep the auth token in memory + `sessionStorage` (not localStorage). The server also sets an httpOnly
  cookie `obscura_token` (path `/api`) which makes `<img src>`, `<video src>` and download links work;
  every non-GET request must send `Authorization: Bearer <token>` (the server rejects cookie-only writes).
- Dependencies allowed (installed from npm, bundled): react, react-dom, react-router-dom, lucide-react,
  and dev tooling (vite, typescript, @vitejs/plugin-react, vitest, @testing-library/react, jsdom). Nothing else
  without good reason.

## Backend
- Run it: `cd backend && OBSCURA_WATCHER=0 .venv/bin/python -m obscura.main` → http://127.0.0.1:8600
  (first run writes `backend/data/INITIAL_ADMIN_PASSWORD.txt`; admin must change password on first login).
- API schema: `frontend/openapi.json` (also `/api/docs` when running). Router sources:
  `backend/obscura/api/{auth,cases,files,library,admin}.py` — read them for exact request/response shapes.
- Vite dev server must proxy `/api` → `http://127.0.0.1:8600`. Production build output: `frontend/dist`
  (assets in `dist/assets`, `index.html` at root; `base: "/"`).
- Long operations (analyze, export, bulk) return `{job_id}`; poll `GET /api/jobs/{id}` (~1 s) and show
  progress (`progress` 0..1, `message`). Show errors from `detail`.

## Roles
admin (everything + users, watchers, system), supervisor (all cases, approve, audit), redactor (cases they
belong to: upload, analyze, review, export), viewer (read-only; **only sees redacted exports**, never originals
or detection lists — hide those UI parts; the API returns 403 anyway).

## Screens
1. **Login** — username/password; handle 401/423 (locked)/429. If `user.must_change_password`, force the
   change-password screen (password rules: ≥12 chars, 3 of lower/upper/digit/symbol, not containing username).
2. **App shell** — left nav: Cases, Library (Lists, Templates, Presets), Audit log (supervisor+), Admin
   (Users, Watchers, System — admin). Top bar: active jobs indicator (poll `GET /api/jobs?active=true`),
   user menu (change password, logout). A persistent small badge "On-premises · offline" (privacy reassurance).
3. **Cases list** — table with name, number, request type, status, due date, file count, exported count;
   search box (client-side), "New case" dialog (name, number, request type: FOIA / Public records / Discovery /
   Subpoena / Medical records release / Internal / Other, due date, default profile from `GET /api/meta` profiles).
4. **Case detail** — header with editable fields + status; tabs:
   - **Files**: drag-and-drop multi-file upload (multipart field name `files`), table (name, kind icon, pages /
     duration, status, redactions, last export with verified ✓/✗), row actions (Open review, Analyze, Export,
     Download latest export, Delete — supervisor). Bulk select → Analyze selected / Export selected. Email
     attachments show indented under their parent (`parent_id`).
   - **Members**: add/remove members (user picker from `GET /api/users`, role redactor/reviewer/viewer).
   - **Notes**: list + add.
   - **Report**: `GET /api/cases/{id}/report` — totals per category and exemption, per-file table.
   - **Activity**: case audit log `GET /api/audit?case_id=`.
5. **Analyze dialog** (per file or bulk) — profile (from meta), optional entity checklist grouped by
   category (meta `entities` / `categories`), toggles: AI models (use_ml), OCR mode (auto/always/never),
   visual classes for images/video/PDF photos (meta `visual_classes`; default face, head, license_plate),
   video mode (balanced / max_accuracy / fast), audio redaction for video, "redact whole sentence for sensitive
   health/legal content", term lists (`GET /api/lists`), templates, extra search terms. Submit → job.
6. **Review workspace** (the core screen) `/files/:id` — layout: left thumbnails/navigation, centre viewer,
   right panel of detections. Behaviour depends on `file.kind`:
   - **pdf / image**: page images from `GET /api/files/{id}/pages/{n}.png?dpi=110` (image: n=0). Page geometry
     from `GET /api/files/{id}/pages` (`width`/`height` in PDF points; for images pixels). Detection boxes
     (`detections[].boxes[]` with `page,x0,y0,x1,y1` in the same units) are drawn as overlays scaled to the
     displayed image: **selected** = solid dark fill at ~85% opacity with a coloured outline per category;
     **unselected suggestions** = dashed outline only. Click a box → toggle selected (PATCH). Hover → tooltip
     with type, confidence, explanation, exemption. "Draw box" tool: drag a rectangle → POST manual detection
     with boxes (convert screen → page units). "Preview redacted" toggle hides text under selected boxes visually
     (pure-black boxes). Zoom in/out/fit, page navigation, keyboard: ←/→ pages, `d` draw, `p` preview.
   - Text selection redaction for PDFs: `GET /api/files/{id}/pages/{n}/text` returns the page text and a box per
     character; offer a "Select text" mode where dragging over characters selects a range and creates a manual
     detection via `POST /api/files/{id}/detections {page,start,end,entity}`.
   - **docx / pptx / xlsx / text**: show the extracted text (`GET /api/files/{id}/pages` returns `{text}` after
     analysis) in a monospace-ish reading view with highlighted spans (detections have `start`/`end` offsets
     into that text); click to toggle; select text to add a manual redaction (start/end).
   - **video**: HTML5 `<video src="/api/files/{id}/media">` with a canvas overlay drawing track boxes for the
     current frame (`fps` from `file.info.fps`; frame = round(currentTime*fps)); tracks list from
     `GET /api/files/{id}/video/tracks` (each `{id,label,enabled,first,last,max_score,boxes:{frame:[x0,y0,x1,y1]}}`,
     coordinates in video pixels). Timeline under the player with one row per track (bar from first→last frame);
     click a track to seek; toggle enabled ("keep visible" for e.g. an officer); delete; trim. "Add redaction":
     pause, draw a box on the current frame, choose mode (track object automatically / static for a range /
     keyframes) → `POST /api/files/{id}/video/tracks`. Preview frame with redaction:
     `GET /api/files/{id}/video/frame/{n}.jpg?preview=true&effect=blur`. Audio PII (if transcript) shown
     like the audio view below.
   - **audio** (and video audio): `<audio src="/api/files/{id}/media">`, transcript from
     `GET /api/files/{id}/transcript` (`words[]` with `text,start,end,char_start,char_end`), rendered as clickable
     words (click → seek). Detections have `meta.t0/t1` and `start/end` char offsets → highlight; toggle select;
     select words to add a manual redaction (POST with `t0,t1`). Download redacted captions
     `GET /api/files/{id}/captions.srt`.
   - **Right panel**: detections grouped by category then type, with counts, per-group "accept all / reject all"
     (`PATCH /api/files/{id}/detections {select_entities:{TYPE:bool}}`), each item shows text (truncated),
     page, confidence bar, source, exemption dropdown (codes from meta `exemption_codes`), entity change,
     delete. Filter box, "show suggestions" toggle, sort by page / confidence. Clicking an item scrolls/zooms to
     its box. A **Find & Redact** box: text, whole word, case sensitive, regex → `POST /api/files/{id}/search`
     (preview count, then "Redact all N"). Status chips: OCR'd pages, model used.
   - **Export dialog**: PDF: box label (none / type / exemption code / custom text), Bates prefix+start, watermark,
     password, flatten to image. Images/video: effect (blackout / blur / pixelate; meta `effects`), video audio
     effect (bleep/mute/noise), voice disguise, mute audio. Office/text: text style (block █ / [TYPE] / [EXEMPTION]).
     Submit → job → show verification result (`report.verification.passed`, issues list). Downloads:
     redacted file and `log.csv` (redaction / exemption log). If verification failed, show a prominent red
     warning and explain that a supervisor must review.
   - Supervisors: "Approve" button (`PATCH /api/files/{id} {status:"approved"}`).
7. **Library** — Term lists (redact lists & allow lists; textarea one term per line, regex flag per list, entity,
   exemption), Templates (zones as fractions 0..1 of the page; simple editor: pick a PDF page image from any
   analysed file and drag zones, or numeric entry), Presets (save analyze settings by name).
8. **Audit log** — filterable table; "Verify integrity" button (`GET /api/audit/verify` → valid/broken_at);
   CSV export.
9. **Admin** — Users (create with temp password, role, deactivate, unlock, reset password), Watchers (input
   folder, output folder, case, preset, enabled), System (`GET /api/system`: offline status, models, disk).
10. **Viewer experience** — viewers see cases → files → exports only (download, page-by-page view of redacted
    PDFs via `GET /api/exports/{id}/pages/{n}.png`).

## Quality bar
- TypeScript strict, no `any` sprawl; a typed API client module (`src/api.ts`) with one function per endpoint.
- Accessible: labelled inputs, focus states, keyboard navigation in the review workspace, colour is never the
  only signal (selected vs suggested also differs by fill vs dashed outline).
- Works at 1280×800 and up; usable on a 1920×1080 monitor; the review workspace uses the full viewport height.
- Light theme default with a dark theme toggle (persist in localStorage — UI preference only).
- Empty states, loading states, error toasts everywhere.
- `npm run build` must succeed with zero TypeScript errors; add a few vitest tests for the API client and the
  box-scaling math (screen ↔ page coordinates).
