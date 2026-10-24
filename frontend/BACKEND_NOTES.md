# Backend notes (found while building / testing the UI)

Nothing under `backend/` was changed. These are issues observed against the running server
(`OBSCURA_DATA=/tmp/obscura-ui-dev OBSCURA_WATCHER=0 python -m obscura.main`) while exercising the UI and
the API through the Vite proxy. Ordered by impact.

## 1. Visual detections crash analysis: `float32 is not JSON serializable` (high)

Any analysis that produces a visual detection fails at the end with
`TypeError: Object of type float32 is not JSON serializable` (raised from `storage.put_json` in
`processing.analyze_file`):

- **Images**: every photo with a detectable face / plate (all four fixtures, e.g. `zidane.jpg`) fails.
  `ImageDocument.analyze` passes `vb.score` and the padded `VBox` coordinates (numpy `float32`) straight into
  `Detection` / `Box`; `round(np.float32, n)` stays `float32`, so `Detection.to_dict()` is not JSON-safe.
- **Video**: `moving_faces.mp4` fails as soon as one track exists (track `max_score` / box values are numpy).
- **PDF photos**: `_visual_on_pdf` has the same `score=vb.score` pattern (not hit by the text-only test PDFs).

Workarounds used for testing: analyze images/video with `visual_classes: ["text"]` (no detector runs), then add
face boxes / tracks manually in the review workspace. Suggested fix: cast to `float()` in `Box.to_dict`,
`Detection.to_dict`, `Track.to_dict` (or give `put_json` a `default=` that converts numpy scalars with `.item()`).

## 2. A failed analysis leaves the file in status `analyzing` forever (medium)

When the analyze job raises, `jobs.run` marks the *job* `error`, but `File.status` stays `analyzing` and
`File.error` stays empty, so the file looks busy forever. The UI works around it (a file in `analyzing` with no
running job is shown as "Analysis interrupted", and the job's error is shown as a toast), but the server should
set `status="error"` and `error=<message>` on failure (same for export failures).

## 3. Email files (`.eml` / `.msg`) cannot be viewed, analyzed or exported (medium)

`ingest` converts the email to a PDF (`working_blob`) but keeps `kind="email"`:

- `GET /api/files/{id}/pages` → `{"pages": []}`; `GET /api/files/{id}/pages/0.png` → 400 "not a paged file";
- `POST /api/files/{id}/analyze` → job error "cannot analyze email";
- `working_path()` would also give the PDF a `.eml` suffix (`suffix = ".pdf" if f.working_blob and f.kind == "pdf"`).

Attachments are ingested correctly as child files (`parent_id`), and the UI shows them indented. Suggest storing
emails as `kind="pdf"` with `info.converted_from="email"` (as is done for TIFF), or handling `"email"` in the PDF
branches of `pages`, `page_png`, `page_text`, `analyze_file`, `search_file`, `text_range_detection`, `export_file`
and `working_path`.

## 4. Trimming a track leaves stale `first` / `last` (low)

`PATCH /api/files/{id}/video/tracks/{tid}` with `trim_start` / `trim_end` filters `boxes` but does not update the
stored `first` / `last` (e.g. a static track 5–20 trimmed at 12 still reports `last: 20`). The UI recomputes the
range from the boxes, but other consumers (reports, exports that rely on first/last) may not.

## 5. Audio duration is 0 for some formats (low)

`speech.aiff` is stored with `duration: 0` (the cv2-based `probe()` cannot open audio-only files; the exception is
swallowed). The transcript knows the real duration (20.1 s). Suggest an ffmpeg-only duration probe for audio.

## 6. Smaller observations / API inconsistencies

- `PATCH /api/watchers/{wid}` takes `enabled` as a **query parameter** while every other PATCH takes a JSON body
  (the UI sends `?enabled=true|false`).
- `GET /api/files/{id}/pages` for office/text files returns `{"pages": []}` before analysis and `{"text": ...}`
  after; returning `{"text": null}` before analysis would make the shape consistent.
- Exporting an approved file sets `status="exported"`, so the "approved" state disappears from lists
  (`approved_by` is kept). Possibly intended; the UI shows an "Approve" button again afterwards.
- Manual redactions made in a transcript can only be sent as a time range (`t0`/`t1`): the `start`/`end` branch of
  `POST /detections` requires an `extract_blob`, which audio/video files do not have. Time-range detections work,
  but they carry no `text`, so they are not added to the case dictionary.
- Image export produces no intermediate progress (stays at 0 until done); PDF/video exports report stages.
- There is no endpoint to delete a custom exemption code, list exports of a case, or delete a single export.
- `verify_pdf` issues of type `text_under_box` include a `found` excerpt of the leaked text. The UI does not
  display it (it could contain the very value that leaked), only the issue type, page and entity.

## 7. Manual-redaction toolkit, pictures, translation, review copies — resolved

The gaps reported here were fixed in the backend (Oct 19, 2026) and the UI now uses the fixes instead of workarounds:

- Appearance / geometry edits (label, colour, effect, note, shape, polygon points) use `PATCH /api/files/{id}/detections`
  in place — ids, confidence, detector and reason are kept (no more delete + re-create).
- Undo uses the exact inverses: PATCH with the previous values, `POST /detections/delete {ids}` (bulk) and
  `POST /detections/restore {detections}` (same ids); "Redact all" undo uses `added_ids` from `POST /search`.
- Video: `PATCH /video/tracks/{tid}` sets `effect` / `shape` on existing tracks; undo of add / delete / trim uses
  `POST /video/tracks/restore`. Frame previews honour per-track effects.
- Review copies are identified by `marked_copy` on every export summary; the case report counts `review_copies`.
- Translations are listed with `GET /api/files/{id}/translations`; segments carry `speaker`.
- The UI still serialises its own writes (harmless with the server's per-file lock).
- PST without `readpst` stays a per-file `errors[]` entry (HTTP 200) by design; the UI shows it verbatim.

## 8. Setup wizard, installation settings, second opinion, case-wide text redaction — resolved

The gaps reported here were fixed in the backend (Oct 19, 2026); the UI now uses the fixes:

- Case-wide "Redact text" and Find & Redact "Redact all" use `new_ids` / `switched_ids`: undo deletes only the new
  detections and un-selects the suggestions that existed before; redo restores them (same ids) and re-selects. On the
  review page a case-wide run is one Undo step across every file; on the case tab the result banner has Undo / Redo.
- Restart screens read `boot` from `/api/health` before the restart and wait for a different one (no timing guess).
- Export lists show the final check from `second_opinion_open`; the full findings are fetched only when a row is
  expanded. Viewers get findings without `text`, and the UI then shows page and type only.
- `POST /api/setup/complete` restarts after a models import / download into another folder, and the reported port is the
  real one, so the "restart once from the System page" note is gone.
