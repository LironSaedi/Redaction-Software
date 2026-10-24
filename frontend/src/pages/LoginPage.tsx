import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Lock, ShieldCheck } from "lucide-react";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { Spinner } from "../components/ui";

export function LoginPage() {
  const { login, status, user, notice, clearNotice } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status === "authenticated" && user) {
    return <Navigate to={user.must_change_password ? "/change-password" : "/cases"} replace />;
  }

  const from = (location.state as { from?: string } | null)?.from;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setBusy(true);
    setError(null);
    clearNotice();
    try {
      const u = await login(username.trim(), password);
      setPassword("");
      if (u.must_change_password) navigate("/change-password", { replace: true });
      else navigate(from && from.startsWith("/") && !from.startsWith("//") ? from : "/cases", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) setError("Invalid username or password.");
        else if (err.status === 423)
          setError("This account is temporarily locked after repeated failed sign-ins. Try again in 15 minutes or ask an administrator to unlock it.");
        else if (err.status === 429) setError("Too many sign-in attempts. Wait a minute and try again.");
        else setError(err.detail);
      } else setError("Sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={submit} noValidate>
        <div className="auth-brand">
          <span className="brand-mark big" aria-hidden>
            <ShieldCheck size={26} />
          </span>
          <div>
            <h1>Obscura Redaction Studio</h1>
            <p className="muted">Sign in to continue</p>
          </div>
        </div>
        {notice && (
          <div className="notice notice-info" role="status">
            {notice}
          </div>
        )}
        {error && (
          <div className="notice notice-error" role="alert">
            {error}
          </div>
        )}
        <div className="field">
          <label htmlFor="login-user">Username</label>
          <input
            id="login-user"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            spellCheck={false}
            autoCapitalize="none"
          />
        </div>
        <div className="field">
          <label htmlFor="login-pass">Password</label>
          <input
            id="login-pass"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button className="btn btn-primary btn-block" type="submit" disabled={busy}>
          {busy ? <Spinner size={15} /> : <Lock size={15} aria-hidden />} Sign in
        </button>
        <p className="auth-foot muted small">
          <ShieldCheck size={13} aria-hidden /> On-premises · offline. Files never leave this server.
        </p>
      </form>
    </div>
  );
}
