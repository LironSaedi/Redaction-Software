import { useEffect, useState, type FormEvent } from "react";
import { FolderInput, Plus, Trash2 } from "lucide-react";
import * as api from "../../api";
import { useMeta } from "../../meta";
import { useToast } from "../../components/Toast";
import { ConfirmDialog, EmptyState, ErrorState, Field, Loading, Spinner } from "../../components/ui";
import { titleCase } from "../../lib/format";
import type { CaseSummary, ExportParams, Preset, Watcher } from "../../types";

export function WatchersPage() {
  const m = useMeta();
  const toast = useToast();
  const [watchers, setWatchers] = useState<Watcher[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toDelete, setToDelete] = useState<Watcher | null>(null);
  const [form, setForm] = useState({
    name: "",
    input_dir: "",
    output_dir: "",
    case_id: "",
    preset_id: "",
    enabled: true,
    label: "none",
    effect: "blackout",
    text_style: "block",
  });

  const load = () => {
    setError(null);
    api.listWatchers().then(setWatchers, (e) => setError(e instanceof Error ? e.message : "failed"));
  };
  useEffect(() => {
    load();
    api.listCases().then(setCases, () => setCases([]));
    api.listPresets().then(setPresets, () => setPresets([]));
  }, []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.input_dir.trim() || !form.output_dir.trim() || !form.case_id) return;
    setBusy(true);
    try {
      const export_settings: ExportParams = {
        style: { label: form.label as "none" },
        effect: form.effect,
        text_style: form.text_style as "block",
      };
      await api.createWatcher({
        name: form.name.trim(),
        input_dir: form.input_dir.trim(),
        output_dir: form.output_dir.trim(),
        case_id: Number(form.case_id),
        preset_id: form.preset_id ? Number(form.preset_id) : null,
        export_settings,
        enabled: form.enabled,
      });
      toast.success("Watcher created");
      setCreating(false);
      load();
    } catch (err) {
      toast.error(err, "Could not create watcher");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (w: Watcher) => {
    try {
      await api.setWatcherEnabled(w.id, !w.enabled);
      load();
    } catch (e) {
      toast.error(e, "Could not update watcher");
    }
  };

  const caseName = (id: number) => cases.find((c) => c.id === id)?.name ?? `#${id}`;
  const presetName = (id: number | null) => (id ? presets.find((p) => p.id === id)?.name ?? `#${id}` : "Default settings");

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Watched folders</h1>
          <p className="muted">
            Files dropped into an input folder on this server are analysed, redacted, verified and written to the output folder
            automatically.
          </p>
        </div>
        {!creating && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden /> New watcher
          </button>
        )}
      </div>
      {creating && (
        <form className="card form-grid" onSubmit={create}>
          <Field label="Name" htmlFor="w-name">
            <input id="w-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </Field>
          <Field label="Case" htmlFor="w-case">
            <select id="w-case" value={form.case_id} onChange={(e) => setForm({ ...form, case_id: e.target.value })} required>
              <option value="">Choose…</option>
              {cases.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.id} {c.name}
                  {c.number ? ` (${c.number})` : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Input folder (on the server)" htmlFor="w-in">
            <input id="w-in" className="mono" value={form.input_dir} onChange={(e) => setForm({ ...form, input_dir: e.target.value })} placeholder="/srv/obscura/inbox" required />
          </Field>
          <Field label="Output folder (on the server)" htmlFor="w-out">
            <input id="w-out" className="mono" value={form.output_dir} onChange={(e) => setForm({ ...form, output_dir: e.target.value })} placeholder="/srv/obscura/redacted" required />
          </Field>
          <Field label="Analysis preset" htmlFor="w-preset">
            <select id="w-preset" value={form.preset_id} onChange={(e) => setForm({ ...form, preset_id: e.target.value })}>
              <option value="">Default settings</option>
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="PDF box label" htmlFor="w-label">
            <select id="w-label" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })}>
              <option value="none">None</option>
              <option value="entity">Type</option>
              <option value="exemption">Exemption code</option>
            </select>
          </Field>
          <Field label="Image / video effect" htmlFor="w-effect">
            <select id="w-effect" value={form.effect} onChange={(e) => setForm({ ...form, effect: e.target.value })}>
              {(m.meta?.effects ?? ["blackout", "blur", "pixelate"]).map((ef) => (
                <option key={ef} value={ef}>
                  {titleCase(ef)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Office text style" htmlFor="w-ts">
            <select id="w-ts" value={form.text_style} onChange={(e) => setForm({ ...form, text_style: e.target.value })}>
              <option value="block">Blocks</option>
              <option value="entity">[TYPE]</option>
              <option value="exemption">[EXEMPTION]</option>
            </select>
          </Field>
          <label className="check span-2">
            <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> Enabled
          </label>
          <div className="row gap span-2">
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy && <Spinner size={14} />} Create watcher
            </button>
            <button className="btn" type="button" onClick={() => setCreating(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && <ErrorState message={error} onRetry={load} />}
      {!watchers && !error && <Loading />}
      {watchers && watchers.length === 0 && !creating && (
        <EmptyState icon={<FolderInput size={28} />} title="No watched folders">
          Use watchers for unattended batch redaction (e.g. a nightly records export).
        </EmptyState>
      )}
      {watchers && watchers.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Input → output</th>
                <th>Case</th>
                <th>Preset</th>
                <th>Enabled</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {watchers.map((w) => (
                <tr key={w.id}>
                  <td className="strong">{w.name}</td>
                  <td className="mono small">
                    {w.input_dir} → {w.output_dir}
                  </td>
                  <td>{caseName(w.case_id)}</td>
                  <td>{presetName(w.preset_id)}</td>
                  <td>
                    <label className="switch">
                      <input type="checkbox" checked={w.enabled} onChange={() => toggle(w)} aria-label={`Enable ${w.name}`} />
                      <span>{w.enabled ? "On" : "Off"}</span>
                    </label>
                  </td>
                  <td className="actions-col">
                    <button className="icon-btn danger" aria-label={`Delete ${w.name}`} onClick={() => setToDelete(w)}>
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {toDelete && (
        <ConfirmDialog
          title="Delete watcher?"
          danger
          message={`“${toDelete.name}” stops watching its folder. Files already processed are not affected.`}
          confirmLabel="Delete"
          onCancel={() => setToDelete(null)}
          onConfirm={async () => {
            try {
              await api.deleteWatcher(toDelete.id);
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
