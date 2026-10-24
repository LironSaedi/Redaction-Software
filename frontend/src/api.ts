// Typed client for the Obscura API — one function per endpoint.
//
// Privacy rules enforced here:
//  * the bearer token is sent in the Authorization header (never in a URL);
//  * request bodies / responses are never logged;
//  * URLs only ever contain numeric ids and non-sensitive options.

import type {
  AppInfo,
  AppSettingsIn,
  ExtraTerm,
  ModelsImportOut,
  RedactTextIn,
  RedactTextList,
  RedactTextOut,
  SetupCompleteIn,
  SetupCompleteOut,
  SetupModelsState,
  SetupState,
  AuthMode,
  CaseExport,
  AnalyzeParams,
  AuditEvent,
  AuditQuery,
  AuditVerify,
  AuthResponse,
  BulkJobs,
  CaseDetail,
  CaseIn,
  CasePatch,
  CaseReport,
  CaseSummary,
  Detection,
  DetectionBulk,
  DetectionsResponse,
  DetectionSummary,
  ExportDetail,
  ExportParams,
  FileRecord,
  Job,
  JobRef,
  ManualDetectionIn,
  ManualTrackIn,
  MemberRole,
  Meta,
  Note,
  Ok,
  PagesResponse,
  PageText,
  Preset,
  SearchIn,
  SearchResult,
  SystemInfo,
  Template,
  TemplateIn,
  TermList,
  TermListIn,
  Track,
  TrackPatch,
  TracksResponse,
  Transcript,
  Translation,
  TranslationRef,
  UploadResult,
  User,
  UserDirectoryEntry,
  UserIn,
  UserPatch,
  Watcher,
  WatcherIn,
} from "./types";

export const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail || `request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue>;

interface ApiConfig {
  getToken: () => string | null;
  onUnauthorized: (() => void) | null;
}

const config: ApiConfig = { getToken: () => null, onUnauthorized: null };

/** Wire the client to the auth store (token getter + what to do when the session ends). */
export function configureApi(opts: Partial<ApiConfig>): void {
  if (opts.getToken) config.getToken = opts.getToken;
  if (opts.onUnauthorized !== undefined) config.onUnauthorized = opts.onUnauthorized;
}

/** `?a=1&b=x` from an object; null / undefined / "" values are dropped. */
export function buildQuery(params?: Query): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** FastAPI errors: {detail: "text"} or {detail: [{loc, msg}]} (validation). */
export function formatDetail(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((e) => {
          if (e && typeof e === "object") {
            const o = e as { msg?: unknown; loc?: unknown };
            const loc = Array.isArray(o.loc) ? o.loc.filter((p) => p !== "body").join(".") : "";
            return `${loc ? loc + ": " : ""}${String(o.msg ?? "invalid value")}`;
          }
          return String(e);
        })
        .join("; ");
    }
    if (d != null) return JSON.stringify(d);
  }
  if (typeof body === "string" && body.trim()) return body.trim().slice(0, 300);
  if (status === 0) return "the server could not be reached";
  return `request failed (${status})`;
}

export interface RequestOptions {
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
  /** false for the login call: a 401 there is a wrong password, not an expired session. */
  auth?: boolean;
}

function authHeaders(): Record<string, string> {
  const t = config.getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function readBody(res: Response): Promise<unknown> {
  const ct = res.headers.get("content-type") || "";
  if (res.status === 204) return null;
  if (ct.includes("application/json")) {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }
  return await res.text();
}

export async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...authHeaders() };
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData) {
    body = opts.body;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}${buildQuery(opts.query)}`, {
      method,
      headers,
      body,
      signal: opts.signal,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "the server could not be reached");
  }
  const data = await readBody(res);
  if (!res.ok) {
    if (res.status === 401 && opts.auth !== false && config.onUnauthorized) config.onUnauthorized();
    throw new ApiError(res.status, formatDetail(data, res.status));
  }
  return data as T;
}

const get = <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>("GET", path, { query, signal });
const post = <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, { body: body ?? {}, query });
const patch = <T>(path: string, body?: unknown, query?: Query) => request<T>("PATCH", path, { body: body ?? {}, query });
const put = <T>(path: string, body?: unknown) => request<T>("PUT", path, { body: body ?? {} });
const del = <T>(path: string) => request<T>("DELETE", path);

// ---- downloads -----------------------------------------------------------------------------------

/** Filename from a Content-Disposition header. */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ""));
    } catch {
      /* fall through */
    }
  }
  const m = /filename="?([^";]+)"?/i.exec(header);
  return m ? m[1].trim() : fallback;
}

/**
 * Download an API resource with the Authorization header and save it locally. Unlike a plain link
 * this surfaces server errors (e.g. "export failed verification") instead of saving an error body.
 */
export async function downloadFile(path: string, fallbackName: string, query?: Query): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}${buildQuery(query)}`, {
      headers: authHeaders(),
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "the server could not be reached");
  }
  if (!res.ok) {
    const data = await readBody(res);
    if (res.status === 401 && config.onUnauthorized) config.onUnauthorized();
    throw new ApiError(res.status, formatDetail(data, res.status));
  }
  const blob = await res.blob();
  const name = filenameFromDisposition(res.headers.get("content-disposition"), fallbackName);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

// ---- URLs for <img>, <video>, <audio> (authenticated by the httpOnly cookie) -----------------------

export const urls = {
  pageImage: (fileId: number, page: number, dpi = 110) => `${API_BASE}/files/${fileId}/pages/${page}.png?dpi=${dpi}`,
  media: (fileId: number) => `${API_BASE}/files/${fileId}/media`,
  videoFrame: (fileId: number, frame: number, preview = true, effect = "blur") =>
    `${API_BASE}/files/${fileId}/video/frame/${frame}.jpg${buildQuery({ preview, effect })}`,
  exportPage: (exportId: number, page: number, dpi = 110) => `${API_BASE}/exports/${exportId}/pages/${page}.png?dpi=${dpi}`,
};

// ---- auth -------------------------------------------------------------------------------------------

export const login = (username: string, password: string) =>
  request<AuthResponse>("POST", "/auth/login", { body: { username, password }, auth: false });
export const authMode = () => request<AuthMode>("GET", "/auth/mode", { auth: false });
/** Sign-in-free access for a browser on the computer running Obscura (only when sign-in is turned off). */
export const localLogin = () => request<AuthResponse>("POST", "/auth/local", { auth: false });
export const logout = () => post<Ok>("/auth/logout");
export const me = () => get<User>("/auth/me");
export const changePassword = (current_password: string, new_password: string) =>
  post<AuthResponse>("/auth/change-password", { current_password, new_password });

// ---- users --------------------------------------------------------------------------------------------

export const listUsers = () => get<UserDirectoryEntry[]>("/users");
export const createUser = (body: UserIn) => post<User>("/users", body);
export const updateUser = (id: number, body: UserPatch) => patch<User>(`/users/${id}`, body);
export const resetUserPassword = (id: number, password: string) => post<Ok>(`/users/${id}/reset-password`, { password });

// ---- cases --------------------------------------------------------------------------------------------

export const listCases = () => get<CaseSummary[]>("/cases");
export const createCase = (body: CaseIn) => post<CaseSummary>("/cases", body);
export const getCase = (id: number, signal?: AbortSignal) => get<CaseDetail>(`/cases/${id}`, undefined, signal);
export const updateCase = (id: number, body: CasePatch) => patch<CaseSummary>(`/cases/${id}`, body);
export const deleteCase = (id: number) => del<Ok>(`/cases/${id}`);
export const addCaseMember = (caseId: number, user_id: number, role: MemberRole) =>
  post<Ok>(`/cases/${caseId}/members`, { user_id, role });
export const removeCaseMember = (caseId: number, userId: number) => del<Ok>(`/cases/${caseId}/members/${userId}`);
export const listNotes = (caseId: number) => get<Note[]>(`/cases/${caseId}/notes`);
export const addNote = (caseId: number, body: string, file_id: number | null = null) =>
  post<{ id: number }>(`/cases/${caseId}/notes`, { body, file_id });
export const bulkAnalyze = (caseId: number, file_ids: number[] | null, params: Partial<AnalyzeParams>) =>
  post<BulkJobs>(`/cases/${caseId}/bulk/analyze`, { file_ids, params });
export const bulkExport = (caseId: number, file_ids: number[] | null, params: ExportParams) =>
  post<BulkJobs>(`/cases/${caseId}/bulk/export`, { file_ids, params });
export const caseReport = (caseId: number) => get<CaseReport>(`/cases/${caseId}/report`);
/** Case-wide "redact additional text": preview or redact the terms in every (or the chosen) file. */
export const caseRedactText = (caseId: number, body: RedactTextIn) => post<RedactTextOut>(`/cases/${caseId}/redact-text`, body);
export const getCaseRedactText = (caseId: number) => get<RedactTextList>(`/cases/${caseId}/redact-text`);
/** Replace the remembered list (removing an entry does not undo redactions already added). */
export const putCaseRedactText = (caseId: number, terms: ExtraTerm[]) => put<RedactTextList>(`/cases/${caseId}/redact-text`, { terms });
export const mergePdfs = (caseId: number, file_ids: number[], name: string) =>
  post<FileRecord>(`/cases/${caseId}/tools/merge`, { file_ids, name });

/** Multipart upload (field name `files`) with upload progress (0..1). */
export function uploadFiles(
  caseId: number,
  files: File[],
  onProgress?: (fraction: number) => void,
): Promise<UploadResult> {
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/cases/${caseId}/files`);
    const t = config.getToken();
    if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.responseType = "text";
    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && e.total > 0) onProgress(e.loaded / e.total);
      };
    }
    xhr.onerror = () => reject(new ApiError(0, "upload failed: the server could not be reached"));
    xhr.onload = () => {
      let data: unknown = xhr.responseText;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data as UploadResult);
      } else {
        if (xhr.status === 401 && config.onUnauthorized) config.onUnauthorized();
        reject(new ApiError(xhr.status, formatDetail(data, xhr.status)));
      }
    };
    xhr.send(form);
  });
}

// ---- files --------------------------------------------------------------------------------------------

export const getFile = (id: number, signal?: AbortSignal) => get<FileRecord>(`/files/${id}`, undefined, signal);
export const updateFile = (id: number, body: { status?: string; assigned_to?: number | null }) =>
  patch<FileRecord>(`/files/${id}`, body);
export const deleteFile = (id: number) => del<Ok>(`/files/${id}`);
export const downloadOriginal = (id: number) => downloadFile(`/files/${id}/original`, "original");
export const getPages = (id: number, signal?: AbortSignal) => get<PagesResponse>(`/files/${id}/pages`, undefined, signal);
export const getPageText = (id: number, page: number, signal?: AbortSignal) =>
  get<PageText>(`/files/${id}/pages/${page}/text`, undefined, signal);
export const analyzeFile = (id: number, params: Partial<AnalyzeParams>) => post<JobRef>(`/files/${id}/analyze`, params);
export const getDetections = (id: number, signal?: AbortSignal) =>
  get<DetectionsResponse>(`/files/${id}/detections`, undefined, signal);
export const patchDetections = (id: number, body: DetectionBulk) => patch<DetectionSummary>(`/files/${id}/detections`, body);
export const addDetection = (id: number, body: ManualDetectionIn) => post<Detection>(`/files/${id}/detections`, body);
export const deleteDetection = (id: number, detId: string) => del<Ok>(`/files/${id}/detections/${encodeURIComponent(detId)}`);
/** Remove several detections in one request (ids in the body, never in the URL). */
export const deleteDetections = (id: number, ids: string[]) => post<{ removed: number }>(`/files/${id}/detections/delete`, { ids });
/** Put detections back exactly as returned by GET (same id, score, detector, reason, meta) — undo. */
export const restoreDetections = (id: number, detections: Detection[]) =>
  post<{ restored: number; ids: string[] }>(`/files/${id}/detections/restore`, { detections });
export const searchFile = (id: number, body: SearchIn) => post<SearchResult>(`/files/${id}/search`, body);
export const getTracks = (id: number, signal?: AbortSignal) => get<TracksResponse>(`/files/${id}/video/tracks`, undefined, signal);
export const addTrack = (id: number, body: ManualTrackIn) => post<Track>(`/files/${id}/video/tracks`, body);
export const patchTrack = (id: number, trackId: number, body: TrackPatch) =>
  patch<Ok>(`/files/${id}/video/tracks/${trackId}`, body);
/** Put a deleted / trimmed track back exactly (full track as returned by GET tracks) — undo. */
export const restoreTrack = (id: number, track: Track) => post<Track>(`/files/${id}/video/tracks/restore`, { track });
export const getTranscript = (id: number, signal?: AbortSignal) => get<Transcript>(`/files/${id}/transcript`, undefined, signal);
/** Captions of the transcript, or of a translation when `lang` is given. Redacted unless `redacted: false`. */
export const downloadCaptions = (id: number, fmt: "srt" | "vtt" = "srt", opts: { lang?: string | null; redacted?: boolean } = {}) =>
  downloadFile(
    `/files/${id}/captions.${fmt}`,
    opts.lang ? `captions_${opts.lang}.${fmt}` : `captions.${fmt}`,
    { redacted: opts.redacted ?? true, lang: opts.lang || undefined },
  );
/** Translate the transcript (local model) → job. With `redacted` the redacted words never reach the translation. */
export const translateTranscript = (id: number, target: string, redacted = true) =>
  post<JobRef>(`/files/${id}/translate`, { target, redacted });
export const listTranslations = (id: number, signal?: AbortSignal) => get<TranslationRef[]>(`/files/${id}/translations`, undefined, signal);
export const getTranslation = (id: number, lang: string, redacted = true, signal?: AbortSignal) =>
  get<Translation>(`/files/${id}/translations/${encodeURIComponent(lang)}`, { redacted }, signal);
/** AI confidence report: every finding with type, confidence, detector, decision and reason (never the value). */
export const downloadConfidenceReport = (id: number) => downloadFile(`/files/${id}/confidence.csv`, `confidence_report_${id}.csv`);
export const exportFile = (id: number, params: ExportParams) => post<JobRef>(`/files/${id}/export`, params);
export const splitPdf = (id: number, ranges: number[][]) => post<FileRecord[]>(`/files/${id}/tools/split`, { ranges });
export const organizePdf = (id: number, body: { order?: number[]; rotate?: Record<number, number>; delete?: number[] }) =>
  post<FileRecord>(`/files/${id}/tools/organize`, body);

// ---- exports ------------------------------------------------------------------------------------------

export const getExport = (id: number, signal?: AbortSignal) => get<ExportDetail>(`/exports/${id}`, undefined, signal);
export const listCaseExports = (caseId: number) => get<CaseExport[]>(`/cases/${caseId}/exports`);
export const downloadExport = (id: number, name = "export") => downloadFile(`/exports/${id}/download`, name);
export const downloadExportLog = (id: number) => downloadFile(`/exports/${id}/log.csv`, "redaction_log.csv");

// ---- jobs ---------------------------------------------------------------------------------------------

export const getJob = (id: number, signal?: AbortSignal) => get<Job>(`/jobs/${id}`, undefined, signal);
export const listJobs = (active = true, caseId?: number) => get<Job[]>("/jobs", { active, case_id: caseId });
export const cancelJob = (id: number) => post<Ok>(`/jobs/${id}/cancel`);

export const FINISHED_JOB_STATES = new Set(["done", "error", "cancelled"]);

/** Poll a job (~1 s) until it finishes. Resolves with the final job; never rejects on job errors. */
export async function waitForJob(
  id: number,
  opts: { onUpdate?: (job: Job) => void; intervalMs?: number; signal?: AbortSignal } = {},
): Promise<Job> {
  const interval = opts.intervalMs ?? 1000;
  for (;;) {
    if (opts.signal?.aborted) throw new DOMException("aborted", "AbortError");
    const j = await getJob(id, opts.signal);
    opts.onUpdate?.(j);
    if (FINISHED_JOB_STATES.has(j.status)) return j;
    await new Promise<void>((resolve, reject) => {
      const t = setTimeout(resolve, interval);
      opts.signal?.addEventListener(
        "abort",
        () => {
          clearTimeout(t);
          reject(new DOMException("aborted", "AbortError"));
        },
        { once: true },
      );
    });
  }
}

// ---- library ------------------------------------------------------------------------------------------

export const getMeta = () => get<Meta>("/meta");
export const listTermLists = (caseId?: number) => get<TermList[]>("/lists", { case_id: caseId });
export const getTermList = (id: number) => get<TermList>(`/lists/${id}`);
export const createTermList = (body: TermListIn) => post<TermList>("/lists", body);
export const updateTermList = (id: number, body: TermListIn) => put<TermList>(`/lists/${id}`, body);
export const deleteTermList = (id: number) => del<Ok>(`/lists/${id}`);
export const listTemplates = () => get<Template[]>("/templates");
export const createTemplate = (body: TemplateIn) => post<Template>("/templates", body);
export const updateTemplate = (id: number, body: TemplateIn) => put<Template>(`/templates/${id}`, body);
export const deleteTemplate = (id: number) => del<Ok>(`/templates/${id}`);
export const listPresets = () => get<Preset[]>("/presets");
export const createPreset = (name: string, settings: Partial<AnalyzeParams>) => post<Preset>("/presets", { name, settings });
export const deletePreset = (id: number) => del<Ok>(`/presets/${id}`);
export const saveExemptionCode = (code: string, description: string) =>
  post<{ code: string; description: string }>("/exemption-codes", { code, description });

// ---- audit / admin ------------------------------------------------------------------------------------

export const listAudit = (q: AuditQuery = {}) => get<AuditEvent[]>("/audit", { ...q });
export const verifyAudit = () => get<AuditVerify>("/audit/verify");
export const downloadAuditCsv = (caseId?: number) => downloadFile("/audit/export.csv", "audit_log.csv", { case_id: caseId });
export const listWatchers = () => get<Watcher[]>("/watchers");
export const createWatcher = (body: WatcherIn) => post<{ id: number }>("/watchers", body);
export const setWatcherEnabled = (id: number, enabled: boolean) => patch<Ok>(`/watchers/${id}`, undefined, { enabled });
export const deleteWatcher = (id: number) => del<Ok>(`/watchers/${id}`);
export const getSystem = () => get<SystemInfo>("/system");

// ---- first-run setup, installation, uninstall (answer only the computer running Obscura) ---------------------

export const getSetupState = () => request<SetupState>("GET", "/setup/state", { auth: false });
export const completeSetup = (body: SetupCompleteIn) => request<SetupCompleteOut>("POST", "/setup/complete", { body, auth: false });
/** Opens the operating system's folder chooser on this computer; null when cancelled. */
export const pickFolder = (purpose: "data" | "models") =>
  request<{ path: string | null }>("POST", "/setup/pick-folder", { body: {}, query: { purpose }, auth: false });
export const getSetupModels = () => request<SetupModelsState>("GET", "/setup/models", { auth: false });
export const importModels = (path: string) => request<ModelsImportOut>("POST", "/setup/models/import", { body: { path }, auth: false });
/** One-time download of model files from their publishers; nothing about documents or settings is sent. */
export const downloadModels = () => request<SetupModelsState["download"]>("POST", "/setup/models/download", { body: {}, auth: false });
export const getAppInfo = () => get<AppInfo>("/system/app");
export const updateApp = (body: AppSettingsIn) => patch<{ ok: boolean; restart: boolean }>("/system/app", body);
export const restartApp = () => post<Ok>("/system/restart");
export const uninstallApp = (remove_data: boolean) =>
  post<{ ok: boolean; remove_data: boolean }>("/system/uninstall", { confirm: "UNINSTALL", remove_data });
/** `boot` changes on every server start (lets the UI tell a restarted server from the old one). */
export const health = () => request<{ ok: boolean; version: string; boot?: string }>("GET", "/health", { auth: false });
