export type Status = "Pass" | "Fail" | "Perlu Review" | "Blocked" | "Skipped";
export type Severity = "Critical" | "Major" | "Minor";
export type RunStatus = "queued" | "running" | "paused" | "completed" | "interrupted";
export type ControlState = "running" | "paused" | "takeover" | "stopped";

export interface Profile {
  id: number;
  name: string;
  provider: "openai_compatible" | "anthropic";
  base_url: string;
  model: string;
  vision: boolean;
  timeout_seconds: number;
  is_default: boolean;
  api_key_masked: string;
  has_api_key: boolean;
}

export interface ProfileInput {
  name: string;
  provider: Profile["provider"];
  base_url: string;
  model: string;
  api_key?: string;
  vision: boolean;
  timeout_seconds: number;
  is_default: boolean;
}

export interface App {
  id: number;
  name: string;
  platform: "web" | "android";
  url: string;
  allowed_domains: string[];
  login_endpoints: string[];
  default_profile_id: number | null;
  explored: boolean;
  last_run_at: string | null;
  accounts: number;
}

export type SkillStage = "plan" | "execute" | "judge" | "report";

export interface Skill {
  id: number;
  name: string;
  filename: string;
  pages: number;
  chars: number;
  stages: SkillStage[];
  stage_labels: string[];
  app_ids: number[];
  app_names: string[];
  active: boolean;
}

export interface SkillsResponse {
  builtin: { name: string; description: string; topics: string[]; content: string };
  skills: Skill[];
  stages: Record<SkillStage, string>;
  capacity_percent: number;
}

export interface ReportSettings {
  company_name: string;
  excel_template: {
    name: string;
    columns: { header: string; maps_to: string | null }[];
    /** template tata letak bebas (format kantor) */
    sheet?: string;
    sheets?: { name: string; header_row: number; score: number; filled: boolean }[];
    sheet_chosen?: boolean;
    header_row?: number;
    capacity?: number | null;
    status_options?: string[];
    status_map?: Record<string, string>;
    fields?: { label: string; key: string; auto: boolean; value: string }[];
  } | null;
  /** logo perusahaan di kepala laporan PDF */
  logo?: { name: string; url: string } | null;
}

export interface Device {
  serial: string;
  state: "device" | "unauthorized" | "offline" | string;
  model: string;
  emulator: boolean;
  android_version: string | null;
}

export interface ApkUpload {
  file: string;
  package: string;
  version: string | null;
  version_code: number | null;
  size_bytes: number;
  installed_version: string | null;
}

export interface ApkChoice {
  file: string;
  grant: boolean;
  uninstall: boolean;
}

export interface InstallResult {
  package: string | null;
  packages: string[];
  message: string;
  file: string;
}

export interface AppInput {
  name: string;
  platform?: "web" | "android";
  url: string;
  allowed_domains: string[];
  login_endpoints: string[];
}

export interface Account {
  id: number;
  app_id: number;
  role: string;
  username: string;
  has_password: boolean;
}

export interface Run {
  id: number;
  app_id: number;
  app_name: string;
  platform: "web" | "android";
  url: string;
  mode: "explore" | "deep";
  module: string | null;
  environment: "dev" | "production";
  profile_id: number | null;
  profile_name: string;
  account_id: number | null;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  folder: string;
  counts: Partial<Record<Status, number>>;
  note: string;
  model: string;
  confirm_each_step: boolean;
  device_serial?: string | null;
  /** username yang memulai run (mode server) */
  created_by?: string | null;
  review_first?: boolean;
  reuse_cases_from?: number | null;
  /** test case sudah disusun, menunggu QA review sebelum dijalankan */
  awaiting_review?: boolean;
  active: boolean;
  control_state: ControlState | null;
}

export interface RunInput {
  app_id: number;
  mode: "explore" | "deep";
  module?: string | null;
  prd_text?: string | null;
  profile_id?: number | null;
  account_id?: number | null;
  environment: "dev" | "production";
  confirm_each_step: boolean;
  device_serial?: string | null;
  review_first?: boolean;
  reuse_cases_from?: number | null;
  ask_before_finish?: boolean;
  /** regresi: putar ulang skrip rekaman tanpa AI; heal = AI memperbaiki bila skrip gagal */
  replay_scripts?: boolean;
  heal?: boolean;
  apk_file?: string | null;
  apk_grant?: boolean;
  apk_uninstall?: boolean;
}

export type ControlCommand =
  | "pause"
  | "resume"
  | "takeover"
  | "release"
  | "hint"
  | "think_again"
  | "skip"
  | "stop"
  | "end_case"
  | "confirm_step"
  | "input"
  | "finish_explore";

export interface ControlInput {
  command: ControlCommand;
  text?: string;
  status?: "pass" | "fail";
  note?: string;
  event?: ManualEvent;
}

export type ManualEvent =
  | { kind: "click"; x: number; y: number }
  | { kind: "type"; text: string }
  | { kind: "key"; key: string }
  | { kind: "scroll"; dy: number };

export interface TestCase {
  id: string;
  module: string;
  page: string;
  title: string;
  type: string;
  priority: string;
  precondition: string;
  test_data: string;
  steps: string[];
  expected: string;
  expected_source: string;
  start_url: string;
  status_ai: Status | null;
  actual: string;
  ai_note: string;
  severity: Severity | null;
  status_final: Status | null;
  reviewer_note: string;
  effective_status: Status | null;
}

export interface CaseStep {
  step_no: number;
  action: string;
  actor: "ai" | "manual" | "script";
  text: string;
  result: string;
  guard: string;
  thought: string;
  location: string;
  screenshot_url: string | null;
}

export interface CaseDetailResponse extends TestCase {
  /** Langkah yang benar-benar dijalankan (evidence). `steps` = langkah rencana. */
  log: CaseStep[];
  technical: string[];
}

export interface ReviewInput {
  status_final?: Status | null;
  severity?: Severity | null;
  reviewer_note?: string;
}

export interface Stats {
  total_runs: number;
  web_runs: number;
  android_runs: number;
  cases_executed: number;
  findings: number;
  fail: number;
  review: number;
  pass_rate: number | null;
  pass_rate_prev: number | null;
  total_runs_prev: number;
  findings_prev: number;
  running: number;
  days: number;
}

export interface Finding {
  run_id: number;
  tc_id: string;
  title: string;
  module: string;
  status: Status;
  severity: Severity | null;
  app_name: string;
  platform: string;
  started_at: string;
}

export interface StepEvent {
  type: "step.done";
  tc_id: string;
  step_no: number;
  result: string;
  screenshot: string | null;
  description: string;
  actor: "ai" | "manual" | "script";
  seq?: number;
}

export interface PlannedEvent {
  type: "step.planned";
  tc_id: string;
  step_no: number;
  action: string;
  element: { role: string; name: string; bbox: [number, number, number, number] } | null;
  thought: string;
  risk: string;
  description: string;
  viewport: { width: number; height: number } | null;
}

export interface Snapshot {
  type: "snapshot";
  run_id: number;
  seq: number;
  status: RunStatus;
  control_state: ControlState | null;
  awaiting_confirm: boolean;
  confirm_each_step: boolean;
  note: string;
  counts: Partial<Record<Status, number>>;
  current_tc: string | null;
  planned: PlannedEvent | null;
  steps: StepEvent[];
  cases: { tc_id: string; title: string; status: Status | null }[];
  screens: number;
  /** Seluruh aplikasi: agent bertanya lanjutkan memetakan atau selesai */
  asking?: { screens: number; modules: number; new_screens?: number } | null;
}

export type RunEvent = { type: string; seq?: number; [key: string]: unknown };

export interface Frame {
  url: string;
  width: number;
  height: number;
}


// ---------- login & peran (mode server) ----------
export type Role = "admin" | "qa" | "viewer";
export type AuthUser = { id: number; username: string; role: Role };
export type AuthStatus = { auth_required: boolean; user: AuthUser | null };
export type UserRow = AuthUser & { active: boolean; created_at: string; last_login: string | null };

// ---------- review test case sebelum dijalankan ----------
export const REVIEW_NOTE = "Menunggu review test case";
export type PlanCase = {
  id?: string;
  title: string;
  page: string;
  type: "positif" | "negatif" | "validasi" | "boundary" | "navigasi";
  priority: "High" | "Medium" | "Low";
  precondition: string;
  test_data: string;
  steps: string[];
  expected: string;
  expected_source?: "PRD" | "Inferensi AI";
  start_url: string;
};
export type PlanResponse = {
  editable: boolean;
  module: string | null;
  cases: PlanCase[];
  screens: { url: string; page_name: string }[];
};

// ---------- hasil penjelajahan (peta aplikasi) ----------
export type MapScreen = {
  page_name: string;
  purpose: string;
  url: string;
  public: boolean;
  depth: number;
  forms: string[];
  actions: string[];
  screenshot_url: string | null;
};
export type RunMap = { modules: { name: string; screens: MapScreen[] }[]; screens: number };

// ---------- modul kustom (alur bisnis) ----------
export type Flow = { id: number; app_id: number; name: string; steps: string; created_at: string; updated_at: string };

// ---------- data uji & persiapan otomatis ----------
export type TestDataValue = { id: number; app_id: number; set_name: string; value: string; used_by: string | null; used_at: string | null };
export type TestDataSet = { name: string; values: TestDataValue[]; available: number };
export type Hook = {
  id: number;
  app_id: number;
  name: string;
  when: "run" | "case";
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  url: string;
  body: string;
  capture: Record<string, string>;
  active: boolean;
  has_headers: boolean;
};
export type HookInput = { name: string; when: Hook["when"]; method: Hook["method"]; url: string; headers: string; body: string; capture: string };

// ---------- uji beban (performance) ----------
export type PerfRequestCfg = {
  name: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD";
  url: string;
  headers: Record<string, string>;
  body: string;
  weight: number;
  expect_status: number | null;
};
export type PerfConfig = {
  requests: PerfRequestCfg[];
  profile: { vus: number; duration_s: number; ramp_up_s: number; think_ms: number };
  thresholds: { p95_ms: number | null; error_rate_pct: number | null };
  environment: "dev" | "production";
  approved_hosts: string[];
};
export type PerfTest = { id: number; app_id: number; name: string; config: PerfConfig; has_secret_headers: boolean; updated_at: string };
export type PerfTestInput = Omit<PerfConfig, never> & { name: string; secret_headers?: string };
export type PerfPoint = { elapsed_s: number; vus: number; requests: number; rps: number; errors: number; p95_ms: number; total: number };
export type PerfStats = { p50_ms: number; p90_ms: number; p95_ms: number; p99_ms: number; min_ms: number; max_ms: number; avg_ms: number };
export type PerfSummary = PerfStats & { total: number; errors: number; error_rate_pct: number; rps: number; duration_s: number; vus: number };
export type PerfResult = {
  summary?: PerfSummary;
  requests?: (PerfStats & { name: string; method: string; url: string; count: number; errors: number; error_rate_pct: number; status_codes: Record<string, number> })[];
  status_codes?: Record<string, number>;
  timeline?: PerfPoint[];
  verdict?: { passed: boolean; checks: { name: string; target: string; actual: string; passed: boolean }[] };
};
export type PerfRun = {
  id: number;
  test_id: number;
  name: string;
  status: "running" | "completed" | "stopped" | "failed";
  config: PerfConfig;
  result: PerfResult;
  note: string;
  started_at: string;
  finished_at: string | null;
};
export type PerfRunBrief = Omit<PerfRun, "result"> & { summary: PerfSummary | null; passed: boolean | null };

// ---------- API testing ----------
export type ApiAssertionKind = "status" | "json" | "time" | "body" | "header";
export type ApiAssertionOp = "eq" | "ne" | "contains" | "exists" | "not_exists" | "lt" | "gt" | "type";
export type ApiAssertion = { kind: ApiAssertionKind; op: ApiAssertionOp; expected: string; path: string };
export type ApiMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD";
export type ApiCaseCfg = {
  name: string;
  method: ApiMethod;
  url: string;
  headers: Record<string, string>;
  body: string;
  assertions: ApiAssertion[];
  capture: Record<string, string>;
};
export type ApiSuiteConfig = {
  base_url: string;
  environment: "dev" | "production";
  approved_hosts: string[];
  variables: Record<string, string>;
  cases: ApiCaseCfg[];
};
export type ApiSuite = { id: number; app_id: number; name: string; config: ApiSuiteConfig; has_secret_headers: boolean; updated_at: string };
export type ApiSuiteInput = ApiSuiteConfig & { name: string; secret_headers?: string };
export type ApiCheck = { description: string; passed: boolean; actual: string };
export type ApiCaseResult = {
  name: string;
  request: { method: string; url: string; body: string };
  status?: number;
  ms?: number;
  response?: string;
  assertions: ApiCheck[];
  error: string;
  passed: boolean;
};
export type ApiSummary = { total: number; passed: number; failed: number; errors: number };
export type ApiRun = {
  id: number;
  suite_id: number;
  app_id: number;
  name: string;
  status: "running" | "completed" | "stopped" | "failed";
  config: ApiSuiteConfig;
  result: { cases?: ApiCaseResult[]; summary?: ApiSummary; variables?: Record<string, unknown>; total?: number };
  note: string;
  started_at: string;
  finished_at: string | null;
};
export type ApiRunBrief = Omit<ApiRun, "result" | "config"> & { summary: ApiSummary | null };
export type ApiImport = { cases: ApiCaseCfg[]; base_url: string; secret_headers?: string };