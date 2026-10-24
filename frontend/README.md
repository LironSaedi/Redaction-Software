# Obscura Redaction Studio — web UI

React 18 + TypeScript + Vite single-page app for the Obscura backend. Everything is bundled locally: no CDN,
no web fonts (system font stack), no analytics, no inline scripts (works under the server's CSP).

## Development

```bash
# 1. backend (another shell) — http://127.0.0.1:8600
cd ../backend && OBSCURA_DATA=/tmp/obscura-ui-dev OBSCURA_WATCHER=0 .venv/bin/python -m obscura.main
#    first run writes /tmp/obscura-ui-dev/INITIAL_ADMIN_PASSWORD.txt (admin must change it at first sign-in)

# 2. UI — http://localhost:5173 (Vite proxies /api → http://127.0.0.1:8600)
npm install
npm run dev
```

## Build & test

```bash
npm run build      # tsc (strict, zero errors) + vite build → dist/ (index.html, assets/, favicon.svg)
npx vitest run     # unit tests (API client, coordinate + shape math, undo history, pictures, review helpers)
npm run typecheck  # types only
```

The backend serves `frontend/dist` automatically when it exists at start-up (`OBSCURA_FRONTEND` overrides the
path), so after `npm run build` the whole app is available at http://127.0.0.1:8600.

## Privacy rules implemented in the client

- The bearer token is kept in memory and `sessionStorage` (`obscura.session`) only; every request sends
  `Authorization: Bearer …`. `<img>`, `<video>` and `<audio>` rely on the server's httpOnly `obscura_token`
  cookie; downloads use `fetch` + a blob URL so server errors (e.g. "export failed verification") are shown
  instead of being saved as a file. Tokens are never put in URLs.
- URLs (routes and API calls) contain numeric ids only. Searches and filters are sent in request bodies or kept
  in component state.
- No `console.*` logging. `localStorage` holds only UI preferences (`obscura.theme`, `obscura.nav`).
- Viewers never request originals or detections; they see verified redacted exports only.

## Structure

```
src/
  api.ts                 typed API client — one function per endpoint, ApiError, downloads, job polling
  types.ts               response / request shapes (mirrors backend/obscura/api/*.py and redact/model.py)
  auth.tsx, meta.tsx, jobs.tsx   session store, GET /api/meta helpers, background-job tracker
  styles/                design system: tokens.css (colours, spacing, radii, shadows, type scale; light + dark),
                         base.css, components.css, shell.css, review.css, video.css (imported by styles/index.css)
  lib/geometry.ts        screen ↔ page / video coordinate math (rotation matrices, zoom, letterboxing, frames)
  lib/shapes.ts          rectangle / ellipse / polygon geometry, hit tests, resize handles, view ↔ page polygons
  lib/history.ts         undo / redo operation history (inverse API calls)
  lib/pictures.ts        picture classes (IMAGE_*), filters, counts, thumbnail crop layout
  lib/exports.ts         marked review copies ("Review copy — not for release"), latest release export
  lib/setup.ts           first-run wizard steps, validation, completion body; lib/restart.ts waits for a restart
  lib/secondOpinion.ts   Microsoft Presidio suggestions and the export's final check; lib/redactText.ts case-wide terms
  lib/hotkeys.ts, format.ts, theme.ts
  components/
    Layout.tsx           app shell: nav, jobs indicator, user menu, "On-premises · offline" badge
    AnalyzeDialog.tsx    analysis settings (speech language, speakers, picture classification…) + progress
    ExportDialog.tsx     export options per kind (margin, review copy, enhance, burned captions), verification
    Tooltip.tsx          one viewport-positioned tooltip for every [data-tip] element
    AppScreens.tsx       full-screen restart / uninstall / done screens; FinalCheck.tsx export final-check result
    Toast.tsx, ui.tsx    toasts, modal, tabs, badges, switch, skeletons, empty/error states
  pages/review/
    ReviewPage, ReviewHeader, ReviewSidebar   workspace shell: undo/redo, confidence report, side tabs
    PagedViewer, PageOverlay, ToolPalette, Thumbs   PDF / image viewer: tools, SVG shapes, move/resize, zoom, pan
    DetectionPanel, PropertiesPanel, FindRedactPanel, PicturesPanel, detectionUtils
    metaEdit             in-place PATCH updates (apply / inverse for undo)
    useDetections        detection state, serialised writes, undo / redo via PATCH / bulk delete / restore
    TextViewer           office / text documents
    AudioViewer, Transcript, Translation   transcript (speaker chips + filter), translation side by side, captions
    VideoWorkspace + video/   player, canvas overlay + live effects, timeline (in/out), tracks, full-frame effect
    ShortcutsHelp        "?" overlay
  pages/setup/           first-run setup wizard (/setup, shown before sign-in on an installed copy)
  pages/case/RedactTextTab   case-wide "Redact text"; case/CaseExports exports with final checks
  pages/admin/InstallationCard   System page: mode, sign-in, start at login, restart, uninstall
  pages/ (cases, case/*, library/*, admin/*, AuditPage, ExportViewerPage, Login, ChangePassword)
```

## Keyboard shortcuts (review workspace — press `?` for the full list)

PDF / image: `V` select / move, `R` (or `D`) rectangle, `E` ellipse, `G` polygon (click points, double-click or `Enter`
to close, `⌫` removes the last point, `Esc` cancels), `T` text selection, `H` hand (or hold `Space`); `Enter` redact /
un-redact the selected box, `Delete` deletes it; `P` edit ↔ preview redacted, `S` show / hide suggestions;
`+` / `−` zoom, `Ctrl`/`⌘` + scroll zooms at the pointer, `0` fit width, `F` fit page; `←` / `→` pages.
Everywhere: `Ctrl`/`⌘`+`Z` undo, `Ctrl`/`⌘`+`Shift`+`Z` (or `Ctrl`+`Y`) redo.
Video: `Space` play / pause, `←` / `→` or `,` / `.` frame step, `Shift`+`←`/`→` one second, `A` add redaction
(`R` / `E` shape while adding), `I` / `O` in / out points, `F` full-frame effect, `X` redact / keep visible the selected
track, `P` live preview. Detection list: `↑` / `↓` move, `Space` toggle.

## Local test data

`BACKEND_NOTES.md` lists backend issues found while testing (notably: images/video with detected faces fail to
analyze because of numpy `float32` values; use `visual_classes: ["text"]` and draw boxes manually until fixed).
The dev data directory used for testing (`/tmp/obscura-ui-dev`) has these throw-away accounts:
`admin` / `Obscura!Dev2026` and a viewer `vera` / `Viewer!Dev2026ok` (member of case 2).
