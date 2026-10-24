import { useEffect, useState, type FormEvent } from "react";
import { Plus, Save, SlidersHorizontal, Trash2 } from "lucide-react";
import * as api from "../../api";
import { hasRole, useUser } from "../../auth";
import { useMeta } from "../../meta";
import { useToast } from "../../components/Toast";
import { AnalyzeSettingsForm, defaultAnalyzeParams, mergeParams } from "../../components/AnalyzeDialog";
import { ConfirmDialog, EmptyState, ErrorState, Field, Loading, Spinner } from "../../components/ui";
import type { AnalyzeParams, Preset } from "../../types";

function summary(p: Partial<AnalyzeParams>, profileLabel: (k: string) => string): string {
  const parts: string[] = [];
  if (p.profile) parts.push(profileLabel(p.profile));
  if (p.entities?.length) parts.push(`${p.entities.length} types`);
  parts.push(p.use_ml === false ? "rules only" : "AI models");
  if (p.visual_classes?.length) parts.push(`visual: ${p.visual_classes.join(", ")}`);
  if (p.list_ids?.length) parts.push(`${p.list_ids.length} lists`);
  if (p.template_ids?.length) parts.push(`${p.template_ids.length} templates`);
  return parts.join(" · ");
}

export function PresetsTab() {
  const user = useUser();
  const m = useMeta();
  const toast = useToast();
  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [params, setParams] = useState<AnalyzeParams>(defaultAnalyzeParams());
  const [busy, setBusy] = useState(false);
  const [toDelete, setToDelete] = useState<Preset | null>(null);
  const [viewing, setViewing] = useState<Preset | null>(null);
  const supervisor = hasRole(user, "supervisor");
  const profileLabel = (k: string) => m.meta?.profiles.find((p) => p.key === k)?.label ?? k;

  const load = () => {
    setError(null);
    api.listPresets().then(setPresets, (e) => setError(e instanceof Error ? e.message : "failed"));
  };
  useEffect(load, []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.createPreset(name.trim(), params);
      toast.success("Preset saved");
      setCreating(false);
      setName("");
      setParams(defaultAnalyzeParams());
      load();
    } catch (err) {
      toast.error(err, "Could not save preset");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="row space">
        <p className="muted small">Saved analysis settings. Pick one in the Analyze dialog or attach it to a watched folder.</p>
        {supervisor && !creating && (
          <button className="btn btn-sm btn-primary" onClick={() => setCreating(true)}>
            <Plus size={14} aria-hidden /> New preset
          </button>
        )}
      </div>
      {!supervisor && <div className="notice notice-info small">Only supervisors can create or delete presets.</div>}
      {creating && (
        <form className="card stack" onSubmit={create}>
          <Field label="Preset name" htmlFor="pr-name">
            <input id="pr-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
          <AnalyzeSettingsForm value={params} onChange={setParams} kinds={new Set()} idPrefix="pr" />
          <div className="row gap">
            <button className="btn btn-primary" type="submit" disabled={busy || !name.trim()}>
              {busy ? <Spinner size={14} /> : <Save size={14} aria-hidden />} Save preset
            </button>
            <button className="btn" type="button" onClick={() => setCreating(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && <ErrorState message={error} onRetry={load} />}
      {!presets && !error && <Loading />}
      {presets && presets.length === 0 && !creating && <EmptyState icon={<SlidersHorizontal size={26} />} title="No presets yet" />}
      {presets && presets.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Settings</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {presets.map((p) => (
                <tr key={p.id}>
                  <td className="strong">{p.name}</td>
                  <td className="small muted">{summary(p.settings, profileLabel)}</td>
                  <td className="actions-col">
                    <button className="btn btn-sm" onClick={() => setViewing(viewing?.id === p.id ? null : p)}>
                      {viewing?.id === p.id ? "Hide" : "Details"}
                    </button>
                    {supervisor && (
                      <button className="icon-btn danger" aria-label={`Delete ${p.name}`} onClick={() => setToDelete(p)}>
                        <Trash2 size={15} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {viewing && (
        <div className="card">
          <h3>{viewing.name}</h3>
          <fieldset disabled className="fieldset-readonly">
            <AnalyzeSettingsForm
              key={viewing.id}
              value={mergeParams(defaultAnalyzeParams(), viewing.settings)}
              onChange={() => undefined}
              kinds={new Set()}
              idPrefix="pv"
            />
          </fieldset>
        </div>
      )}
      {toDelete && (
        <ConfirmDialog
          title="Delete preset?"
          danger
          message={`“${toDelete.name}” will be removed. Watchers using it fall back to defaults.`}
          confirmLabel="Delete"
          onCancel={() => setToDelete(null)}
          onConfirm={async () => {
            try {
              await api.deletePreset(toDelete.id);
              toast.success("Preset deleted");
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

export function CodesTab() {
  const user = useUser();
  const m = useMeta();
  const toast = useToast();
  const [code, setCode] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const supervisor = hasRole(user, "supervisor");

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    try {
      await api.saveExemptionCode(code.trim(), desc.trim());
      toast.success("Exemption code saved");
      setCode("");
      setDesc("");
      m.reload();
    } catch (err) {
      toast.error(err, "Could not save code");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      {supervisor && (
        <form className="card row gap wrap" onSubmit={save}>
          <div className="field">
            <label htmlFor="ec-code">Code</label>
            <input id="ec-code" value={code} onChange={(e) => setCode(e.target.value)} maxLength={40} placeholder="e.g. CA 6254(c)" />
          </div>
          <div className="field grow">
            <label htmlFor="ec-desc">Description</label>
            <input id="ec-desc" value={desc} onChange={(e) => setDesc(e.target.value)} />
          </div>
          <button className="btn btn-primary align-end" type="submit" disabled={busy || !code.trim()}>
            {busy ? <Spinner size={14} /> : <Plus size={14} aria-hidden />} Add / update code
          </button>
        </form>
      )}
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Code</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>
            {m.exemptionCodes.map(([c, d]) => (
              <tr key={c}>
                <td className="mono nowrap">{c}</td>
                <td>{d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
