import { useEffect, useId, useRef, type ReactNode } from "react";
import {
  AlertTriangle,
  FileAudio,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType2,
  FileVideo,
  Loader2,
  Mail,
  Presentation,
  X,
} from "lucide-react";
import { statusLabel } from "../lib/format";

// ---- Modal -------------------------------------------------------------------------------------------

interface ModalProps {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  /** prevent closing with Esc / backdrop while a request is running */
  busy?: boolean;
}

export function Modal({ title, onClose, children, footer, size = "md", busy = false }: ModalProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    // focus priority: an explicit [data-autofocus], then the first field, then the first button in the body
    const first =
      el?.querySelector<HTMLElement>("[data-autofocus]") ??
      el?.querySelector<HTMLElement>(
        ".modal-body input:not([type=hidden]):not([disabled]), .modal-body select:not([disabled]), .modal-body textarea:not([disabled])",
      ) ??
      el?.querySelector<HTMLElement>(".modal-body button:not([disabled]), .modal-footer button:not([disabled])") ??
      el?.querySelector<HTMLElement>("button");
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busyRef.current) {
        e.stopPropagation();
        closeRef.current();
      }
      if (e.key === "Tab" && el) {
        const items = Array.from(
          el.querySelectorAll<HTMLElement>(
            "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
          ),
        ).filter((n) => n.offsetParent !== null);
        if (!items.length) return;
        const a = items[0];
        const z = items[items.length - 1];
        if (e.shiftKey && document.activeElement === a) {
          e.preventDefault();
          z.focus();
        } else if (!e.shiftKey && document.activeElement === z) {
          e.preventDefault();
          a.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      prev?.focus?.();
    };
  }, []);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div ref={ref} className={`modal modal-${size}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className="modal-header">
          <h2 id={titleId}>{title}</h2>
          <button className="icon-btn" onClick={onClose} disabled={busy} aria-label="Close dialog">
            <X size={18} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-footer">{footer}</footer>}
      </div>
    </div>
  );
}

interface ConfirmProps {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ title, message, confirmLabel = "Confirm", danger, busy, onConfirm, onCancel }: ConfirmProps) {
  return (
    <Modal
      title={title}
      onClose={onCancel}
      size="sm"
      busy={busy}
      footer={
        <>
          <button className="btn" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button className={danger ? "btn btn-danger" : "btn btn-primary"} onClick={onConfirm} disabled={busy} data-autofocus>
            {busy && <Spinner size={14} />} {confirmLabel}
          </button>
        </>
      }
    >
      <div className="confirm-message">{message}</div>
    </Modal>
  );
}

// ---- Small pieces ------------------------------------------------------------------------------------

export function Spinner({ size = 16, label }: { size?: number; label?: string }) {
  return (
    <span className="spinner" role={label ? "status" : undefined} aria-label={label}>
      <Loader2 size={size} className="spin" aria-hidden />
    </span>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <Loader2 size={20} className="spin" aria-hidden /> <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action,
  compact = false,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`empty-state ${compact ? "compact" : ""}`}>
      {icon && <div className="empty-icon" aria-hidden>{icon}</div>}
      <h3>{title}</h3>
      {children && <div className="empty-body">{children}</div>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-state" role="alert">
      <AlertTriangle size={20} aria-hidden />
      <span>{message}</span>
      {onRetry && (
        <button className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function ProgressBar({ value, label, indeterminate }: { value: number; label?: string; indeterminate?: boolean }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div
      className={`progress ${indeterminate ? "progress-indeterminate" : ""}`}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : pct}
      aria-label={label ?? "Progress"}
    >
      <div className="progress-fill" style={{ width: indeterminate ? "40%" : `${pct}%` }} />
    </div>
  );
}

const STATUS_TONES: Record<string, string> = {
  uploaded: "neutral",
  analyzing: "info",
  ready: "info",
  in_review: "warn",
  approved: "ok",
  exported: "ok",
  error: "bad",
  open: "info",
  completed: "ok",
  closed: "neutral",
  queued: "neutral",
  running: "info",
  done: "ok",
  cancelled: "neutral",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${STATUS_TONES[status] ?? "neutral"}`}>{statusLabel(status)}</span>;
}

export function KindIcon({ kind, size = 16 }: { kind: string; size?: number }) {
  const props = { size, "aria-hidden": true } as const;
  switch (kind) {
    case "pdf":
      return <FileType2 {...props} className="kind-icon kind-pdf" />;
    case "image":
    case "tiff":
      return <FileImage {...props} className="kind-icon kind-image" />;
    case "video":
      return <FileVideo {...props} className="kind-icon kind-video" />;
    case "audio":
      return <FileAudio {...props} className="kind-icon kind-audio" />;
    case "xlsx":
      return <FileSpreadsheet {...props} className="kind-icon kind-office" />;
    case "pptx":
      return <Presentation {...props} className="kind-icon kind-office" />;
    case "email":
      return <Mail {...props} className="kind-icon kind-email" />;
    default:
      return <FileText {...props} className="kind-icon kind-office" />;
  }
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
  className,
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
  className?: string;
}) {
  return (
    <div className={`field ${className ?? ""}`}>
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && <div className="field-hint">{hint}</div>}
    </div>
  );
}

export interface TabDef<K extends string> {
  key: K;
  label: ReactNode;
  hidden?: boolean;
}

export function Tabs<K extends string>({
  tabs,
  active,
  onChange,
  label,
  idPrefix = "tab",
  className = "",
}: {
  tabs: TabDef<K>[];
  active: K;
  onChange: (k: K) => void;
  label: string;
  idPrefix?: string;
  className?: string;
}) {
  const visible = tabs.filter((t) => !t.hidden);
  return (
    <div className={`tabs ${className}`} role="tablist" aria-label={label}>
      {visible.map((t, i) => (
        <button
          key={t.key}
          role="tab"
          id={`${idPrefix}-${t.key}`}
          aria-selected={t.key === active}
          tabIndex={t.key === active ? 0 : -1}
          className={t.key === active ? "tab active" : "tab"}
          onClick={() => onChange(t.key)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
              e.preventDefault();
              const n = visible[(i + (e.key === "ArrowRight" ? 1 : visible.length - 1)) % visible.length];
              onChange(n.key);
              document.getElementById(`${idPrefix}-${n.key}`)?.focus();
            }
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const tone = pct >= 85 ? "high" : pct >= 60 ? "mid" : "low";
  return (
    <span className={`conf conf-${tone}`} title={`Confidence ${pct}%`} aria-label={`Confidence ${pct}%`}>
      <span className="conf-track">
        <span className="conf-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="conf-num">{pct}</span>
    </span>
  );
}

/** Compact confidence pill (colour + number, so colour is never the only signal). */
export function ConfidenceBadge({ score, compact = false }: { score: number; compact?: boolean }) {
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const tone = pct >= 85 ? "high" : pct >= 60 ? "mid" : "low";
  const word = tone === "high" ? "high" : tone === "mid" ? "medium" : "low";
  return (
    <span className={`conf-badge conf-${tone}`} title={`Confidence ${pct}% (${word})`} aria-label={`Confidence ${pct}%`}>
      {pct}
      {!compact && "%"}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

/** Placeholder shimmer while content loads. */
export function Skeleton({ width, height = 12, className = "" }: { width?: number | string; height?: number | string; className?: string }) {
  return <span className={`skeleton ${className}`} style={{ width, height }} aria-hidden />;
}

/** A few skeleton rows for lists (detection list, tracks, pictures). */
export function SkeletonList({ rows = 6, label = "Loading…" }: { rows?: number; label?: string }) {
  return (
    <div className="skeleton-list" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton-row">
          <Skeleton width={14} height={14} />
          <Skeleton width={`${50 + ((i * 37) % 40)}%`} />
          <Skeleton width={28} height={16} className="ml-auto" />
        </div>
      ))}
    </div>
  );
}

/** Accessible on/off switch (a checkbox styled as a toggle). */
export function Switch({
  checked,
  onChange,
  label,
  hint,
  disabled,
  id,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  id?: string;
}) {
  const uid = useId();
  return (
    <label className={`switch-row ${disabled ? "is-disabled" : ""}`}>
      <input
        id={id}
        type="checkbox"
        role="switch"
        className="switch-input"
        checked={checked}
        disabled={disabled}
        aria-labelledby={`${uid}-l`}
        aria-describedby={hint ? `${uid}-h` : undefined}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="switch-track" aria-hidden>
        <span className="switch-thumb" />
      </span>
      <span className="switch-text">
        <span id={`${uid}-l`}>{label}</span>
        {hint && (
          <span id={`${uid}-h`} className="field-hint block">
            {hint}
          </span>
        )}
      </span>
    </label>
  );
}
