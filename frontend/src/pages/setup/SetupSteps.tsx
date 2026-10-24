import { useEffect, useRef, useState } from "react";
import {
  Building2,
  Check,
  CircleAlert,
  Download,
  FolderOpen,
  HardDrive,
  Laptop,
  Lock,
  ShieldCheck,
  Usb,
  WifiOff,
} from "lucide-react";
import * as api from "../../api";
import { Field, ProgressBar, Spinner, Switch } from "../../components/ui";
import { PasswordRules } from "../ChangePasswordPage";
import { missingModels, STEP_TITLES, type SetupChoices, type StepKey } from "../../lib/setup";
import type { SetupModel, SetupModelsState, SetupNeeded } from "../../types";

export interface StepProps {
  state: SetupNeeded;
  c: SetupChoices;
  set: (patch: Partial<SetupChoices>) => void;
  error: string | null;
}

function StepError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="notice notice-error" role="alert">
      <CircleAlert size={15} aria-hidden /> {error}
    </div>
  );
}

// ---- 1. welcome -----------------------------------------------------------------------------------------

export function WelcomeStep({ state }: StepProps) {
  return (
    <div className="setup-step">
      <h2>Welcome to Obscura Redaction Studio</h2>
      <p className="muted">A few questions and you're ready to redact. You can change everything later on the System page.</p>
      <ul className="promise-list">
        <li>
          <span className="promise-icon" aria-hidden>
            <HardDrive size={18} />
          </span>
          <div>
            <strong>Everything runs on this computer</strong>
            <div className="small muted">Detection, OCR, transcription and export all happen here — no cloud service is used.</div>
          </div>
        </li>
        <li>
          <span className="promise-icon" aria-hidden>
            <WifiOff size={18} />
          </span>
          <div>
            <strong>Nothing is uploaded</strong>
            <div className="small muted">No documents, settings or usage data ever leave this computer. No telemetry.</div>
          </div>
        </li>
        <li>
          <span className="promise-icon" aria-hidden>
            <Lock size={18} />
          </span>
          <div>
            <strong>Case files are encrypted</strong>
            <div className="small muted">Originals, working copies and exports are stored with AES-256 encryption.</div>
          </div>
        </li>
      </ul>
      <p className="tiny muted">
        Version {state.version} · {state.platform}
      </p>
    </div>
  );
}

// ---- 2. mode ----------------------------------------------------------------------------------------------

export function ModeStep({ state, c, set, error }: StepProps) {
  const addr = `http://${state.lan_address ?? "this-computer"}:${c.port}`;
  return (
    <div className="setup-step">
      <h2>How will you use Obscura?</h2>
      <StepError error={error} />
      <div className="choice-cards" role="radiogroup" aria-label="How Obscura is used">
        <div
          role="radio"
          aria-checked={c.mode === "single"}
          tabIndex={0}
          className={`choice-card ${c.mode === "single" ? "active" : ""}`}
          onClick={() => set({ mode: "single" })}
          onKeyDown={(e) => (e.key === " " || e.key === "Enter") && (e.preventDefault(), set({ mode: "single" }))}
        >
          <div className="choice-head">
            <Laptop size={22} aria-hidden />
            <strong>Just this computer</strong>
            <span className="badge badge-ok tiny">Recommended</span>
          </div>
          <p className="small muted">Obscura opens straight away on this computer, with no sign-in. Other computers cannot connect.</p>
          {c.mode === "single" && (
            <div className="choice-extra" onClick={(e) => e.stopPropagation()}>
              <Switch
                checked={c.requireLogin}
                onChange={(v) => set({ requireLogin: v })}
                label={<span className="small strong">Require a password on this computer too</span>}
                hint="For shared computers: you create an administrator account in a later step."
              />
            </div>
          )}
        </div>
        <div
          role="radio"
          aria-checked={c.mode === "office"}
          tabIndex={0}
          className={`choice-card ${c.mode === "office" ? "active" : ""}`}
          onClick={() => set({ mode: "office" })}
          onKeyDown={(e) => (e.key === " " || e.key === "Enter") && (e.preventDefault(), set({ mode: "office" }))}
        >
          <div className="choice-head">
            <Building2 size={22} aria-hidden />
            <strong>Office server</strong>
          </div>
          <p className="small muted">
            Colleagues on your network open <span className="mono">{addr}</span> in their browser and sign in with their own
            accounts.
          </p>
          {c.mode === "office" && (
            <div className="choice-extra" onClick={(e) => e.stopPropagation()}>
              <Field label="Port" htmlFor="su-port" hint="Leave as is unless another program uses it.">
                <input
                  id="su-port"
                  className="num-input"
                  type="number"
                  min={1024}
                  max={65535}
                  value={c.port}
                  onChange={(e) => set({ port: Number(e.target.value) || 0 })}
                />
              </Field>
              {!state.lan_address && <div className="field-hint warn-text">This computer's network address could not be read; check its network connection.</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---- 3. location ------------------------------------------------------------------------------------------

export function LocationStep({ state, c, set, error }: StepProps) {
  const [picking, setPicking] = useState(false);
  const [pickError, setPickError] = useState<string | null>(null);
  const pick = async () => {
    setPicking(true);
    setPickError(null);
    try {
      const r = await api.pickFolder("data");
      if (r.path) set({ dataDir: r.path });
    } catch (e) {
      setPickError(e instanceof Error ? e.message : "the folder chooser could not be opened");
    } finally {
      setPicking(false);
    }
  };
  return (
    <div className="setup-step">
      <h2>Where should case files be kept?</h2>
      <p className="muted small">
        Uploaded files, working copies, exports and the audit log are stored here, encrypted. Choose a drive with plenty of space —
        video and scanned records add up quickly.
      </p>
      <StepError error={error ?? pickError} />
      <Field label="Case files folder" htmlFor="su-dir">
        <div className="row gap-sm">
          <input id="su-dir" className="mono" value={c.dataDir} onChange={(e) => set({ dataDir: e.target.value })} spellCheck={false} />
          {state.can_pick_folder && (
            <button type="button" className="btn" onClick={pick} disabled={picking}>
              {picking ? <Spinner size={14} /> : <FolderOpen size={15} aria-hidden />} Change…
            </button>
          )}
        </div>
      </Field>
      <div className="row gap-sm small">
        <HardDrive size={15} aria-hidden className="muted" />
        {state.disk_free_gb != null ? (
          <span className={state.disk_free_gb < 10 ? "warn-text" : "muted"}>
            {state.disk_free_gb} GB free on the default drive{state.disk_free_gb < 10 ? " — that is not much for video" : ""}
          </span>
        ) : (
          <span className="muted">Free space unknown</span>
        )}
      </div>
      <p className="tiny muted">A folder that already holds other files gets an “Obscura Data” folder inside it, so nothing is mixed.</p>
    </div>
  );
}

// ---- 4. models --------------------------------------------------------------------------------------------

function ModelRow({ m }: { m: SetupModel }) {
  return (
    <li className={`model-row ${m.present ? "present" : m.required ? "missing required" : "missing"}`}>
      <span className="model-state" aria-hidden>
        {m.present ? <Check size={15} /> : <CircleAlert size={15} />}
      </span>
      <div className="grow">
        <div className="row gap-sm">
          <strong className="small">{m.label}</strong>
          {m.required && !m.present && <span className="badge badge-warn tiny">Required</span>}
        </div>
        <div className="tiny muted">For {m.needed_for}</div>
      </div>
      <span className="tiny muted nowrap">{m.size_gb < 1 ? `${Math.round(m.size_gb * 1000)} MB` : `${m.size_gb.toFixed(1)} GB`}</span>
      <span className={`tiny nowrap ${m.present ? "ok-text" : "muted"}`}>{m.present ? "Installed" : "Missing"}</span>
    </li>
  );
}

/** Models imported or downloaded into another folder are picked up by the restart at the end of setup. */
export function ModelsStep({ state, models, setModels }: StepProps & { models: SetupModel[]; setModels: (m: SetupModel[]) => void }) {
  const [busy, setBusy] = useState<"import" | "download" | null>(null);
  const [download, setDownload] = useState<SetupModelsState["download"]["state"]>("idle");
  const [msg, setMsg] = useState<{ kind: "ok" | "error" | "info"; text: string } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const miss = missingModels(models);

  const refresh = async () => {
    const r = await api.getSetupModels();
    setModels(r.models);
    setDownload(r.download?.state ?? "idle");
    return r;
  };

  // poll while a download runs
  useEffect(() => {
    if (download !== "running") return;
    const tick = async () => {
      try {
        const r = await refresh();
        if (r.download?.state === "running") timer.current = setTimeout(tick, 2000);
        else if (r.download?.state === "done") setMsg({ kind: "ok", text: "The models were downloaded. Obscura is offline again." });
        else if (r.download?.state === "error") setMsg({ kind: "error", text: "The download did not finish. Check the internet connection and try again, or import the models from a USB drive." });
      } catch {
        timer.current = setTimeout(tick, 3000);
      }
    };
    timer.current = setTimeout(tick, 2000);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [download]);

  const importFolder = async () => {
    setBusy("import");
    setMsg(null);
    try {
      const picked = await api.pickFolder("models");
      if (!picked.path) return;
      const r = await api.importModels(picked.path);
      await refresh();
      setMsg({ kind: "ok", text: `Imported ${r.imported.length} model folder${r.imported.length === 1 ? "" : "s"}.` });
    } catch (e) {
      setMsg({ kind: "error", text: e instanceof Error ? e.message : "the models could not be imported" });
    } finally {
      setBusy(null);
    }
  };

  const startDownload = async () => {
    setBusy("download");
    setMsg(null);
    try {
      const r = await api.downloadModels();
      setDownload(r.state);
    } catch (e) {
      setMsg({ kind: "error", text: e instanceof Error ? e.message : "the download could not start" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="setup-step">
      <h2>AI models</h2>
      <p className="muted small">
        Obscura's detectors run from model files on this computer. {miss.required.length === 0 && miss.optional.length === 0
          ? "Everything is installed."
          : miss.required.length
            ? "Some required models are missing — analysis will be limited until they are installed."
            : "The required models are installed; the optional ones add speech and translation."}
      </p>
      <ul className="model-list">
        {models.map((m) => (
          <ModelRow key={m.key} m={m} />
        ))}
      </ul>
      <div className="row gap-sm wrap status-chips" aria-label="Other components">
        <span className={`chip ${state.spacy_model ? "chip-ok" : ""}`}>{state.spacy_model ? "✓" : "✗"} spaCy language model</span>
        <span className={`chip ${state.ocr ? "chip-ok" : ""}`}>{state.ocr ? "✓" : "✗"} OCR (Tesseract)</span>
        <span className={`chip ${state.second_opinion ? "chip-ok" : ""}`}>{state.second_opinion ? "✓" : "✗"} Second opinion (Microsoft Presidio)</span>
      </div>
      {(miss.required.length > 0 || miss.optional.length > 0) && (
        <div className="row gap wrap">
          <button className="btn" onClick={importFolder} disabled={busy !== null || download === "running"}>
            {busy === "import" ? <Spinner size={14} /> : <Usb size={15} aria-hidden />} Import from a folder or USB drive…
          </button>
          <button className="btn btn-primary" onClick={startDownload} disabled={busy !== null || download === "running"}>
            {busy === "download" ? <Spinner size={14} /> : <Download size={15} aria-hidden />} Download now (one time, ~{miss.downloadGb} GB)
          </button>
        </div>
      )}
      {download === "running" && (
        <div className="stack-sm" role="status">
          <span className="small">Downloading the model files… this can take a while. You can keep going with the other steps.</span>
          <ProgressBar value={0} indeterminate label="Model download" />
        </div>
      )}
      {msg && (
        <div className={`notice ${msg.kind === "error" ? "notice-error" : "notice-info"}`} role={msg.kind === "error" ? "alert" : "status"}>
          {msg.text}
        </div>
      )}
      <p className="tiny muted row gap-xs">
        <ShieldCheck size={13} aria-hidden /> Only model files are downloaded, from their publishers. No documents, settings or usage data are
        sent, and Obscura stays offline afterwards.
      </p>
      <p className="tiny muted">Models folder: <span className="mono">{state.models_dir}</span></p>
    </div>
  );
}

// ---- 5. administrator ------------------------------------------------------------------------------------

export function AdminStep({ c, set, error }: StepProps) {
  return (
    <div className="setup-step">
      <h2>Administrator account</h2>
      <p className="muted small">
        {c.mode === "office"
          ? "You sign in with this account from any computer; add your colleagues' accounts afterwards on the Users page."
          : "You sign in with this account on this computer."}
      </p>
      <StepError error={error} />
      <div className="form-grid">
        <Field label="User name" htmlFor="su-user">
          <input id="su-user" value={c.adminUsername} autoComplete="username" onChange={(e) => set({ adminUsername: e.target.value })} />
        </Field>
        <Field label="Full name (optional)" htmlFor="su-name">
          <input id="su-name" value={c.adminFullName} autoComplete="name" onChange={(e) => set({ adminFullName: e.target.value })} />
        </Field>
        <Field label="Password" htmlFor="su-pw">
          <input id="su-pw" type="password" autoComplete="new-password" value={c.adminPassword} onChange={(e) => set({ adminPassword: e.target.value })} />
        </Field>
        <Field label="Confirm password" htmlFor="su-pw2">
          <input id="su-pw2" type="password" autoComplete="new-password" value={c.adminConfirm} onChange={(e) => set({ adminConfirm: e.target.value })} />
        </Field>
      </div>
      <PasswordRules password={c.adminPassword} username={c.adminUsername.trim().toLowerCase()} confirm={c.adminConfirm} />
    </div>
  );
}

// ---- 6. options ------------------------------------------------------------------------------------------------

export function OptionsStep({ c, set }: StepProps) {
  return (
    <div className="setup-step">
      <h2>Options</h2>
      <Switch
        checked={c.autostart}
        onChange={(v) => set({ autostart: v })}
        label={<strong>Start Obscura when I log in</strong>}
        hint={c.mode === "office" ? "Recommended for an office server, so colleagues can always reach it." : "Obscura starts quietly in the background."}
      />
    </div>
  );
}

// ---- 7. review -------------------------------------------------------------------------------------------------

export function ReviewStep({ state, c, error, models, steps }: StepProps & { models: SetupModel[]; steps: StepKey[] }) {
  const miss = missingModels(models);
  const rows: [string, string][] = [
    ["Use", c.mode === "office" ? `Office server — http://${state.lan_address ?? "this-computer"}:${c.port}` : "Just this computer"],
    ["Sign-in", c.mode === "office" || c.requireLogin ? `Required (administrator: ${c.adminUsername.trim().toLowerCase()})` : "Off — opens straight away here"],
    ["Case files", c.dataDir],
    ["AI models", miss.required.length ? `${miss.required.length} required model(s) missing` : miss.optional.length ? `Installed (${miss.optional.length} optional missing)` : "All installed"],
  ];
  if (steps.includes("options")) rows.push(["Start at login", c.autostart ? "Yes" : "No"]);
  return (
    <div className="setup-step">
      <h2>{STEP_TITLES.review}</h2>
      <StepError error={error} />
      <dl className="review-list">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className={k === "Case files" ? "mono small" : ""}>{v}</dd>
          </div>
        ))}
      </dl>
      <p className="small muted">Press Finish to save these settings. Obscura may restart once to use them.</p>
    </div>
  );
}
