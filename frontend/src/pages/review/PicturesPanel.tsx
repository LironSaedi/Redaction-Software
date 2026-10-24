import { memo, useMemo, useState } from "react";
import { Check, FileImage, Images, ShieldCheck, X } from "lucide-react";
import * as api from "../../api";
import { pictureClassLabel, useMeta } from "../../meta";
import { ConfidenceBadge, EmptyState, Switch } from "../../components/ui";
import { chooseDpi, toMatrix, transformRect } from "../../lib/geometry";
import {
  cropLayout,
  filterPictures,
  pictureClass,
  pictureCounts,
  pictureMediaName,
  sortPictures,
  type PictureStatus,
} from "../../lib/pictures";
import type { Detection, PageInfo } from "../../types";
import type { DetectionOps } from "./useDetections";

const FRAME = { w: 156, h: 104 };

const PictureThumb = memo(function PictureThumb({ fileId, d, page }: { fileId: number; d: Detection; page: PageInfo | undefined }) {
  const b = d.boxes[0];
  if (!b || !page) {
    return (
      <span className="pic-thumb pic-thumb-empty" aria-hidden>
        <FileImage size={28} />
      </span>
    );
  }
  const r = transformRect(toMatrix(page.matrix), b);
  const lay = cropLayout(r, { width: page.width, height: page.height }, FRAME);
  const dpi = chooseDpi(lay.scale, window.devicePixelRatio || 1);
  return (
    <span className="pic-thumb" style={{ width: FRAME.w, height: FRAME.h }} aria-hidden>
      <img
        src={api.urls.pageImage(fileId, b.page, dpi)}
        alt=""
        loading="lazy"
        draggable={false}
        style={{ width: lay.imgWidth, height: lay.imgHeight, left: lay.left, top: lay.top }}
      />
    </span>
  );
});

interface Props {
  fileId: number;
  pages: PageInfo[];
  dets: Detection[];
  ops: DetectionOps;
  focusedId: string | null;
  onFocus: (d: Detection) => void;
  readOnly: boolean;
  analyzed: boolean;
}

/** Every picture found in the document, classified, with a one-click "redact whole picture" toggle. */
export function PicturesPanel({ fileId, pages, dets, ops, focusedId, onFocus, readOnly, analyzed }: Props) {
  const m = useMeta();
  const [classes, setClasses] = useState<string[]>([]);
  const [status, setStatus] = useState<PictureStatus>("all");
  const counts = useMemo(() => pictureCounts(dets), [dets]);
  const shown = useMemo(() => sortPictures(filterPictures(dets, { classes, status })), [dets, classes, status]);
  const total = counts.reduce((n, c) => n + c.total, 0);
  const redacted = counts.reduce((n, c) => n + c.selected, 0);
  const byPage = useMemo(() => new Map(pages.map((p) => [p.page, p])), [pages]);

  const toggleClass = (c: string) => setClasses((cs) => (cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]));

  if (total === 0) {
    return (
      <div className="pictures-panel">
        <EmptyState compact icon={<Images size={28} />} title={analyzed ? "No pictures found" : "Not analyzed yet"}>
          {analyzed
            ? "No photos, exhibits, charts, ID cards or signatures were found. Re-analyze with “Classify pictures” switched on if the document has pictures."
            : "Analyze the file to find and classify its pictures (photos, exhibits, charts, ID cards, signatures)."}
        </EmptyState>
      </div>
    );
  }

  const shownKept = shown.filter((d) => !d.selected).length;
  const shownRedacted = shown.length - shownKept;

  return (
    <div className="pictures-panel">
      <div className="pictures-head">
        <div className="row space">
          <h2>Pictures</h2>
          <span className="small muted">
            <strong className="text">{redacted}</strong> of {total} redacted whole
          </span>
        </div>
        <div className="chip-filter" role="group" aria-label="Filter by picture type">
          <button type="button" className={`filter-chip ${classes.length === 0 ? "active" : ""}`} aria-pressed={classes.length === 0} onClick={() => setClasses([])}>
            All <span className="filter-count">{total}</span>
          </button>
          {counts.map((c) => (
            <button
              key={c.cls}
              type="button"
              className={`filter-chip ${classes.includes(c.cls) ? "active" : ""}`}
              aria-pressed={classes.includes(c.cls)}
              onClick={() => toggleClass(c.cls)}
              data-tip={`${c.selected} of ${c.total} redacted`}
            >
              {pictureClassLabel(m, c.cls).split(" (")[0]} <span className="filter-count">{c.total}</span>
            </button>
          ))}
        </div>
        <div className="row gap-sm wrap">
          <div className="seg seg-xs" role="radiogroup" aria-label="Status">
            {(
              [
                ["all", "All"],
                ["redacted", "Redacted"],
                ["kept", "Kept"],
              ] as const
            ).map(([k, l]) => (
              <button key={k} type="button" role="radio" aria-checked={status === k} className={`seg-item ${status === k ? "active" : ""}`} onClick={() => setStatus(k)}>
                {l}
              </button>
            ))}
          </div>
          <span className="toolbar-spacer" />
          {!readOnly && shown.length > 0 && (
            <>
              <button className="btn btn-xs" disabled={!shownKept} data-tip="Redact every picture shown (as filtered) whole" onClick={() => ops.setSelected(shown.map((d) => d.id), true, `Redact ${shownKept} pictures`)}>
                <Check size={12} aria-hidden /> Redact all
              </button>
              <button className="btn btn-xs" disabled={!shownRedacted} data-tip="Keep every picture shown (as filtered)" onClick={() => ops.setSelected(shown.map((d) => d.id), false, `Keep ${shownRedacted} pictures`)}>
                <X size={12} aria-hidden /> Keep all
              </button>
            </>
          )}
        </div>
      </div>
      <div className="pictures-grid" role="list">
        {shown.map((d) => {
          const cls = pictureClass(d);
          const name = pictureMediaName(d);
          const pageNo = d.boxes[0]?.page ?? d.page;
          return (
            <article key={d.id} role="listitem" className={`pic-card ${d.selected ? "is-redacted" : ""} ${focusedId === d.id ? "is-focused" : ""}`}>
              <button className="pic-open" onClick={() => onFocus(d)} aria-label={`Show ${pictureClassLabel(m, cls)} ${name ?? `on page ${pageNo + 1}`}`}>
                <PictureThumb fileId={fileId} d={d} page={byPage.get(d.boxes[0]?.page ?? -1)} />
                {d.selected && (
                  <span className="pic-redacted-mark">
                    <ShieldCheck size={14} aria-hidden /> Redacted
                  </span>
                )}
              </button>
              <div className="pic-info">
                <div className="pic-title">
                  <span className="truncate" title={pictureClassLabel(m, cls)}>
                    {pictureClassLabel(m, cls)}
                  </span>
                  <ConfidenceBadge score={d.score} compact />
                </div>
                <div className="pic-meta tiny muted truncate" title={name ?? undefined}>
                  {name ? name : `Page ${pageNo + 1}`}
                  {d.exemption ? ` · ${d.exemption}` : ""}
                </div>
                <Switch checked={d.selected} disabled={readOnly} onChange={(v) => ops.toggle(d.id, v)} label={<span className="small strong">Redact whole picture</span>} />
              </div>
            </article>
          );
        })}
        {shown.length === 0 && (
          <EmptyState compact title="No pictures match">
            <button className="link-btn" onClick={() => {
                setClasses([]);
                setStatus("all");
              }}>
              Show all pictures
            </button>
          </EmptyState>
        )}
      </div>
      <p className="tiny muted pictures-foot">
        Faces, plates and text found inside pictures are listed separately under Detections and are redacted even when the picture
        itself is kept.
      </p>
    </div>
  );
}
