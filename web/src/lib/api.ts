import type {
  Account,
  ApkUpload,
  App,
  AuthStatus,
  AuthUser,
  PlanCase,
  PlanResponse,
  Role,
  RunMap,
  UserRow,
  AppInput,
  CaseDetailResponse,
  ControlInput,
  ControlState,
  Device,
  Finding,
  InstallResult,
  Profile,
  ProfileInput,
  ReportSettings,
  ReviewInput,
  Run,
  Skill,
  SkillsResponse,
  RunInput,
  Snapshot,
  Stats,
  TestCase,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public fieldErrors: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Event saat server meminta login ulang (mode server: sesi habis). */
export const UNAUTHORIZED_EVENT = "qa:unauthorized";

export async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(path, {
    ...rest,
    credentials: "same-origin",
    headers: {
      // perlindungan CSRF sederhana: server menolak perubahan data tanpa header ini (mode server)
      "X-QA-Agent": "1",
      ...(json !== undefined ? { "content-type": "application/json" } : {}),
      ...(headers ?? {}),
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 401 && !path.startsWith("/api/auth/") && typeof window !== "undefined") {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const body = (data ?? {}) as { detail?: unknown; field_errors?: Record<string, string> };
    const message =
      typeof body.detail === "string" ? body.detail : `Permintaan gagal (HTTP ${res.status})`;
    throw new ApiError(res.status, message, body.field_errors ?? {});
  }
  return data as T;
}

const get = <T,>(path: string) => request<T>(path);
const post = <T,>(path: string, json?: unknown) => request<T>(path, { method: "POST", json: json ?? {} });
const patch = <T,>(path: string, json: unknown) => request<T>(path, { method: "PATCH", json });
const del = (path: string) => request<void>(path, { method: "DELETE" });

export const api = {
  // login & pengguna (mode server)
  authStatus: () => get<AuthStatus>("/api/auth/status"),
  login: (username: string, password: string) => post<{ user: AuthUser }>("/api/auth/login", { username, password }),
  logout: () => post<void>("/api/auth/logout"),
  changePassword: (current: string, next: string) => post<void>("/api/auth/password", { current, new: next }),
  listUsers: () => get<UserRow[]>("/api/users"),
  createUser: (body: { username: string; password: string; role: Role }) => post<UserRow>("/api/users", body),
  patchUser: (id: number, body: { role?: Role; active?: boolean; password?: string }) => patch<UserRow>(`/api/users/${id}`, body),
  deleteUser: (id: number) => del(`/api/users/${id}`),
  connectDevice: (body: { address: string; pair_address?: string; pair_code?: string }) =>
    post<{ address: string; message: string }>("/api/devices/connect", body),

  // profil AI
  listProfiles: () => get<Profile[]>("/api/profiles"),
  createProfile: (body: ProfileInput) => post<Profile>("/api/profiles", body),
  updateProfile: (id: number, body: Partial<ProfileInput>) => patch<Profile>(`/api/profiles/${id}`, body),
  deleteProfile: (id: number) => del(`/api/profiles/${id}`),
  listModels: (id: number) => post<{ models: string[]; message: string }>(`/api/profiles/${id}/models`),
  testProfile: (id: number) =>
    post<{ text_ok: boolean; vision_ok: boolean; latency_ms: number; message: string }>(`/api/profiles/${id}/test`),

  // aplikasi & akun
  listApps: () => get<App[]>("/api/apps"),
  getApp: (id: number) => get<App>(`/api/apps/${id}`),
  createApp: (body: AppInput) => post<App>("/api/apps", body),
  updateApp: (id: number, body: Partial<AppInput>) => patch<App>(`/api/apps/${id}`, body),
  deleteApp: (id: number) => del(`/api/apps/${id}`),
  appModules: (id: number) => get<{ modules: string[]; explored: boolean }>(`/api/apps/${id}/modules`),
  listAccounts: (appId: number) => get<Account[]>(`/api/apps/${appId}/accounts`),
  createAccount: (appId: number, body: { role: string; username: string; password: string }) =>
    post<Account>(`/api/apps/${appId}/accounts`, body),
  updateAccountPassword: (id: number, password: string) => patch<Account>(`/api/accounts/${id}`, { password }),
  deleteAccount: (id: number) => del(`/api/accounts/${id}`),

  // run
  listRuns: (params: { status?: string; app_id?: number; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.app_id) q.set("app_id", String(params.app_id));
    if (params.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return get<Run[]>(`/api/runs${qs ? `?${qs}` : ""}`);
  },
  getRun: (id: number) => get<Run>(`/api/runs/${id}`),
  createRun: (body: RunInput) => post<Run>("/api/runs", body),
  runState: (id: number) => get<Snapshot>(`/api/runs/${id}/state`),
  control: (id: number, body: ControlInput) => post<{ state: ControlState }>(`/api/runs/${id}/control`, body),
  resumeRun: (id: number) => post<Run>(`/api/runs/${id}/resume`),
  deleteRun: (id: number) => del(`/api/runs/${id}`),
  runMap: (id: number) => get<RunMap>(`/api/runs/${id}/map`),
  getPlan: (id: number) => get<PlanResponse>(`/api/runs/${id}/plan`),
  savePlan: (id: number, cases: PlanCase[]) => request<PlanResponse>(`/api/runs/${id}/plan`, { method: "PUT", json: { cases } }),

  // hasil
  listCases: (runId: number) => get<TestCase[]>(`/api/runs/${runId}/cases`),
  caseDetail: (runId: number, tcId: string) =>
    get<CaseDetailResponse>(`/api/runs/${runId}/cases/${encodeURIComponent(tcId)}`),
  patchCase: (runId: number, tcId: string, body: ReviewInput) =>
    patch<{ case: TestCase; warning: string | null }>(`/api/runs/${runId}/cases/${encodeURIComponent(tcId)}`, body),
  downloadUrl: (runId: number, kind: "xlsx" | "html" | "pdf") => `/api/runs/${runId}/download/${kind}`,
  fileUrl: (runId: number, path: string) => `/api/runs/${runId}/files/${path}`,

  // skill QA
  listSkills: () => get<SkillsResponse>("/api/skills"),
  uploadSkill: (file: File) =>
    request<Skill>(`/api/skills?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      body: file,
      headers: { "content-type": "application/octet-stream" },
    }),
  patchSkill: (id: number, body: Partial<Pick<Skill, "name" | "stages" | "app_ids" | "active">>) =>
    patch<Skill>(`/api/skills/${id}`, body),
  deleteSkill: (id: number) => del(`/api/skills/${id}`),
  skillText: (id: number) => get<{ text: string }>(`/api/skills/${id}/text`),
  previewSkills: (body: { app_id: number; module: string }) => post<{ cases: TestCase[] }>("/api/skills/preview", body),

  // pengaturan laporan
  reportSettings: () => get<ReportSettings>("/api/settings/report"),
  patchReportSettings: (body: { company_name: string }) => patch<ReportSettings>("/api/settings/report", body),
  uploadTemplate: (file: File) =>
    request<ReportSettings>(`/api/settings/report/template?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      body: file,
      headers: { "content-type": "application/octet-stream" },
    }),
  deleteTemplate: () => del("/api/settings/report/template"),

  // perangkat Android
  listDevices: () => get<{ devices: Device[] }>("/api/devices"),
  devicePackages: (serial: string) =>
    get<{ packages: string[]; apps?: { package: string; version: string | null }[] }>(
      `/api/devices/${encodeURIComponent(serial)}/packages`,
    ),
  uploadApk: (serial: string, file: File) =>
    request<ApkUpload>(`/api/devices/${encodeURIComponent(serial)}/apk?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      body: file,
      headers: { "content-type": "application/octet-stream" },
    }),
  deviceScreenUrl: (serial: string, tick: number) => `/api/devices/${encodeURIComponent(serial)}/screen?t=${tick}`,
  installApk: (serial: string, file: File) =>
    request<InstallResult>(`/api/devices/${encodeURIComponent(serial)}/install?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      body: file,
      headers: { "content-type": "application/octet-stream" },
    }),

  // statistik
  stats: (days = 30) => get<Stats>(`/api/stats?days=${days}`),
  findings: (limit = 10) => get<Finding[]>(`/api/findings?limit=${limit}`),
  importRuns: (folder: string, appId: number) =>
    post<{ imported: number; failed: { folder: string; error: string }[] }>("/api/import-runs", { folder, app_id: appId }),
};
