import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Check, KeyRound, X } from "lucide-react";
import { useAuth, useUser } from "../auth";
import { useToast, errorMessage } from "../components/Toast";
import { Spinner } from "../components/ui";

export function PasswordRules({ password, username, confirm }: { password: string; username: string; confirm?: string }) {
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  const rules: [string, boolean][] = [
    ["At least 12 characters", password.length >= 12],
    ["Three of: lower case, upper case, digits, symbols", classes >= 3],
    ["Does not contain the username", !!password && (!username || !password.toLowerCase().includes(username.toLowerCase()))],
  ];
  if (confirm !== undefined) rules.push(["Both entries match", !!password && password === confirm]);
  return (
    <ul className="pw-rules" aria-label="Password requirements">
      {rules.map(([label, ok]) => (
        <li key={label} className={ok ? "ok" : "pending"}>
          {ok ? <Check size={14} aria-hidden /> : <X size={14} aria-hidden />}
          <span>{label}</span>
          <span className="sr-only">{ok ? "(met)" : "(not met)"}</span>
        </li>
      ))}
    </ul>
  );
}

export function ChangePasswordPage() {
  const user = useUser();
  const { changePassword, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const forced = user.must_change_password;

  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(next)).length;
  const valid =
    next.length >= 12 && classes >= 3 && !next.toLowerCase().includes(user.username.toLowerCase()) && next === confirm && !!current;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) {
      setError("The new password does not meet the requirements yet.");
      return;
    }
    if (next === current) {
      setError("Choose a password different from the current one.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success("Password changed");
      navigate("/cases", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={forced ? "auth-screen" : "page page-narrow"}>
      <form className={forced ? "auth-card" : "card"} onSubmit={submit} noValidate>
        <div className="auth-brand">
          <span className="brand-mark big" aria-hidden>
            <KeyRound size={24} />
          </span>
          <div>
            <h1>{forced ? "Set a new password" : "Change password"}</h1>
            <p className="muted">
              {forced
                ? "Your account uses a temporary password. Choose a new one to continue."
                : `Signed in as ${user.username}`}
            </p>
          </div>
        </div>
        {error && (
          <div className="notice notice-error" role="alert">
            {error}
          </div>
        )}
        <div className="field">
          <label htmlFor="pw-current">Current password</label>
          <input
            id="pw-current"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoFocus
          />
        </div>
        <div className="field">
          <label htmlFor="pw-new">New password</label>
          <input
            id="pw-new"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            aria-describedby="pw-rules"
          />
        </div>
        <div className="field">
          <label htmlFor="pw-confirm">Confirm new password</label>
          <input
            id="pw-confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </div>
        <div id="pw-rules">
          <PasswordRules password={next} username={user.username} confirm={confirm} />
        </div>
        <div className="row gap">
          <button className="btn btn-primary" type="submit" disabled={busy || !valid}>
            {busy && <Spinner size={14} />} Save new password
          </button>
          {forced ? (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={async () => {
                await logout();
                navigate("/login", { replace: true });
              }}
            >
              Sign out
            </button>
          ) : (
            <button type="button" className="btn btn-ghost" onClick={() => navigate(-1)}>
              Cancel
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
