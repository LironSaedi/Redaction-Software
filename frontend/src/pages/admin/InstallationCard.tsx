import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Laptop, Building2, Power, RotateCw, Trash2 } from "lucide-react";
import * as api from "../../api";
import { useToast } from "../../components/Toast";
import { GoodbyeScreen, RestartScreen } from "../../components/AppScreens";
import { currentBoot } from "../../lib/restart";
import { ConfirmDialog, ErrorState, Modal, SkeletonList, Spinner, Switch } from "../../components/ui";
import type { AppInfo, AppMode, AppSettingsIn } from "../../types";

export const UNINSTALL_WORD = "UNINSTALL";

export function UninstallDialog({ onClose, onDone }: { onClose: () => void; onDone: (removedData: boolean) => void }) {
  const [removeData, setRemoveData] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ok = typed.trim() === UNINSTALL_WORD;
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.uninstallApp(removeData);
      onDone(removeData);
    } catch (e) {
      setError(e instanceof api.ApiError ? e.detail : e instanceof Error ? e.message : "uninstall failed");
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Uninstall Obscura"
      onClose={onClose}
      size="sm"
      busy={busy}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-danger" onClick={go} disabled={!ok || busy}>
            {busy ? <Spinner size={14} /> : <Trash2 size={14} aria-hidden />} Uninstall
          </button>
        </>
      }
    >
      <div className="stack-sm">
        <p className="small">Obscura is removed from this computer. Anyone using it on the network loses access.</p>
        <label className={`check uninstall-data ${removeData ? "danger" : ""}`}>
          <input type="checkbox" checked={removeData} onChange={(e) => setRemoveData(e.target.checked)} />
          <span>
            <strong>Also permanently delete all case files, exports, audit log and settings</strong>
            <span className="field-hint block">
              {removeData
                ? "This cannot be undone. The encryption keys are destroyed first, so nothing left behind can be read."
                : "Off: your case data stays on this computer (encrypted) and is used again if you reinstall."}
            </span>
          </span>
        </label>
        <div className="field">
          <label htmlFor="un-confirm">
            Type <span className="mono">{UNINSTALL_WORD}</span> to confirm
          </label>
          <input id="un-confirm" value={typed} autoComplete="off" spellCheck={false} onChange={(e) => setTyped(e.target.value)} />
        </div>
        {error && (
          <div className="notice notice-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </Modal>
  );
}

/** System page: how this copy is installed, sign-in, start-at-login, mode, restart and uninstall. */
export function InstallationCard() {
  const toast = useToast();
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<keyof AppSettingsIn | "restart" | null>(null);
  const [signInError, setSignInError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ kind: "mode"; mode: AppMode } | { kind: "restart" } | null>(null);
  // the boot id from before the restart: the overlay waits for a different one
  const [restarting, setRestarting] = useState<{ boot: string | null } | null>(null);
  const [uninstall, setUninstall] = useState(false);
  const [gone, setGone] = useState<boolean | null>(null);

  const load = () => {
    setError(null);
    api.getAppInfo().then(setInfo, (e) => setError(e instanceof Error ? e.message : "failed"));
  };
  useEffect(load, []);

  if (gone !== null) return <GoodbyeScreen removedData={gone} />;
  if (restarting) return <RestartScreen title="Restarting Obscura…" previousBoot={restarting.boot} />;

  const change = async (patch: AppSettingsIn) => {
    const key = Object.keys(patch)[0] as keyof AppSettingsIn;
    setBusy(key);
    setSignInError(null);
    try {
      const boot = patch.mode !== undefined || patch.port !== undefined ? await currentBoot() : null;
      const r = await api.updateApp(patch);
      if (r.restart) {
        setRestarting({ boot });
        return;
      }
      setInfo((x) => (x ? { ...x, ...patch } : x));
      toast.success("Setting saved");
    } catch (e) {
      const msg = e instanceof api.ApiError ? e.detail : e instanceof Error ? e.message : "could not save";
      if (key === "require_login") setSignInError(msg);
      else toast.error(msg);
    } finally {
      setBusy(null);
    }
  };

  const restart = async () => {
    setBusy("restart");
    try {
      const boot = await currentBoot();
      await api.restartApp();
      setRestarting({ boot });
    } catch (e) {
      toast.error(e, "Could not restart");
      setBusy(null);
    }
  };

  return (
    <section className="card installation">
      <h3 className="row gap-sm">
        <Power size={17} aria-hidden /> This installation
      </h3>
      {error && <ErrorState message={error} onRetry={load} />}
      {!info && !error && <SkeletonList rows={3} />}
      {info && !info.installed && <p className="small muted">Running from source — nothing to uninstall here.</p>}
      {info && info.installed && (
        <div className="install-grid">
          <dl className="kv">
            <dt>Version</dt>
            <dd>
              Obscura {info.version} · <span className="small">{info.platform}</span>
            </dd>
            <dt>Installed in</dt>
            <dd className="mono small">{info.install_dir || "—"}</dd>
            <dt>Case files</dt>
            <dd className="mono small">{info.data_dir}</dd>
            <dt>Models</dt>
            <dd className="mono small">{info.models_dir}</dd>
            <dt>Settings file</dt>
            <dd className="mono small">{info.config_path}</dd>
            <dt>Address</dt>
            <dd className="mono small">
              {info.mode === "office" && info.lan_address ? `http://${info.lan_address}:${info.port}/` : `http://127.0.0.1:${info.port}/`}
            </dd>
          </dl>
          <div className="stack-sm">
            {!info.local_request && (
              <div className="notice notice-info small">These settings can only be changed on the computer running Obscura.</div>
            )}
            <div className="field">
              <span className="field-label">Use</span>
              <div className="seg" role="radiogroup" aria-label="How Obscura is used">
                {(
                  [
                    ["single", "Just this computer", <Laptop key="l" size={14} aria-hidden />],
                    ["office", "Office server", <Building2 key="b" size={14} aria-hidden />],
                  ] as [AppMode, string, JSX.Element][]
                ).map(([k, label, icon]) => (
                  <button
                    key={k}
                    type="button"
                    role="radio"
                    aria-checked={info.mode === k}
                    className={`seg-item ${info.mode === k ? "active" : ""}`}
                    disabled={!info.local_request || busy !== null}
                    onClick={() => info.mode !== k && setConfirm({ kind: "mode", mode: k })}
                  >
                    {icon} {label}
                  </button>
                ))}
              </div>
              <span className="field-hint">
                {info.mode === "office" ? "Colleagues on the network open the address above and sign in." : "Only this computer can open Obscura."}
              </span>
            </div>
            <Switch
              checked={info.require_login}
              disabled={!info.local_request || busy !== null}
              onChange={(v) => change({ require_login: v })}
              label={<strong>Require sign-in on this computer</strong>}
              hint="Off: Obscura opens straight away here. Other computers always sign in."
            />
            {signInError && (
              <div className="notice notice-error small" role="alert">
                {signInError} <Link to="/admin/users">Open Users</Link>
              </div>
            )}
            {info.autostart_available && (
              <Switch
                checked={info.autostart}
                disabled={!info.local_request || busy !== null}
                onChange={(v) => change({ autostart: v })}
                label={<strong>Start at login</strong>}
                hint="Starts Obscura quietly when you log in to this computer."
              />
            )}
            <div>
              <button className="btn btn-sm" onClick={() => setConfirm({ kind: "restart" })} disabled={!info.local_request || busy !== null}>
                {busy === "restart" ? <Spinner size={13} /> : <RotateCw size={14} aria-hidden />} Restart Obscura
              </button>
            </div>
          </div>
          {info.uninstall_available && (
            <div className="danger-zone">
              <div>
                <strong className="row gap-sm">
                  <AlertTriangle size={15} aria-hidden /> Danger zone
                </strong>
                <div className="small muted">Remove Obscura from this computer, optionally with all case data.</div>
              </div>
              <button className="btn btn-danger-ghost" onClick={() => setUninstall(true)}>
                <Trash2 size={14} aria-hidden /> Uninstall Obscura…
              </button>
            </div>
          )}
        </div>
      )}
      {confirm?.kind === "mode" && (
        <ConfirmDialog
          title={confirm.mode === "office" ? "Turn this into an office server?" : "Use Obscura on this computer only?"}
          message={
            <p>
              {confirm.mode === "office"
                ? "Obscura will listen on the office network, and colleagues sign in with their own accounts. "
                : "Other computers will no longer be able to connect. "}
              Obscura restarts to apply this.
            </p>
          }
          confirmLabel="Switch and restart"
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            const mode = confirm.mode;
            setConfirm(null);
            void change({ mode });
          }}
        />
      )}
      {confirm?.kind === "restart" && (
        <ConfirmDialog
          title="Restart Obscura?"
          message={<p>Anyone using Obscura loses their connection for a few seconds. Running analyses and exports are interrupted.</p>}
          confirmLabel="Restart"
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            setConfirm(null);
            void restart();
          }}
        />
      )}
      {uninstall && <UninstallDialog onClose={() => setUninstall(false)} onDone={(rd) => setGone(rd)} />}
    </section>
  );
}
