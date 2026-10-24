// Data shapes returned by the Obscura API (see backend/obscura/api/*.py and redact/model.py).

export type Role = "admin" | "supervisor" | "redactor" | "viewer";
export type MemberRole = "redactor" | "reviewer" | "viewer";

export interface User {
  id: number;
  username: string;
  full_name: string;
  email: string;
  role: Role;
  is_active: boolean;
  must_change_password: boolean;
  locked: boolean;
  created_at: string;
  last_login: string | null;
  /** The built-in account used when sign-in is turned off (no password, no sign-out). */
  local?: boolean;
}

/** GET /api/auth/mode: whether this browser may open the app without signing in. */
export interface AuthMode {
  require_login: boolean;
  local_access: boolean;
}

/** Directory entry returned to non-admins by GET /api/users. */
export interface UserDirectoryEntry {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  email?: string;
  is_active?: boolean;
  locked?: boolean;
  must_change_password?: boolean;
  created_at?: string;
  last_login?: string | null;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export type CaseStatus = "open" | "in_review" | "completed" | "closed";

export interface CaseSummary {
  id: number;
  name: string;
  number: string;
  description: string;
  status: CaseStatus | string;
  request_type: string;
  due_date: string | null;
  default_profile: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  file_count?: number;
  status_counts?: Record<string, number>;
  exported?: number;
  member_count?: number;
}

export interface CaseMember {
  user_id: number;
  role: MemberRole | string;
  username: string;
  full_name: string;
}

export interface CaseDetail extends CaseSummary {
  members: CaseMember[];
  files: FileRecord[];
}

export interface CaseIn {
  name: string;
  number?: string;
  description?: string;
  request_type?: string;
  due_date?: string | null;
  default_profile?: string;
  members?: { user_id: number; role: MemberRole }[];
}

export type CasePatch = Partial<Omit<CaseIn, "members">> & { status?: string };

export type FileKind = "pdf" | "image" | "video" | "audio" | "docx" | "pptx" | "xlsx" | "email" | "text" | "tiff";
export type FileStatus = "uploaded" | "analyzing" | "ready" | "in_review" | "approved" | "exported" | "error";

export interface ExportSummary {
  id: number;
  name: string;
  verified: boolean;
  created_at: string;
  sha256: string;
  size: number;
  /** marked review copy: outlines + labels, nothing removed — never a release */
  marked_copy?: boolean;
  /** final check: possible personal items still readable (null = not checked) */
  second_opinion_open?: number | null;
  settings?: Record<string, unknown> | null;
}

export interface VideoInfo {
  fps?: number;
  frames?: number;
  width?: number;
  height?: number;
  duration?: number;
  has_audio?: boolean;
  rotation?: number;
}

export interface FileInfo extends VideoInfo {
  attachments?: number;
  converted_from?: string;
  exif?: boolean;
  metadata?: Record<string, boolean>;
  has_forms?: boolean;
  last_analysis?: Partial<AnalyzeParams>;
  /** translation keys: "<lang>:r" (redacted) / "<lang>:o" (original) */
  translations?: string[] | Record<string, string>;
  [key: string]: unknown;
}

export interface FileRecord {
  id: number;
  case_id: number;
  parent_id: number | null;
  name: string;
  kind: FileKind | string;
  ext: string;
  mime: string;
  size: number;
  sha256: string;
  page_count: number;
  duration: number;
  info: FileInfo;
  status: FileStatus | string;
  assigned_to: number | null;
  uploaded_by: number | null;
  uploaded_at: string;
  analyzed_at: string | null;
  approved_by: number | null;
  error: string;
  has_detections: boolean;
  has_tracks: boolean;
  has_transcript: boolean;
  exports: ExportSummary[];
}

export interface UploadResult {
  files: FileRecord[];
  errors: { name: string; error: string }[];
}

export interface Box {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export type DetectionKind = "text" | "visual" | "manual" | "template" | "audio" | "region";
export type ShapeKind = "rect" | "ellipse" | "polygon";
export type ImageEffect = "blur" | "pixelate" | "blackout" | "whiteout";

export interface DetectionMeta {
  t0?: number;
  t1?: number;
  words?: string[];
  /** manual shapes (absent = rectangle) */
  shape?: ShapeKind;
  /** polygon vertices, unrotated page units */
  points?: number[][];
  /** images / video: per-redaction effect */
  effect?: ImageEffect | string;
  /** text printed on this box in the export */
  label_text?: string;
  /** box colour, RGB 0..1 */
  fill?: number[];
  note?: string;
  /** picture classification */
  class?: string;
  whole_picture?: boolean;
  /** office pictures: media part name, boxes inside the picture, picture size */
  media?: string;
  image_boxes?: Box[];
  image_size?: number[];
  [key: string]: unknown;
}

export interface Detection {
  id: string;
  entity: string;
  text: string;
  score: number;
  source: string;
  boxes: Box[];
  page: number;
  start: number;
  end: number;
  explanation: string;
  selected: boolean;
  exemption: string;
  partial: string | null;
  kind: DetectionKind | string;
  meta: DetectionMeta;
}

export interface DetectionSummary {
  detections: number;
  selected: number;
  by_entity: Record<string, number>;
}

export interface DetectionsResponse {
  detections: Detection[];
  summary: DetectionSummary;
}

/** One change in PATCH /api/files/{id}/detections. Omitted = unchanged; "" / [] clears a meta field. */
export interface DetectionUpdate {
  id: string;
  selected?: boolean;
  entity?: string;
  exemption?: string;
  boxes?: Box[];
  partial?: string | null;
  label_text?: string;
  fill?: number[];
  effect?: string;
  note?: string;
  /** "rect" clears the shape */
  shape?: ShapeKind;
  /** polygon vertices; the server moves the locating box with them */
  points?: number[][];
  image_boxes?: Box[];
}

export interface DetectionBulk {
  updates?: DetectionUpdate[];
  select_entities?: Record<string, boolean>;
}

export interface ManualDetectionIn {
  entity?: string;
  /** omitted / null = the type's default reason; "" = none */
  exemption?: string | null;
  /** default true */
  selected?: boolean;
  partial?: string | null;
  /** a picture inside a Word / PowerPoint file (with image_boxes) */
  media?: string;
  image_boxes?: Box[];
  boxes?: Omit<Box, "page">[] | Box[];
  page?: number;
  start?: number;
  end?: number;
  t0?: number;
  t1?: number;
  note?: string;
  shape?: ShapeKind;
  /** polygon vertices (page coordinates); polygon only */
  points?: number[][];
  effect?: ImageEffect;
  label_text?: string;
  fill?: [number, number, number];
}

export interface SearchTermIn {
  text: string;
  regex?: boolean;
  case_sensitive?: boolean;
  whole_word?: boolean;
  entity?: string;
  exemption?: string;
}

export interface SearchIn {
  terms: SearchTermIn[];
  add?: boolean;
  entity?: string;
  exemption?: string;
}

export interface SearchResult {
  matches: Detection[];
  count: number;
  /** with add: true — ids of the detections that were added (new_ids ∪ switched_ids) */
  added_ids?: string[];
  /** detections created by this search */
  new_ids?: string[];
  /** existing suggestions switched to redacted by this search */
  switched_ids?: string[];
}

export interface PageInfo {
  page: number;
  width: number;
  height: number;
  rotation?: number;
  source?: string;
  ocr_conf?: number | null;
  /** PyMuPDF rotation matrix [a, b, c, d, e, f] mapping unrotated → displayed page coordinates. */
  matrix?: number[];
}

export interface ExtractStats {
  native_pages?: number;
  ocr_pages?: number;
  hybrid_pages?: number;
  ocr_conf?: number[];
}

export interface PagesResponse {
  pages?: PageInfo[];
  stats?: ExtractStats;
  text?: string;
}

/** Character box in page units, or null for a synthetic separator (space / newline). */
export type CharBox = [number, number, number, number] | null;

export interface PageText {
  text: string;
  boxes?: CharBox[];
  width?: number;
  height?: number;
  source?: string;
}

export interface AnalyzeParams {
  profile: string | null;
  entities: string[] | null;
  use_ml: boolean;
  ocr: "auto" | "always" | "never";
  visual_classes: string[] | null;
  video_mode: string;
  audio: boolean;
  terms: SearchTermIn[];
  allow_list: string[];
  list_ids: number[];
  template_ids: number[];
  threshold: number;
  sensitive_sentence_mode: boolean;
  use_case_dictionary: boolean;
  image_text: boolean;
  whisper_model?: string | null;
  /** speech language: "auto" or an ISO code */
  language: string;
  /** classify photos / exhibits / charts / ID cards / signatures in documents */
  classify_images: boolean;
  /** look for faces / plates in pictures inside PDFs */
  visual_on_pages: boolean;
  /** label who is speaking in transcripts (anonymous "Speaker 1", "Speaker 2", …) */
  speakers: boolean;
  /** Microsoft Presidio re-reads the text; extra findings become (unselected) suggestions */
  second_opinion: boolean;
}

export interface JobRef {
  job_id: number;
}

export interface BulkJobs {
  jobs: number[];
}

export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";

export interface Job {
  id: number;
  kind: string;
  file_id: number | null;
  case_id: number | null;
  status: JobStatus | string;
  progress: number;
  message: string;
  result?: Record<string, unknown> & {
    export_id?: number;
    verified?: boolean;
    sha256?: string;
    issues?: VerificationIssue[];
    detections?: number;
    selected?: number;
    /** export: possible personal items the final check still found (null = not checked) */
    second_opinion_open?: number | null;
  };
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface VerificationIssue {
  type: string;
  page?: number;
  entity?: string;
  found?: string;
  frame?: number;
  time?: number;
  score?: number;
  [key: string]: unknown;
}

export interface Verification {
  passed: boolean;
  issues: VerificationIssue[];
  pages?: number;
  checks?: string[];
  frames_checked?: number;
  leak_frames?: number;
  [key: string]: unknown;
}

export interface ExportDetail {
  id: number;
  second_opinion_open?: number | null;
  file_id: number;
  name: string;
  sha256: string;
  size: number;
  settings: Record<string, unknown>;
  report: {
    verification?: Verification;
    pages?: number;
    redactions?: number;
    second_opinion?: SecondOpinionReport;
    [key: string]: unknown;
  };
  verified: boolean;
  created_at: string;
}

/** GET /api/cases/{id}/exports */
export interface CaseExport {
  id: number;
  file_id: number;
  file_name: string;
  name: string;
  verified: boolean;
  marked_copy?: boolean;
  second_opinion_open?: number | null;
  sha256: string;
  size: number;
  created_at: string;
}

export interface RedactionStyleIn {
  label?: "none" | "entity" | "exemption" | "custom";
  custom_text?: string;
  fill?: [number, number, number];
  text_color?: [number, number, number];
}

export interface EnhanceParams {
  brightness: number;
  contrast: number;
  sharpen: number;
  gamma: number;
  denoise: boolean;
}

export interface ExportParams {
  style?: RedactionStyleIn;
  text_style?: "block" | "entity" | "exemption";
  effect?: string;
  face_effect?: string | null;
  audio_effect?: string;
  voice_disguise?: boolean;
  mute_audio?: boolean;
  bates_prefix?: string | null;
  bates_start?: number;
  bates_digits?: number;
  watermark?: string | null;
  password?: string | null;
  flatten?: boolean;
  /** extra margin around every redaction (PDF points / image pixels) */
  padding?: number;
  /** PDF / image review copy: outlines + labels, nothing removed (internal QC only) */
  marked_copy?: boolean;
  enhance?: EnhanceParams | null;
  /** video: draw the redacted transcript as captions */
  burn_captions?: boolean;
  /** final check of the released file with Microsoft Presidio */
  second_opinion?: boolean;
}

/** Track as stored in tracks_blob (Track.to_dict()). boxes: frame → [x0, y0, x1, y1] in video pixels. */
export interface Track {
  id: number;
  label: string;
  enabled: boolean;
  source: string;
  first: number;
  last: number;
  max_score: number;
  observations?: number;
  boxes?: Record<string, number[]>;
  /** per-track override (blur / pixelate / blackout); null = export setting */
  effect?: string | null;
  /** rect / ellipse; null = rect */
  shape?: string | null;
}

export interface TracksResponse {
  tracks: Track[];
  info: FileInfo;
}

export type TrackMode = "track" | "static" | "keyframes" | "full_frame";

export interface ManualTrackIn {
  frame: number;
  box: number[];
  label?: string;
  mode?: TrackMode;
  end_frame?: number | null;
  keyframes?: Record<string, number[]> | null;
  effect?: string | null;
  shape?: "rect" | "ellipse" | null;
}

export interface TrackPatch {
  enabled?: boolean;
  label?: string;
  delete?: boolean;
  trim_start?: number | null;
  trim_end?: number | null;
  /** "" clears the per-track override */
  effect?: string;
  /** "" / "rect" = rectangle */
  shape?: string;
}

export interface TranscriptWord {
  text: string;
  start: number;
  end: number;
  prob: number;
  char_start: number;
  char_end: number;
  /** anonymous label ("Speaker 1") when speakers were identified */
  speaker?: string | null;
}

export interface Transcript {
  text: string;
  language: string;
  duration: number;
  model: string;
  segments: { start?: number; end?: number; text?: string; speaker?: string | null; [key: string]: unknown }[];
  words: TranscriptWord[];
}

export interface TranslationSegment {
  start: number;
  end: number;
  text: string;
  speaker?: string | null;
}

export interface TranslationRef {
  lang: string;
  redacted: boolean;
}

export interface Translation {
  source?: string;
  target?: string;
  redacted?: boolean;
  segments: TranslationSegment[];
}

export interface Note {
  id: number;
  file_id: number | null;
  body: string;
  user: string;
  created_at: string;
}

export interface CaseReportRow {
  file_id: number;
  name: string;
  kind: string;
  status: string;
  pages: number;
  redactions: number;
  exports: number;
  /** marked review copies (not counted in exports / verified) */
  review_copies?: number;
  verified: boolean | null;
}

export interface CaseReport {
  case: CaseSummary;
  files: CaseReportRow[];
  by_entity: Record<string, number>;
  by_exemption: Record<string, number>;
  total_redactions: number;
}

export interface AuditEvent {
  id: number;
  ts: string;
  user: string;
  action: string;
  object_type: string;
  object_id: string;
  case_id: number | null;
  details: Record<string, unknown>;
  ip: string;
  hash: string;
}

export interface AuditQuery {
  case_id?: number;
  file_id?: number;
  user_id?: number;
  action?: string;
  limit?: number;
  offset?: number;
}

export interface AuditVerify {
  valid: boolean;
  events: number;
  head?: string;
  broken_at?: number;
  reason?: string;
}

export interface EntityMeta {
  key: string;
  label: string;
  category: string;
  description: string;
  default_on: boolean;
  exemption: string;
  hipaa: boolean;
}

export interface ProfileMeta {
  key: string;
  label: string;
  entities: string[];
  partial: Record<string, string>;
}

export interface Meta {
  version: string;
  entities: EntityMeta[];
  categories: Record<string, string>;
  profiles: ProfileMeta[];
  exemption_codes: Record<string, string>;
  visual_classes: Record<string, string>;
  effects: string[];
  audio_effects: string[];
  models: Record<string, unknown> | string[];
  video_modes: string[];
  languages?: {
    /** "auto" when the multilingual speech model is installed, else "en" */
    transcription: string;
    translation_available: boolean;
    codes: Record<string, string>;
  };
  image_classes?: { classes: Record<string, string>; selected_by_default: string[] };
  shapes?: string[];
  track_modes?: string[];
  second_opinion?: SecondOpinionMeta;
}

export interface TermEntry {
  text: string;
  regex?: boolean;
  case_sensitive?: boolean;
  whole_word?: boolean;
  entity?: string | null;
}

export interface TermList {
  id: number;
  name: string;
  kind: "redact" | "allow" | string;
  entity: string;
  exemption: string;
  case_id: number | null;
  created_at: string;
  count: number;
  terms?: TermEntry[];
}

export interface TermListIn {
  name: string;
  kind: "redact" | "allow";
  terms: (TermEntry | string)[];
  entity?: string;
  exemption?: string;
  case_id?: number | null;
}

export interface TemplateZone {
  pages: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  entity: string;
  exemption: string;
  label: string;
}

export interface Template {
  id: number;
  name: string;
  description: string;
  zones: TemplateZone[];
}

export interface TemplateIn {
  name: string;
  description?: string;
  zones: TemplateZone[];
}

export interface Preset {
  id: number;
  name: string;
  settings: Partial<AnalyzeParams>;
}

export interface Watcher {
  id: number;
  name: string;
  input_dir: string;
  output_dir: string;
  case_id: number;
  preset_id: number | null;
  export_settings: ExportParams;
  enabled: boolean;
}

export interface WatcherIn {
  name: string;
  input_dir: string;
  output_dir: string;
  case_id: number;
  preset_id?: number | null;
  export_settings?: ExportParams;
  enabled?: boolean;
}

// ---- second opinion (Microsoft Presidio, local) ------------------------------------------------------

export interface SecondOpinionMeta {
  available: boolean;
  engine: string;
  version?: string | null;
  reason?: string | null;
}

export interface SecondOpinionFinding {
  page: number;
  entity: string;
  /** the text still readable in the export — sent to reviewers only (viewers do not receive it); never shown in notifications */
  text?: string;
  score: number;
  recognizer: string;
  /** the reviewer deliberately left this text unredacted */
  reviewed: boolean;
}

export type SecondOpinionReport =
  | { checked: true; engine: string; count: number; open: number; findings: SecondOpinionFinding[] }
  | { checked: false; reason?: string };

// ---- first-run setup & installation -------------------------------------------------------------------

export type AppMode = "single" | "office";

export interface SetupModel {
  key: string;
  label: string;
  size_gb: number;
  needed_for: string;
  required: boolean;
  present: boolean;
}

export type SetupState =
  | { needed: false }
  | {
      needed: true;
      version: string;
      platform: string;
      defaults: { mode: AppMode; data_dir: string; port: number; autostart: boolean };
      disk_free_gb: number | null;
      models_dir: string;
      models: SetupModel[];
      spacy_model: boolean;
      ocr: boolean;
      second_opinion: boolean;
      lan_address: string | null;
      can_pick_folder: boolean;
      autostart_available: boolean;
    };

export type SetupNeeded = Extract<SetupState, { needed: true }>;

export interface SetupCompleteIn {
  mode: AppMode;
  require_login: boolean;
  admin_username: string | null;
  admin_password: string | null;
  admin_full_name: string;
  data_dir: string;
  autostart: boolean;
  port?: number;
}

export interface SetupCompleteOut {
  ok: boolean;
  restart: boolean;
  require_login: boolean;
  autostart: boolean;
  url: string;
  lan_url: string | null;
}

export type DownloadState = "idle" | "running" | "done" | "error";

export interface SetupModelsState {
  models_dir: string;
  models: SetupModel[];
  download: { state: DownloadState; restart_needed?: boolean; [key: string]: unknown };
}

export interface ModelsImportOut {
  ok: boolean;
  imported: string[];
  models_dir: string;
  restart_needed: boolean;
}

export interface AppInfo {
  installed: boolean;
  version: string;
  platform: string;
  install_dir: string;
  config_path: string;
  data_dir: string;
  models_dir: string;
  mode: AppMode;
  require_login: boolean;
  host: string;
  port: number;
  autostart: boolean;
  autostart_available: boolean;
  uninstall_available: boolean;
  local_request: boolean;
  lan_address: string | null;
}

export interface AppSettingsIn {
  require_login?: boolean;
  autostart?: boolean;
  mode?: AppMode;
  port?: number;
}

// ---- case-wide "redact additional text" -----------------------------------------------------------------

export interface ExtraTerm {
  text: string;
  regex?: boolean;
  case_sensitive?: boolean;
  whole_word?: boolean;
  entity?: string | null;
}

export interface RedactTextIn {
  terms: ExtraTerm[];
  preview: boolean;
  remember: boolean;
  entity: string;
  exemption: string;
  file_ids: number[] | null;
}

export interface RedactTextFile {
  file_id: number;
  name: string;
  matches: number;
  added: number;
  added_ids: string[];
  /** detections created (undo: delete them) */
  new_ids?: string[];
  /** existing suggestions switched to redacted (undo: un-select them) */
  switched_ids?: string[];
  skipped?: string;
  needs_reexport?: boolean;
}

export interface RedactTextOut {
  files: RedactTextFile[];
  total_matches: number;
  total_added: number;
  remembered: boolean;
  list_id: number | null;
  preview: boolean;
}

export interface RedactTextList {
  list_id: number | null;
  terms: ExtraTerm[];
}

export interface SystemInfo {
  host: string;
  port: number;
  platform: string;
  python: string;
  encrypt_at_rest: boolean;
  offline: boolean;
  ocr_available: boolean;
  models_on_disk: Record<string, string[]>;
  models_loaded: Record<string, unknown> | string[];
  spacy_model: string;
  gliner_model: string;
  whisper_model: string;
  data_dir: string;
  disk_free_gb: number;
  users: number;
  cases: number;
  files: number;
}

export interface UserIn {
  username: string;
  full_name?: string;
  email?: string;
  role: Role;
  password: string;
}

export interface UserPatch {
  full_name?: string;
  email?: string;
  role?: Role;
  is_active?: boolean;
  unlock?: boolean;
}

export interface Ok {
  ok: boolean;
}
