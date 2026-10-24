// First-run setup wizard: which steps apply, what each step needs, and the body sent to POST /api/setup/complete.

import { passwordProblems } from "./format";
import type { AppMode, SetupCompleteIn, SetupModel, SetupNeeded } from "../types";

export type StepKey = "welcome" | "mode" | "location" | "models" | "admin" | "options" | "review";

export const STEP_TITLES: Record<StepKey, string> = {
  welcome: "Welcome",
  mode: "How you'll use it",
  location: "Case files",
  models: "AI models",
  admin: "Administrator",
  options: "Options",
  review: "Review & finish",
};

export interface SetupChoices {
  mode: AppMode;
  /** "Just this computer": optionally require a password here too */
  requireLogin: boolean;
  dataDir: string;
  port: number;
  autostart: boolean;
  adminUsername: string;
  adminFullName: string;
  adminPassword: string;
  adminConfirm: string;
}

export function initialChoices(s: SetupNeeded): SetupChoices {
  return {
    mode: s.defaults.mode ?? "single",
    requireLogin: false,
    dataDir: s.defaults.data_dir,
    port: s.defaults.port,
    autostart: !!s.defaults.autostart && s.autostart_available,
    adminUsername: "admin",
    adminFullName: "",
    adminPassword: "",
    adminConfirm: "",
  };
}

/** Sign-in applies to an office server always, and to a single computer when asked for. */
export function needsAdmin(c: Pick<SetupChoices, "mode" | "requireLogin">): boolean {
  return c.mode === "office" || c.requireLogin;
}

export function wizardSteps(s: Pick<SetupNeeded, "autostart_available">, c: Pick<SetupChoices, "mode" | "requireLogin">): StepKey[] {
  const steps: StepKey[] = ["welcome", "mode", "location", "models"];
  if (needsAdmin(c)) steps.push("admin");
  if (s.autostart_available) steps.push("options");
  steps.push("review");
  return steps;
}

/** Mirrors the server: lower-case letters, digits, . _ - ; "local" is the built-in account. */
export function usernameProblem(raw: string): string | null {
  const u = raw.trim().toLowerCase();
  if (!u) return "Choose a user name.";
  if (u === "local") return "“local” is reserved for the built-in account.";
  if (!/^[a-z0-9._-]+$/.test(u) || !/[a-z0-9]/.test(u)) return "Use letters, digits, dots, dashes or underscores only.";
  return null;
}

/** Problems that keep the user on a step (empty = can continue). */
export function stepProblems(step: StepKey, c: SetupChoices): string[] {
  if (step === "location") {
    const p = c.dataDir.trim();
    if (!p) return ["Choose a folder for the case files."];
    if (!(p.startsWith("/") || p.startsWith("~") || /^[A-Za-z]:[\\/]/.test(p) || p.startsWith("\\\\")))
      return ["Enter a full folder path (for example /Users/you/Obscura or C:\\Obscura)."];
    return [];
  }
  if (step === "mode" && c.mode === "office") {
    if (!Number.isInteger(c.port) || c.port < 1024 || c.port > 65535) return ["The port must be between 1024 and 65535."];
    return [];
  }
  if (step === "admin" && needsAdmin(c)) {
    const out: string[] = [];
    const u = usernameProblem(c.adminUsername);
    if (u) out.push(u);
    const pw = passwordProblems(c.adminPassword, c.adminUsername.trim().toLowerCase());
    if (pw.length) out.push(...pw.map((x) => `Password: ${x}`));
    else if (c.adminPassword !== c.adminConfirm) out.push("The two passwords do not match.");
    return out;
  }
  return [];
}

export function completeBody(c: SetupChoices, s: Pick<SetupNeeded, "autostart_available" | "defaults">): SetupCompleteIn {
  const admin = needsAdmin(c);
  const body: SetupCompleteIn = {
    mode: c.mode,
    require_login: c.mode === "office" ? true : c.requireLogin,
    admin_username: admin ? c.adminUsername.trim().toLowerCase() : null,
    admin_password: admin ? c.adminPassword : null,
    admin_full_name: admin ? c.adminFullName.trim() : "",
    data_dir: c.dataDir.trim(),
    autostart: s.autostart_available ? c.autostart : false,
  };
  if (c.mode === "office" && c.port !== s.defaults.port) body.port = c.port;
  return body;
}

/** The step a server error (400 detail) belongs to, so it can be shown next to the right fields. */
export function stepForError(detail: string): StepKey {
  const d = detail.toLowerCase();
  if (/password|user ?name|administrator/.test(d)) return "admin";
  if (/folder|path|write/.test(d)) return "location";
  if (/port/.test(d)) return "mode";
  return "review";
}

export function missingModels(models: SetupModel[]): { required: SetupModel[]; optional: SetupModel[]; downloadGb: number } {
  const missing = models.filter((m) => !m.present);
  const gb = missing.reduce((n, m) => n + (m.size_gb || 0), 0);
  return {
    required: missing.filter((m) => m.required),
    optional: missing.filter((m) => !m.required),
    downloadGb: Math.round(gb * 10) / 10,
  };
}
