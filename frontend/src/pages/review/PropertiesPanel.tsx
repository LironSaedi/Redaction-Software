import { useEffect, useState } from "react";
import { Check, RotateCcw, Trash2, X } from "lucide-react";
import { entityGroups, useMeta, type MetaHelpers } from "../../meta";
import { ConfidenceBadge } from "../../components/ui";
import { titleCase, truncate } from "../../lib/format";
import { detectionShape } from "../../lib/shapes";
import { isPicture } from "../../lib/pictures";
import type { Detection, ImageEffect } from "../../types";
import type { DetectionOps } from "./useDetections";
import { detectionLabel, detectionLocation, detectorLabel } from "./detectionUtils";
import type { DrawDefaults } from "./PagedViewer";
import { FILL_SWATCHES, rgbCss, sameRgb } from "./workspace";

const EFFECTS: ImageEffect[] = ["blackout", "blur", "pixelate", "whiteout"];

export function EntitySelect({ id, value, onChange, disabled }: { id: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  const m = useMeta();
  const groups = entityGroups(m);
  const known = groups.some((g) => g.options.some((o) => o.key === value));
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      {!known && <option value={value}>{m.entityLabel(value)}</option>}
      {groups.map((g) => (
        <optgroup key={g.category} label={g.label}>
          {g.options.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

export function ExemptionSelect({
  id,
  value,
  onChange,
  m,
  emptyLabel = "None",
  disabled,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  m: MetaHelpers;
  emptyLabel?: string;
  disabled?: boolean;
}) {
  return (
    <select id={id} value={value || ""} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      <option value="">{emptyLabel}</option>
      {m.exemptionCodes.map(([code, desc]) => (
        <option key={code} value={code} title={desc}>
          {code} — {truncate(desc, 44)}
        </option>
      ))}
      {value && !m.exemptionCodes.some(([c]) => c === value) && <option value={value}>{value}</option>}
    </select>
  );
}

function Swatches({ value, onChange, disabled }: { value: number[] | null; onChange: (v: [number, number, number] | null) => void; disabled?: boolean }) {
  return (
    <div className="swatches" role="radiogroup" aria-label="Box colour">
      <button
        type="button"
        role="radio"
        aria-checked={!value}
        className={`swatch swatch-default ${!value ? "active" : ""}`}
        onClick={() => onChange(null)}
        disabled={disabled}
        data-tip="Export setting (default)"
        aria-label="Default colour"
      />
      {FILL_SWATCHES.map((s) => (
        <button
          key={s.name}
          type="button"
          role="radio"
          aria-checked={sameRgb(value, s.rgb)}
          className={`swatch ${sameRgb(value, s.rgb) ? "active" : ""}`}
          style={{ background: rgbCss(s.rgb) }}
          onClick={() => onChange(s.rgb)}
          disabled={disabled}
          data-tip={s.name}
          aria-label={s.name}
        />
      ))}
    </div>
  );
}

interface Appearance {
  label_text: string;
  fill: [number, number, number] | null;
  effect: string;
  note: string;
}

function appearanceOf(d: Detection): Appearance {
  const f = d.meta?.fill;
  return {
    label_text: typeof d.meta?.label_text === "string" ? d.meta.label_text : "",
    fill: Array.isArray(f) && f.length >= 3 ? [Number(f[0]), Number(f[1]), Number(f[2])] : null,
    effect: typeof d.meta?.effect === "string" ? d.meta.effect : "",
    note: typeof d.meta?.note === "string" ? d.meta.note : "",
  };
}

function sameAppearance(a: Appearance, b: Appearance): boolean {
  return a.label_text.trim() === b.label_text.trim() && sameRgb(a.fill, b.fill) && a.effect === b.effect && a.note.trim() === b.note.trim();
}

interface Props {
  det: Detection | null;
  fileKind: string;
  ops: DetectionOps;
  readOnly: boolean;
  defaults: DrawDefaults;
  setDefaults: (d: DrawDefaults) => void;
  onClose: () => void;
}

/** Properties of the selected redaction, or — with nothing selected — the settings for new shapes. */
export function PropertiesPanel({ det, fileKind, ops, readOnly, defaults, setDefaults, onClose }: Props) {
  const m = useMeta();
  const paged = fileKind === "pdf" || fileKind === "image";
  const isImage = fileKind === "image";
  const [draft, setDraft] = useState<Appearance | null>(det ? appearanceOf(det) : null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(det ? appearanceOf(det) : null);
    // reset only when another detection is selected (or it was re-created)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [det?.id]);

  if (!det) {
    if (!paged || readOnly) return null;
    return (
      <section className="props-panel" aria-label="New redaction settings">
        <header className="props-head">
          <h3>New redactions</h3>
          <span className="muted tiny">applied to shapes you draw</span>
        </header>
        <div className="props-body">
          <div className="field">
            <label htmlFor="pp-new-type">Type</label>
            <EntitySelect id="pp-new-type" value={defaults.entity} onChange={(v) => setDefaults({ ...defaults, entity: v })} />
          </div>
          <div className="field">
            <label htmlFor="pp-new-ex">Exemption / reason</label>
            <ExemptionSelect id="pp-new-ex" m={m} value={defaults.exemption} emptyLabel="Default for the type" onChange={(v) => setDefaults({ ...defaults, exemption: v })} />
          </div>
          <div className="field">
            <label htmlFor="pp-new-label">Label on the box</label>
            <input
              id="pp-new-label"
              value={defaults.label_text}
              placeholder="e.g. (b)(6) or Redacted per HIPAA"
              onChange={(e) => setDefaults({ ...defaults, label_text: e.target.value })}
            />
          </div>
          <div className="field">
            <span className="field-label">Colour</span>
            <Swatches value={defaults.fill} onChange={(v) => setDefaults({ ...defaults, fill: v })} />
          </div>
          {isImage && (
            <div className="field">
              <label htmlFor="pp-new-effect">Effect</label>
              <select id="pp-new-effect" value={defaults.effect} onChange={(e) => setDefaults({ ...defaults, effect: e.target.value })}>
                <option value="">Export setting</option>
                {EFFECTS.map((e) => (
                  <option key={e} value={e}>
                    {titleCase(e)}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </section>
    );
  }

  const d = det;
  const hasBoxes = d.boxes.length > 0;
  const editable = !readOnly;
  const dirty = !!draft && !sameAppearance(draft, appearanceOf(d));
  const shape = detectionShape(d);

  const apply = async () => {
    if (!draft) return;
    setSaving(true);
    // PATCH in place: the id, confidence, detector and reason are kept
    const ok = await ops.edit(
      d.id,
      hasBoxes
        ? {
            label_text: draft.label_text.trim() || null,
            fill: draft.fill,
            effect: (draft.effect || null) as ImageEffect | null,
            note: draft.note.trim() || null,
          }
        : { note: draft.note.trim() || null },
      hasBoxes ? "Edit appearance" : "Edit note",
    );
    setSaving(false);
    if (ok) setDraft({ ...draft, label_text: draft.label_text.trim(), note: draft.note.trim() });
  };

  return (
    <section className="props-panel" aria-label="Selected redaction">
      <header className="props-head">
        <span className="cat-dot" style={{ background: m.color(d.entity) }} aria-hidden />
        <h3 className="truncate" title={detectionLabel(d, m)}>
          {m.entityLabel(d.entity)}
        </h3>
        <span className={`badge tiny ${d.selected ? "badge-dark" : "badge-outline"}`}>{d.selected ? "Redacting" : "Suggestion"}</span>
        <span className="toolbar-spacer" />
        <button className="icon-btn sm" onClick={onClose} aria-label="Deselect" data-tip="Deselect (Esc)">
          <X size={14} />
        </button>
      </header>
      <div className="props-body">
        {!readOnly && (
          <div className="row gap-sm">
            <button className={`btn btn-sm grow ${d.selected ? "" : "btn-primary"}`} onClick={() => ops.toggle(d.id)}>
              {d.selected ? <X size={14} aria-hidden /> : <Check size={14} aria-hidden />}
              {d.selected ? "Un-redact (keep visible)" : isPicture(d) ? "Redact whole picture" : "Redact"}
            </button>
            <button className="btn btn-sm btn-danger-ghost" onClick={() => ops.remove(d.id)} aria-label="Delete this redaction" data-tip="Delete (Del)">
              <Trash2 size={14} aria-hidden />
            </button>
          </div>
        )}
        <div className="props-grid">
          <div className="field">
            <label htmlFor="pp-type">Type</label>
            <EntitySelect id="pp-type" value={d.entity} disabled={readOnly} onChange={(v) => ops.update(d.id, { entity: v }, "Change type")} />
          </div>
          <div className="field">
            <label htmlFor="pp-ex">Exemption / reason code</label>
            <ExemptionSelect id="pp-ex" m={m} value={d.exemption} disabled={readOnly} onChange={(v) => ops.update(d.id, { exemption: v }, "Change exemption")} />
          </div>
        </div>
        {editable && draft && (
          <fieldset className="props-appearance">
            <legend>{hasBoxes ? "Appearance in the export" : "Note"}</legend>
            {hasBoxes && (
              <>
            <div className="field">
              <label htmlFor="pp-label">Label on the box</label>
              <input
                id="pp-label"
                value={draft.label_text}
                placeholder={d.exemption ? `e.g. ${d.exemption}` : "e.g. Redacted per HIPAA"}
                onChange={(e) => setDraft({ ...draft, label_text: e.target.value })}
              />
            </div>
            <div className="field">
              <span className="field-label">Colour</span>
              <Swatches value={draft.fill} onChange={(v) => setDraft({ ...draft, fill: v })} />
            </div>
            {isImage && (
              <div className="field">
                <label htmlFor="pp-effect">Effect</label>
                <select id="pp-effect" value={draft.effect} onChange={(e) => setDraft({ ...draft, effect: e.target.value })}>
                  <option value="">Export setting</option>
                  {EFFECTS.map((e) => (
                    <option key={e} value={e}>
                      {titleCase(e)}
                    </option>
                  ))}
                </select>
              </div>
            )}
              </>
            )}
            <div className="field">
              <label htmlFor="pp-note">{hasBoxes ? "Note" : "Note (kept in the redaction log)"}</label>
              <textarea id="pp-note" rows={2} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
            </div>
            <div className="row gap-sm">
              <button className="btn btn-sm btn-primary" onClick={apply} disabled={!dirty || saving}>
                Save
              </button>
              <button className="btn btn-sm btn-ghost" onClick={() => setDraft(appearanceOf(d))} disabled={!dirty || saving}>
                <RotateCcw size={13} aria-hidden /> Reset
              </button>
            </div>
          </fieldset>
        )}
        <dl className="props-facts">
          <div>
            <dt>Confidence</dt>
            <dd>
              <ConfidenceBadge score={d.score} />
            </dd>
          </div>
          <div>
            <dt>Detector</dt>
            <dd title={d.source}>{detectorLabel(d.source)}</dd>
          </div>
          <div>
            <dt>Where</dt>
            <dd>
              {detectionLocation(d)}
              {hasBoxes && shape !== "rect" ? ` · ${shape}` : ""}
              {d.boxes.length > 1 ? ` · ${d.boxes.length} boxes` : ""}
            </dd>
          </div>
          {d.partial && (
            <div>
              <dt>Partial</dt>
              <dd>{d.partial}</dd>
            </div>
          )}
          {d.explanation && (
            <div className="span-all">
              <dt>Reason</dt>
              <dd>{d.explanation}</dd>
            </div>
          )}
        </dl>
      </div>
    </section>
  );
}
