import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  Briefcase,
  ChevronDown,
  Cpu,
  FolderInput,
  KeyRound,
  LayoutTemplate,
  ListChecks,
  LogOut,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  Users,
  X,
} from "lucide-react";
import { hasRole, useAuth, useUser } from "../auth";
import { useJobs } from "../jobs";
import * as api from "../api";
import { loadTheme, saveTheme, type Theme } from "../lib/theme";
import { ProgressBar, Spinner } from "./ui";
import { useToast } from "./Toast";
import { statusLabel, titleCase } from "../lib/format";

function useOutsideClose(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return ref;
}

function JobsIndicator() {
  const { active } = useJobs();
  const user = useUser();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(open, () => setOpen(false));
  const n = active.length;
  return (
    <div className="popover-anchor" ref={ref}>
      <button
        className={`topbar-btn ${n ? "has-jobs" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={n ? `${n} background job${n > 1 ? "s" : ""} running` : "No background jobs"}
      >
        {n ? <Spinner size={15} /> : <Activity size={15} aria-hidden />}
        <span>{n ? `${n} job${n > 1 ? "s" : ""}` : "Idle"}</span>
      </button>
      {open && (
        <div className="popover jobs-popover" role="dialog" aria-label="Background jobs">
          <div className="popover-title">Background jobs</div>
          {n === 0 && <div className="muted small pad">Nothing is running.</div>}
          <ul className="jobs-list">
            {active.map((j) => (
              <li key={j.id}>
                <div className="job-row">
                  <span className="job-kind">{titleCase(j.kind)}</span>
                  {j.file_id ? (
                    <Link to={`/files/${j.file_id}`} onClick={() => setOpen(false)} className="small">
                      file #{j.file_id}
                    </Link>
                  ) : null}
                  <span className="muted small">{statusLabel(j.status)}</span>
                  {hasRole(user, "redactor") && (
                    <button
                      className="icon-btn"
                      aria-label={`Cancel job ${j.id}`}
                      title="Cancel"
                      onClick={() => api.cancelJob(j.id).then(() => toast.info("Cancellation requested"), (e) => toast.error(e))}
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
                <ProgressBar value={j.progress} label={`Job ${j.id} progress`} indeterminate={j.status === "queued"} />
                {j.message && <div className="muted small job-msg">{j.message}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function UserMenu({ theme, onTheme }: { theme: Theme; onTheme: (t: Theme) => void }) {
  const user = useUser();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(open, () => setOpen(false));
  return (
    <div className="popover-anchor" ref={ref}>
      <button
        className="topbar-btn"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.full_name || user.username} (${user.role})`}
      >
        <span className="avatar" aria-hidden>
          {(user.full_name || user.username).slice(0, 1).toUpperCase()}
        </span>
        <span className="user-name">{user.full_name || user.username}</span>
        <span className="badge badge-neutral">{user.role}</span>
        <ChevronDown size={14} aria-hidden />
      </button>
      {open && (
        <div className="popover menu" role="menu">
          <div className="menu-head">
            <div className="strong">{user.local ? "Signed in automatically" : user.username}</div>
            {user.local && <div className="muted small">Sign-in is off on this computer</div>}
            {user.email && <div className="muted small">{user.email}</div>}
          </div>
          {!user.local && (
            <button
              role="menuitem"
              className="menu-item"
              onClick={() => {
                setOpen(false);
                navigate("/change-password");
              }}
            >
              <KeyRound size={15} aria-hidden /> Change password
            </button>
          )}
          <button role="menuitem" className="menu-item" onClick={() => onTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? <Sun size={15} aria-hidden /> : <Moon size={15} aria-hidden />}
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
          {!user.local && (
            <button
              role="menuitem"
              className="menu-item"
              onClick={async () => {
                setOpen(false);
                await logout();
                navigate("/login", { replace: true });
              }}
            >
              <LogOut size={15} aria-hidden /> Sign out
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const NAV_KEY = "obscura.nav";

export function Layout() {
  const user = useUser();
  const location = useLocation();
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [collapsedPref, setCollapsedPref] = useState<boolean>(() => {
    try {
      return localStorage.getItem(NAV_KEY) === "collapsed";
    } catch {
      return false;
    }
  });
  const inReview = location.pathname.startsWith("/files/");
  const collapsed = collapsedPref || inReview;

  const toggleNav = () => {
    const next = !collapsedPref;
    setCollapsedPref(next);
    try {
      localStorage.setItem(NAV_KEY, next ? "collapsed" : "open");
    } catch {
      /* ignore */
    }
  };

  const onTheme = (t: Theme) => {
    setTheme(t);
    saveTheme(t);
  };

  const supervisor = hasRole(user, "supervisor");
  const admin = hasRole(user, "admin");
  const redactor = hasRole(user, "redactor");

  const item = (to: string, icon: React.ReactNode, label: string) => (
    <NavLink to={to} className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")} title={collapsed ? label : undefined}>
      {icon}
      <span className="nav-label">{label}</span>
    </NavLink>
  );

  return (
    <div className={`app ${collapsed ? "nav-collapsed" : ""}`}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sidenav" aria-label="Main navigation">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            <ShieldCheck size={20} />
          </span>
          <span className="brand-text">
            Obscura <span className="brand-sub">Redaction Studio</span>
          </span>
        </div>
        <nav className="nav">
          {item("/cases", <Briefcase size={18} aria-hidden />, "Cases")}
          {redactor && (
            <>
              <div className="nav-section">Library</div>
              {item("/library/lists", <ListChecks size={18} aria-hidden />, "Term lists")}
              {item("/library/templates", <LayoutTemplate size={18} aria-hidden />, "Templates")}
              {item("/library/presets", <SlidersHorizontal size={18} aria-hidden />, "Presets")}
            </>
          )}
          {supervisor && (
            <>
              <div className="nav-section">Oversight</div>
              {item("/audit", <ScrollText size={18} aria-hidden />, "Audit log")}
            </>
          )}
          {admin && (
            <>
              <div className="nav-section">Admin</div>
              {item("/admin/users", <Users size={18} aria-hidden />, "Users")}
              {item("/admin/watchers", <FolderInput size={18} aria-hidden />, "Watchers")}
              {item("/admin/system", <Cpu size={18} aria-hidden />, "System")}
            </>
          )}
        </nav>
        {!inReview && (
          <button className="nav-collapse" onClick={toggleNav} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}>
            {collapsed ? <PanelLeftOpen size={18} aria-hidden /> : <PanelLeftClose size={18} aria-hidden />}
          </button>
        )}
      </aside>
      <div className="main-col">
        <header className="topbar">
          <div className="topbar-left">
            <span className="offline-badge" title="All processing happens on this server. Nothing is sent to the internet.">
              <ShieldCheck size={14} aria-hidden /> On-premises · offline
            </span>
          </div>
          <div className="topbar-right">
            <JobsIndicator />
            <button
              className="topbar-btn"
              onClick={() => onTheme(theme === "dark" ? "light" : "dark")}
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              data-tip={theme === "dark" ? "Light theme" : "Dark theme"}
            >
              {theme === "dark" ? <Sun size={15} aria-hidden /> : <Moon size={15} aria-hidden />}
            </button>
            <UserMenu theme={theme} onTheme={onTheme} />
          </div>
        </header>
        <main id="main" className={inReview ? "content content-full" : "content"} tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
