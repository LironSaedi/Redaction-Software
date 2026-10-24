import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { LayoutTemplate, Plus, Save, Trash2 } from "lucide-react";
import * as api from "../../api";
import { entityOptions, useMeta } from "../../meta";
import { useToast } from "../../components/Toast";
import { ConfirmDialog, EmptyState, ErrorState, Field, Loading, Spinner } from "../../components/ui";
import { normalizeRect, type Point } from "../../lib/geometry";
import type { CaseSummary, FileRecord, PageInfo, Template, TemplateZone } from "../../types";

const newZone = (): TemplateZone => ({ pages: "all", x0: 0.1, y0: 0.1, x1: 0.3, y1: 0.15, entity: "CUSTOM", exemption: "", label: "" });

/** Fractions → rounded to 4 decimals and clamped into a valid zone. */
export function cleanZone(z: TemplateZone): TemplateZone {
  const c = (v: number) => Math.round(Math.min(1, Math.max(0, v)) * 10000) / 10000;
  const x0 = c(Math.min(z.x0, z.x1));
  const x1 = c(Math.max(z.x0, z.x1));
  const y0 = c(Math.min(z.y0, z.y1));
  const y1 = c(Math.max(z.y0, z.y1));
  return { ...z, x0, y0, x1: x1 > x0 ? x1 : Math.min(1, x0 + 0.001), y1: y1 > y0 ? y1 : Math.min(1, y0 + 0.001) };
}

function PagePicker({ onPick }: { onPick: (p: { fileId: number; page: number; info: PageInfo } | null) => void }) {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [caseId, setCaseId] = useState("");
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [fileId, setFileId] = useState("");
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [page, setPage] = useState(0);

  useEffect(() => {
    api.listCases().then(setCases, () => setCases([]));
  }, []);
  useEffect(() => {
    setFiles([]);
    setFileId("");
    if (caseId) api.getCase(Number(caseId)).then((c) => setFiles(c.files.filter((f) => f.kind === "pdf")), () => setFiles([]));
  }, [caseId]);
  useEffect(() => {
    setPages([]);
    setPage(0);
    onPick(null);
    if (fileId) api.getPages(Number(fileId)).then((r) => setPages(r.pages ?? []), () => setPages([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileId]);
  useEffect(() => {
    const info = pages.find((p) => p.page === page);
    onPick(info && fileId ? { fileId: Number(fileId), page, info } : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages, page]);

  return (
    <div className="row gap wrap">
      <select aria-label="Case" value={caseId} onChange={(e) => setCaseId(e.target.value)}>
        <option value="">Pick a case…</option>
        {cases.map((c) => (
          <option key={c.id} value={c.id}>
            #{c.id} {c.name}
            {c.number ? ` (${c.number})` : ""}
          </option>
        ))}
      </select>
      <select aria-label="PDF file" value={fileId} onChange={(e) => setFileId(e.target.value)} disabled={!files.length}>
        <option value="">{caseId && !files.length ? "No PDFs in this case" : "Pick a PDF…"}</option>
        {files.map((f) => (
          <option key={f.id} value={f.id}>
            {f.name}
          </option>
        ))}
      </select>
      {pages.length > 0 && (
        <select aria-label="Page" value={page} onChange={(e) => setPage(Number(e.target.value))}>
          {pages.map((p) => (
            <option key={p.page} value={p.page}>
              Page {p.page + 1}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

function ZoneCanvas({
  sample,
  zones,
  active,
  onActive,
  onAdd,
}: {
  sample: { fileId: number; page: number; info: PageInfo } | null;
  zones: TemplateZone[];
  active: number | null;
  onActive: (i: number) => void;
  onAdd: (z: TemplateZone) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ a: Point; b: Point } | null>(null);
  const aspect = sample ? sample.info.width / sample.info.height : 8.5 / 11;
  const frac = (e: RPointerEvent): Point => {
    const r = ref.current!.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };
  return (
    <div
      ref={ref}
      className="zone-canvas"
      style={{ aspectRatio: `${aspect}` }}
      onPointerDown={(e) => {
        if (e.button !== 0 || (e.target as HTMLElement).dataset.zone) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        const p = frac(e);
        setDrag({ a: p, b: p });
      }}
      onPointerMove={(e) => drag && setDrag({ a: drag.a, b: frac(e) })}
      onPointerUp={() => {
        if (!drag) return;
        const r = normalizeRect(drag.a, drag.b);
        setDrag(null);
        if (r.x1 - r.x0 < 0.01 || r.y1 - r.y0 < 0.005) return;
        onAdd(cleanZone({ ...newZone(), ...r }));
      }}
    >
      {sample ? (
        <img src={api.urls.pageImage(sample.fileId, sample.page, 72)} alt="Sample page" draggable={false} />
      ) : (
        <div className="zone-placeholder muted small">Pick a sample page above (optional) — or drag on this blank page.</div>
      )}
      {zones.map((z, i) => (
        <div
          key={i}
          data-zone="1"
          className={`zone ${i === active ? "active" : ""}`}
          style={{ left: `${z.x0 * 100}%`, top: `${z.y0 * 100}%`, width: `${(z.x1 - z.x0) * 100}%`, height: `${(z.y1 - z.y0) * 100}%` }}
          onClick={() => onActive(i)}
          title={z.label || `Zone ${i + 1}`}
        >
          <span data-zone="1">{i + 1}</span>
        </div>
      ))}
      {drag && (
        <div
          className="zone drawing"
          style={{
            left: `${Math.min(drag.a.x, drag.b.x) * 100}%`,
            top: `${Math.min(drag.a.y, drag.b.y) * 100}%`,
            width: `${Math.abs(drag.b.x - drag.a.x) * 100}%`,
            height: `${Math.abs(drag.b.y - drag.a.y) * 100}%`,
          }}
        />
      )}
    </div>
  );
}

export function TemplatesTab() {
  const m = useMeta();
  const toast = useToast();
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<(Omit<Template, "id"> & { id: number | null }) | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const [sample, setSample] = useState<{ fileId: number; page: number; info: PageInfo } | null>(null);
  const [busy, setBusy] = useState(false);
  const [toDelete, setToDelete] = useState<Template | null>(null);

  const load = () => {
    setError(null);
    api.listTemplates().then(setTemplates, (e) => setError(e instanceof Error ? e.message : "failed"));
  };
  useEffect(load, []);

  const setZone = (i: number, patch: Partial<TemplateZone>) =>
    draft && setDraft({ ...draft, zones: draft.zones.map((z, j) => (j === i ? { ...z, ...patch } : z)) });

  const save = async () => {
    if (!draft || !draft.name.trim()) return;
    setBusy(true);
    try {
      const body = { name: draft.name.trim(), description: draft.description, zones: draft.zones.map(cleanZone) };
      const t = draft.id ? await api.updateTemplate(draft.id, body) : await api.createTemplate(body);
      setDraft({ ...t });
      toast.success("Template saved");
      load();
    } catch (e) {
      toast.error(e, "Could not save template");
    } finally {
      setBusy(false);
    }
  };

  const pct = (v: number) => Math.round(v * 1000) / 10;

  return (
    <div className="master-detail">
      <div className="master">
        <div className="row space">
          <h2 className="h3">Zone templates</h2>
          <button
            className="btn btn-sm btn-primary"
            onClick={() => {
              setDraft({ id: null, name: "", description: "", zones: [] });
              setActive(null);
            }}
          >
            <Plus size={14} aria-hidden /> New template
          </button>
        </div>
        <p className="small muted">Fixed areas redacted on every page of a form (e.g. a signature or photo box). Coordinates are fractions of the page.</p>
        {error && <ErrorState message={error} onRetry={load} />}
        {!templates && !error && <Loading />}
        {templates && templates.length === 0 && <EmptyState icon={<LayoutTemplate size={26} />} title="No templates yet" />}
        <ul className="master-list">
          {templates?.map((t) => (
            <li key={t.id}>
              <button
                className={`master-item ${draft?.id === t.id ? "active" : ""}`}
                onClick={() => {
                  setDraft({ ...t });
                  setActive(null);
                }}
              >
                <span className="strong">{t.name}</span>
                <span className="muted small">{t.zones.length} zones</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="detail">
        {!draft && <EmptyState title="Select a template or create a new one" />}
        {draft && (
          <div className="card stack">
            <div className="form-grid">
              <Field label="Name" htmlFor="tp-name">
                <input id="tp-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </Field>
              <Field label="Description" htmlFor="tp-desc">
                <input id="tp-desc" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
              </Field>
            </div>
            <div>
              <div className="label">Sample page (from any analysed PDF)</div>
              <PagePicker onPick={setSample} />
            </div>
            <div className="template-editor">
              <ZoneCanvas
                sample={sample}
                zones={draft.zones}
                active={active}
                onActive={setActive}
                onAdd={(z) => {
                  setDraft({ ...draft, zones: [...draft.zones, z] });
                  setActive(draft.zones.length);
                }}
              />
              <div className="zone-table">
                <div className="row space">
                  <span className="label">Zones (drag on the page to add)</span>
                  <button className="btn btn-xs" onClick={() => setDraft({ ...draft, zones: [...draft.zones, newZone()] })}>
                    <Plus size={12} aria-hidden /> Add numerically
                  </button>
                </div>
                {draft.zones.length === 0 && <div className="muted small">No zones yet.</div>}
                {draft.zones.map((z, i) => (
                  <fieldset key={i} className={`zone-row ${i === active ? "active" : ""}`} onFocus={() => setActive(i)}>
                    <legend>Zone {i + 1}</legend>
                    <div className="zone-grid">
                      {(["x0", "y0", "x1", "y1"] as const).map((k) => (
                        <label key={k} className="small">
                          {k} %
                          <input
                            type="number"
                            step={0.1}
                            min={0}
                            max={100}
                            value={pct(z[k])}
                            onChange={(e) => setZone(i, { [k]: Number(e.target.value) / 100 })}
                          />
                        </label>
                      ))}
                      <label className="small">
                        Pages
                        <input value={z.pages} onChange={(e) => setZone(i, { pages: e.target.value })} placeholder="all, first, last or 1,3" />
                      </label>
                      <label className="small">
                        Type
                        <select value={z.entity} onChange={(e) => setZone(i, { entity: e.target.value })}>
                          {entityOptions(m).map((o) => (
                            <option key={o.key} value={o.key}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="small">
                        Exemption
                        <select value={z.exemption} onChange={(e) => setZone(i, { exemption: e.target.value })}>
                          <option value="">—</option>
                          {m.exemptionCodes.map(([c]) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="small">
                        Label
                        <input value={z.label} onChange={(e) => setZone(i, { label: e.target.value })} />
                      </label>
                    </div>
                    <button
                      className="btn btn-xs btn-danger-ghost"
                      onClick={() => {
                        setDraft({ ...draft, zones: draft.zones.filter((_, j) => j !== i) });
                        setActive(null);
                      }}
                    >
                      <Trash2 size={12} aria-hidden /> Remove
                    </button>
                  </fieldset>
                ))}
              </div>
            </div>
            <div className="row gap">
              <button className="btn btn-primary" onClick={save} disabled={busy || !draft.name.trim()}>
                {busy ? <Spinner size={14} /> : <Save size={14} aria-hidden />} Save template
              </button>
              {draft.id && (
                <button className="btn btn-danger-ghost" onClick={() => setToDelete(templates?.find((t) => t.id === draft.id) ?? null)}>
                  <Trash2 size={14} aria-hidden /> Delete
                </button>
              )}
            </div>
          </div>
        )}
      </div>
      {toDelete && (
        <ConfirmDialog
          title="Delete template?"
          danger
          message={`“${toDelete.name}” will be removed.`}
          confirmLabel="Delete"
          onCancel={() => setToDelete(null)}
          onConfirm={async () => {
            try {
              await api.deleteTemplate(toDelete.id);
              toast.success("Template deleted");
              if (draft?.id === toDelete.id) setDraft(null);
              setToDelete(null);
              load();
            } catch (e) {
              toast.error(e, "Could not delete");
            }
          }}
        />
      )}
    </div>
  );
}
