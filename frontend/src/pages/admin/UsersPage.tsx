import { useEffect, useState, type FormEvent } from "react";
import { Copy, KeyRound, Lock, Plus, RefreshCw, Unlock, UserCheck, UserX } from "lucide-react";
import * as api from "../../api";
import { useUser } from "../../auth";
import { useToast } from "../../components/Toast";
import { ErrorState, Field, Loading, Modal, Spinner } from "../../components/ui";
import { PasswordRules } from "../ChangePasswordPage";
import { formatDate, generatePassword, passwordProblems } from "../../lib/format";
import type { Role, UserDirectoryEntry } from "../../types";

const ROLES: { key: Role; label: string }[] = [
  { key: "admin", label: "Admin — everything, users and system" },
  { key: "supervisor", label: "Supervisor — all cases, approvals, audit" },
  { key: "redactor", label: "Redactor — their cases: upload, review, export" },
  { key: "viewer", label: "Viewer — redacted exports only" },
];

function TempPasswordField({ value, onChange, username, id }: { value: string; onChange: (v: string) => void; username: string; id: string }) {
  const toast = useToast();
  return (
    <Field label="Temporary password" htmlFor={id} hint="The user must change it at first sign-in. Hand it over in person or by phone.">
      <div className="row gap-sm">
        <input id={id} className="mono grow" value={value} onChange={(e) => onChange(e.target.value)} autoComplete="off" spellCheck={false} />
        <button type="button" className="btn btn-sm" onClick={() => onChange(generatePassword())} title="Generate">
          <RefreshCw size={14} aria-hidden /> Generate
        </button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={!value}
          onClick={() => navigator.clipboard?.writeText(value).then(() => toast.info("Copied to clipboard"), () => toast.error("Copy failed"))}
          title="Copy"
        >
          <Copy size={14} aria-hidden />
        </button>
      </div>
      <PasswordRules password={value} username={username} />
    </Field>
  );
}

function CreateUserDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("redactor");
  const [password, setPassword] = useState(() => generatePassword());
  const [busy, setBusy] = useState(false);
  const valid = /^[a-z0-9._-]+$/i.test(username.trim()) && passwordProblems(password, username.trim()).length === 0;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    try {
      await api.createUser({ username: username.trim().toLowerCase(), full_name: fullName, email, role, password });
      toast.success("User created");
      onCreated();
    } catch (err) {
      toast.error(err, "Could not create user");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="New user"
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-primary" type="submit" form="new-user" disabled={busy || !valid}>
            {busy && <Spinner size={14} />} Create user
          </button>
        </>
      }
    >
      <form id="new-user" className="form-grid" onSubmit={submit}>
        <Field label="Username" htmlFor="nu-user" hint="Letters, digits, . _ -">
          <input id="nu-user" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" spellCheck={false} />
        </Field>
        <Field label="Role" htmlFor="nu-role">
          <select id="nu-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Full name" htmlFor="nu-name">
          <input id="nu-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </Field>
        <Field label="Email (optional)" htmlFor="nu-email">
          <input id="nu-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <div className="span-2">
          <TempPasswordField id="nu-pw" value={password} onChange={setPassword} username={username} />
        </div>
      </form>
    </Modal>
  );
}

function ResetPasswordDialog({ user, onClose }: { user: UserDirectoryEntry; onClose: () => void }) {
  const toast = useToast();
  const [password, setPassword] = useState(() => generatePassword());
  const [busy, setBusy] = useState(false);
  const valid = passwordProblems(password, user.username).length === 0;
  const submit = async () => {
    setBusy(true);
    try {
      await api.resetUserPassword(user.id, password);
      toast.success(`Password reset for ${user.username}; they must change it at next sign-in`);
      onClose();
    } catch (e) {
      toast.error(e, "Could not reset password");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={`Reset password — ${user.username}`}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={busy || !valid}>
            {busy && <Spinner size={14} />} Reset password
          </button>
        </>
      }
    >
      <p className="small muted">All of the user's sessions are signed out and the account is unlocked.</p>
      <TempPasswordField id="rp-pw" value={password} onChange={setPassword} username={user.username} />
    </Modal>
  );
}

export function UsersPage() {
  const me = useUser();
  const toast = useToast();
  const [users, setUsers] = useState<UserDirectoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<UserDirectoryEntry | null>(null);

  const load = () => {
    setError(null);
    api.listUsers().then(setUsers, (e) => setError(e instanceof Error ? e.message : "failed"));
  };
  useEffect(load, []);

  const patch = async (u: UserDirectoryEntry, body: Parameters<typeof api.updateUser>[1], msg: string) => {
    try {
      await api.updateUser(u.id, body);
      toast.success(msg);
      load();
    } catch (e) {
      toast.error(e, "Could not update user");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Users</h1>
          <p className="muted">Accounts are local to this server. Five failed sign-ins lock an account for 15 minutes.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          <Plus size={16} aria-hidden /> New user
        </button>
      </div>
      {error && <ErrorState message={error} onRetry={load} />}
      {!users && !error && <Loading />}
      {users && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>State</th>
                <th>Last sign-in</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className={u.is_active === false ? "row-muted" : ""}>
                  <td className="mono strong">{u.username}</td>
                  <td>{u.full_name || "—"}</td>
                  <td className="small">{u.email || "—"}</td>
                  <td>
                    <select
                      aria-label={`Role of ${u.username}`}
                      value={u.role}
                      disabled={u.id === me.id}
                      onChange={(e) => patch(u, { role: e.target.value as Role }, "Role changed (user signed out)")}
                    >
                      {ROLES.map((r) => (
                        <option key={r.key} value={r.key}>
                          {r.key}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <div className="row gap-sm wrap">
                      {u.is_active === false ? <span className="badge badge-neutral">inactive</span> : <span className="badge badge-ok">active</span>}
                      {u.locked && (
                        <span className="badge badge-bad">
                          <Lock size={11} aria-hidden /> locked
                        </span>
                      )}
                      {u.must_change_password && <span className="badge badge-warn">must change password</span>}
                    </div>
                  </td>
                  <td className="small">{formatDate(u.last_login, true)}</td>
                  <td className="actions-col">
                    <div className="row-actions">
                      {u.locked && (
                        <button className="btn btn-xs" onClick={() => patch(u, { unlock: true }, "Account unlocked")}>
                          <Unlock size={12} aria-hidden /> Unlock
                        </button>
                      )}
                      <button className="btn btn-xs" onClick={() => setResetting(u)}>
                        <KeyRound size={12} aria-hidden /> Reset password
                      </button>
                      {u.id !== me.id &&
                        (u.is_active === false ? (
                          <button className="btn btn-xs" onClick={() => patch(u, { is_active: true }, "User reactivated")}>
                            <UserCheck size={12} aria-hidden /> Activate
                          </button>
                        ) : (
                          <button className="btn btn-xs btn-danger-ghost" onClick={() => patch(u, { is_active: false }, "User deactivated")}>
                            <UserX size={12} aria-hidden /> Deactivate
                          </button>
                        ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && (
        <CreateUserDialog
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            load();
          }}
        />
      )}
      {resetting && (
        <ResetPasswordDialog
          user={resetting}
          onClose={() => {
            setResetting(null);
            load();
          }}
        />
      )}
    </div>
  );
}
