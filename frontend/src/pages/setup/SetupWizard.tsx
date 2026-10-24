import { useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, Copy, Shield } from "lucide-react";
import * as api from "../../api";
import { DoneScreen, PrivacyLine, RestartScreen } from "../../components/AppScreens";
import { Spinner } from "../../components/ui";
import { currentBoot } from "../../lib/restart";
import { completeBody, initialChoices, STEP_TITLES, stepForError, stepProblems, wizardSteps, type SetupChoices, type StepKey } from "../../lib/setup";
import type { SetupCompleteOut, SetupModel, SetupNeeded } from "../../types";
import { AdminStep, LocationStep, ModelsStep, ModeStep, OptionsStep, ReviewStep, WelcomeStep } from "./SetupSteps";

/** First-run setup of an installed copy (GET /api/setup/state → needed). Runs before any account exists. */
export function SetupWizard({ state }: { state: SetupNeeded }) {
  const [c, setC] = useState<SetupChoices>(() => initialChoices(state));
  const [step, setStep] = useState<StepKey>("welcome");
  const [errors, setErrors] = useState<Partial<Record<StepKey, string>>>({});
  const [models, setModels] = useState<SetupModel[]>(state.models);
  const [boot, setBoot] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<SetupCompleteOut | null>(null);
  const [copied, setCopied] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  const steps = useMemo(() => wizardSteps(state, c), [state, c]);
  const idx = Math.max(0, steps.indexOf(step));
  const set = (patch: Partial<SetupChoices>) => {
    setC((x) => ({ ...x, ...patch }));
    setErrors((e) => ({ ...e, [step]: undefined }));
  };

  const go = (to: StepKey) => {
    setStep(to);
    const el = bodyRef.current;
    if (el && typeof el.scrollTo === "function") el.scrollTo({ top: 0 });
  };
  const next = () => {
    const probs = stepProblems(step, c);
    if (probs.length) {
      setErrors((e) => ({ ...e, [step]: probs[0] }));
      return;
    }
    if (idx < steps.length - 1) go(steps[idx + 1]);
  };
  const back = () => idx > 0 && go(steps[idx - 1]);

  const finish = async () => {
    // re-check every step (the user may have jumped back and changed something)
    for (const s of steps) {
      const probs = stepProblems(s, c);
      if (probs.length) {
        setErrors((e) => ({ ...e, [s]: probs[0] }));
        go(s);
        return;
      }
    }
    setBusy(true);
    try {
      setBoot(await currentBoot());
      const res = await api.completeSetup(completeBody(c, state));
      setDone(res);
      if (!res.restart && c.mode === "single") window.location.assign("/");
    } catch (e) {
      const detail = e instanceof api.ApiError ? e.detail : e instanceof Error ? e.message : "setup could not be saved";
      const s = stepForError(detail);
      setErrors((x) => ({ ...x, [s]: detail }));
      go(steps.includes(s) ? s : "review");
    } finally {
      setBusy(false);
    }
  };

  const share = done?.lan_url ? (
    <div className="share-url">
      <div className="small muted">Share this address with your colleagues:</div>
      <div className="row gap-sm">
        <code className="mono">{done.lan_url}</code>
        <button
          className="btn btn-sm"
          onClick={() => {
            void navigator.clipboard?.writeText(done.lan_url ?? "").then(() => setCopied(true), () => undefined);
          }}
        >
          {copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  ) : null;

  if (done?.restart) return <RestartScreen extra={share} previousBoot={boot} />;
  if (done) {
    return (
      <DoneScreen
        title="Obscura is ready"
        action={
          <button className="btn btn-primary" onClick={() => window.location.assign("/")}>
            Open Obscura <ArrowRight size={15} aria-hidden />
          </button>
        }
      >
        {share}
        {done.require_login && <p className="small muted center">Sign in with the administrator account you just created.</p>}
      </DoneScreen>
    );
  }

  const props = { state, c, set, error: errors[step] ?? null };
  return (
    <div className="auth-screen setup-screen">
      <div className="setup-card" role="main" aria-label="Obscura setup">
        <aside className="setup-rail">
          <div className="auth-brand">
            <span className="brand-mark" aria-hidden>
              <Shield size={18} />
            </span>
            <div>
              <div className="strong">Obscura</div>
              <div className="tiny muted">Redaction Studio setup</div>
            </div>
          </div>
          <ol className="setup-steps" aria-label="Setup steps">
            {steps.map((s, i) => {
              const st = i < idx ? "done" : i === idx ? "current" : "todo";
              return (
                <li key={s} className={`setup-step-item ${st} ${errors[s] ? "has-error" : ""}`} aria-current={i === idx ? "step" : undefined}>
                  <button type="button" onClick={() => i < idx && go(s)} disabled={i > idx} aria-label={`Step ${i + 1}: ${STEP_TITLES[s]}`}>
                    <span className="setup-num" aria-hidden>
                      {st === "done" ? <Check size={13} /> : i + 1}
                    </span>
                    <span>{STEP_TITLES[s]}</span>
                  </button>
                </li>
              );
            })}
          </ol>
          <PrivacyLine />
        </aside>
        <section className="setup-main">
          <div className="setup-body" ref={bodyRef}>
            {step === "welcome" && <WelcomeStep {...props} />}
            {step === "mode" && <ModeStep {...props} />}
            {step === "location" && <LocationStep {...props} />}
            {step === "models" && <ModelsStep {...props} models={models} setModels={setModels} />}
            {step === "admin" && <AdminStep {...props} />}
            {step === "options" && <OptionsStep {...props} />}
            {step === "review" && <ReviewStep {...props} models={models} steps={steps} />}
          </div>
          <footer className="setup-footer">
            <span className="tiny muted">
              Step {idx + 1} of {steps.length}
            </span>
            <span className="toolbar-spacer" />
            {idx > 0 && (
              <button className="btn" onClick={back} disabled={busy}>
                <ArrowLeft size={15} aria-hidden /> Back
              </button>
            )}
            {step !== "review" ? (
              <button className="btn btn-primary" onClick={next}>
                {step === "welcome" ? "Get started" : "Continue"} <ArrowRight size={15} aria-hidden />
              </button>
            ) : (
              <button className="btn btn-primary" onClick={finish} disabled={busy}>
                {busy ? <Spinner size={14} /> : <Check size={15} aria-hidden />} Finish
              </button>
            )}
          </footer>
        </section>
      </div>
    </div>
  );
}
