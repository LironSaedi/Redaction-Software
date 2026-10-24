import { useEffect, useState } from "react";
import { CheckCircle2, Cpu, HardDrive, RefreshCw, ShieldCheck, WifiOff, XCircle } from "lucide-react";
import * as api from "../../api";
import { useMeta } from "../../meta";
import { ErrorState, Loading } from "../../components/ui";
import type { SystemInfo } from "../../types";
import { InstallationCard } from "./InstallationCard";

function Flag({ ok, yes, no }: { ok: boolean; yes: string; no: string }) {
  return ok ? (
    <span className="ok-text">
      <CheckCircle2 size={15} aria-hidden /> {yes}
    </span>
  ) : (
    <span className="bad-text">
      <XCircle size={15} aria-hidden /> {no}
    </span>
  );
}

function listModels(v: SystemInfo["models_loaded"]): string {
  if (Array.isArray(v)) return v.length ? v.join(", ") : "none yet (loaded on first use)";
  const keys = Object.entries(v ?? {})
    .filter(([, x]) => !!x)
    .map(([k, x]) => (typeof x === "string" ? `${k}: ${x}` : k));
  return keys.length ? keys.join(", ") : "none yet (loaded on first use)";
}

export function SystemPage() {
  const { meta } = useMeta();
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => {
    setError(null);
    api.getSystem().then(setInfo, (e) => setError(e instanceof Error ? e.message : "failed"));
  };
  useEffect(load, []);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>System</h1>
          <p className="muted">Everything runs on this host. No cloud services are used.</p>
        </div>
        <button className="btn" onClick={load}>
          <RefreshCw size={15} aria-hidden /> Refresh
        </button>
      </div>
      <InstallationCard />
      {error && <ErrorState message={error} onRetry={load} />}
      {!info && !error && <Loading />}
      {info && (
        <div className="grid-3">
          <section className="card">
            <h3 className="row gap-sm">
              <WifiOff size={17} aria-hidden /> Privacy
            </h3>
            <dl className="kv">
              <dt>Offline mode</dt>
              <dd>
                <Flag ok={info.offline} yes="Enforced (no model downloads, no telemetry)" no="Not enforced" />
              </dd>
              <dt>Encryption at rest</dt>
              <dd>
                <Flag ok={info.encrypt_at_rest} yes="AES-256-GCM" no="Disabled" />
              </dd>
              <dt>Listening on</dt>
              <dd className="mono">
                {info.host}:{info.port}
                {["127.0.0.1", "localhost", "::1"].includes(info.host) ? " (this computer only)" : " (network)"}
              </dd>
            </dl>
          </section>
          <section className="card">
            <h3 className="row gap-sm">
              <Cpu size={17} aria-hidden /> Models
            </h3>
            <dl className="kv">
              <dt>OCR (Tesseract)</dt>
              <dd>
                <Flag ok={info.ocr_available} yes="Available" no="Not installed" />
              </dd>
              <dt>spaCy</dt>
              <dd className="mono small">{info.spacy_model}</dd>
              <dt>GLiNER</dt>
              <dd className="mono small">{info.gliner_model}</dd>
              <dt>Whisper</dt>
              <dd className="mono small">{info.whisper_model}</dd>
              <dt>Second opinion</dt>
              <dd>
                <Flag
                  ok={!!meta?.second_opinion?.available}
                  yes={`Microsoft Presidio ${meta?.second_opinion?.version ?? ""}`.trim()}
                  no={meta?.second_opinion?.reason ? `Unavailable (${meta.second_opinion.reason})` : "Unavailable"}
                />
              </dd>
              <dt>Loaded now</dt>
              <dd className="small">{listModels(info.models_loaded)}</dd>
              {Object.entries(info.models_on_disk).map(([k, v]) => (
                <div key={k} className="kv-row">
                  <dt>On disk: {k}</dt>
                  <dd className="small mono">{v.length ? v.join(", ") : "—"}</dd>
                </div>
              ))}
            </dl>
          </section>
          <section className="card">
            <h3 className="row gap-sm">
              <HardDrive size={17} aria-hidden /> Storage &amp; usage
            </h3>
            <dl className="kv">
              <dt>Data folder</dt>
              <dd className="mono small">{info.data_dir}</dd>
              <dt>Free disk</dt>
              <dd className={info.disk_free_gb < 5 ? "bad-text" : ""}>{info.disk_free_gb} GB</dd>
              <dt>Users / cases / files</dt>
              <dd>
                {info.users} / {info.cases} / {info.files}
              </dd>
              <dt>Platform</dt>
              <dd className="small">{info.platform}</dd>
              <dt>Python</dt>
              <dd className="small">{info.python}</dd>
              <dt>Version</dt>
              <dd className="small">
                <ShieldCheck size={13} aria-hidden /> Obscura {meta?.version ?? "—"}
              </dd>
            </dl>
          </section>
        </div>
      )}
    </div>
  );
}
