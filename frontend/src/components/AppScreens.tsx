import { useEffect, useState, type ReactNode } from "react";
import { CheckCircle2, Loader2, LogOut, RefreshCw, ShieldCheck } from "lucide-react";
import { pingHealth, waitForRestart } from "../lib/restart";

/** Full-screen panel used by the setup wizard, restarts and uninstall. */
export function FullScreen({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="auth-screen setup-screen screen-overlay" role="dialog" aria-modal="true">
      <div className={`auth-card screen-card ${wide ? "wide" : ""}`}>{children}</div>
    </div>
  );
}

interface RestartProps {
  title?: string;
  message?: ReactNode;
  /** where to go once Obscura answers again */
  target?: string;
  extra?: ReactNode;
  /** GET /api/health → boot, read before the restart was requested */
  previousBoot?: string | null;
}

/** "Restarting Obscura…": waits for /api/health to answer again, then reloads the app. */
export function RestartScreen({ title = "Restarting Obscura with your settings…", message, target = "/", extra, previousBoot }: RestartProps) {
  const [state, setState] = useState<"waiting" | "timeout">("waiting");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const ctl = new AbortController();
    waitForRestart({ ping: pingHealth, previousBoot, signal: ctl.signal, timeoutMs: 120_000 }).then((r) => {
      if (r === "up") window.location.assign(target);
      else if (r === "timeout") setState("timeout");
    });
    return () => ctl.abort();
  }, [target, attempt, previousBoot]);
  return (
    <FullScreen>
      <div className="screen-icon" aria-hidden>
        {state === "waiting" ? <Loader2 size={30} className="spin" /> : <RefreshCw size={30} />}
      </div>
      <h1 className="screen-title" role="status">
        {state === "waiting" ? title : "Obscura has not come back yet"}
      </h1>
      {state === "waiting" ? (
        <p className="muted center">{message ?? "This takes a few seconds. The page reloads by itself."}</p>
      ) : (
        <>
          <p className="muted center">
            The desktop launcher normally starts it again by itself. If you run Obscura from a terminal, start it again, then
            try once more.
          </p>
          <div className="row gap center-row">
            <button
              className="btn btn-primary"
              onClick={() => {
                setState("waiting");
                setAttempt((a) => a + 1);
              }}
            >
              <RefreshCw size={15} aria-hidden /> Try again
            </button>
          </div>
        </>
      )}
      {extra}
    </FullScreen>
  );
}

/** Shown after "Uninstall Obscura". */
export function GoodbyeScreen({ removedData }: { removedData: boolean }) {
  return (
    <FullScreen>
      <div className="screen-icon ok" aria-hidden>
        <LogOut size={30} />
      </div>
      <h1 className="screen-title">Obscura is being removed — you can close this window.</h1>
      <p className="muted center">
        {removedData
          ? "The case files, exports, audit log and settings are being deleted permanently (the encryption keys go first)."
          : "Your case files, exports and settings stay on this computer, still encrypted."}
      </p>
    </FullScreen>
  );
}

/** A finished step with a next action. */
export function DoneScreen({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <FullScreen>
      <div className="screen-icon ok" aria-hidden>
        <CheckCircle2 size={30} />
      </div>
      <h1 className="screen-title">{title}</h1>
      {children}
      {action && <div className="row gap center-row">{action}</div>}
    </FullScreen>
  );
}

export function PrivacyLine() {
  return (
    <p className="auth-foot small muted">
      <ShieldCheck size={14} aria-hidden /> On-premises · offline. Files never leave this computer.
    </p>
  );
}
