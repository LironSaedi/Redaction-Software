// Small display helpers (no PII ever leaves the page through these).

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return withTime
    ? d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** `YYYY-MM-DD` for <input type="date"> from an ISO timestamp. */
export function toDateInput(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** ISO timestamp (noon local time, avoids TZ day shifts) from a date input value. */
export function fromDateInput(value: string): string | null {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d, 12, 0, 0).toISOString();
}

export function isOverdue(due: string | null | undefined, status?: string): boolean {
  if (!due || status === "completed" || status === "closed") return false;
  const d = new Date(due);
  if (Number.isNaN(d.getTime())) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return d.getTime() < today.getTime();
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(sec)}` : `${m}:${p(sec)}`;
}

/** mm:ss.t for media scrubbing. */
export function formatTimecode(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${m}:${s < 10 ? "0" : ""}${s.toFixed(1)}`;
}

export function percent(v: number | null | undefined, digits = 0): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function truncate(s: string, n: number): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function titleCase(s: string): string {
  return s
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export const STATUS_LABELS: Record<string, string> = {
  uploaded: "Uploaded",
  analyzing: "Analyzing",
  ready: "Ready for review",
  in_review: "In review",
  approved: "Approved",
  exported: "Exported",
  error: "Error",
  open: "Open",
  completed: "Completed",
  closed: "Closed",
  queued: "Queued",
  running: "Running",
  done: "Done",
  cancelled: "Cancelled",
};

export function statusLabel(s: string): string {
  return STATUS_LABELS[s] ?? titleCase(s);
}

export const REQUEST_TYPES = [
  "FOIA",
  "Public records",
  "Discovery",
  "Subpoena",
  "Medical records release",
  "Internal",
  "Other",
];

export const CASE_STATUSES = ["open", "in_review", "completed", "closed"];

export const KIND_LABELS: Record<string, string> = {
  pdf: "PDF",
  image: "Image",
  video: "Video",
  audio: "Audio",
  docx: "Word",
  pptx: "PowerPoint",
  xlsx: "Excel",
  email: "Email",
  text: "Text",
  tiff: "TIFF",
};

export function isPaged(kind: string): boolean {
  return kind === "pdf" || kind === "image" || kind === "email";
}

export function isTextKind(kind: string): boolean {
  return kind === "docx" || kind === "pptx" || kind === "xlsx" || kind === "text";
}

/** Strong random temporary password satisfying the server rules (≥12, 3 classes, no username). */
export function generatePassword(length = 16): string {
  const lower = "abcdefghjkmnpqrstuvwxyz";
  const upper = "ABCDEFGHJKMNPQRSTUVWXYZ";
  const digits = "23456789";
  const symbols = "!#$%&*+-=?@";
  const all = lower + upper + digits + symbols;
  const rnd = (n: number) => {
    const a = new Uint32Array(1);
    crypto.getRandomValues(a);
    return a[0] % n;
  };
  const chars = [lower[rnd(lower.length)], upper[rnd(upper.length)], digits[rnd(digits.length)], symbols[rnd(symbols.length)]];
  while (chars.length < length) chars.push(all[rnd(all.length)]);
  for (let i = chars.length - 1; i > 0; i--) {
    const j = rnd(i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

/** Client-side mirror of the server password rules, for live feedback. */
export function passwordProblems(pw: string, username = ""): string[] {
  const probs: string[] = [];
  if (pw.length < 12) probs.push("At least 12 characters");
  if (username && pw.toLowerCase().includes(username.toLowerCase())) probs.push("Must not contain the username");
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length;
  if (classes < 3) probs.push("Use three of: lower case, upper case, digits, symbols");
  return probs;
}
