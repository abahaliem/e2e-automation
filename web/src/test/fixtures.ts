import type { CaseDetailResponse, Run, TestCase } from "@/lib/types";

export const run: Run = {
  id: 9,
  app_id: 3,
  app_name: "Web HR",
  platform: "web",
  url: "http://hr-dev.kantor.local",
  mode: "deep",
  module: "Pengguna",
  environment: "dev",
  profile_id: 1,
  profile_name: "GLM",
  account_id: 7,
  status: "completed",
  started_at: "2026-11-05T10:12:00",
  finished_at: "2026-11-05T10:24:00",
  folder: "x",
  counts: { Pass: 1, Fail: 1, "Perlu Review": 1 },
  note: "",
  model: "z-ai/glm-5.3-flash",
  confirm_each_step: false,
  active: false,
  control_state: null,
};

function tc(id: string, title: string, status_ai: TestCase["status_ai"], extra: Partial<TestCase> = {}): TestCase {
  const base: TestCase = {
    id,
    module: "Pengguna",
    page: "Tambah Pengguna",
    title,
    type: "positif",
    priority: "High",
    precondition: "",
    test_data: "",
    steps: ["Buka Tambah Pengguna", "Klik Simpan"],
    expected: "Pengguna tersimpan",
    expected_source: "Inferensi AI",
    start_url: "",
    status_ai,
    actual: "",
    ai_note: "",
    severity: null,
    status_final: null,
    reviewer_note: "",
    effective_status: status_ai,
    ...extra,
  };
  base.effective_status = base.status_final ?? base.status_ai;
  return base;
}

export const cases: TestCase[] = [
  tc("TC-PEN-001", "Tambah pengguna valid", "Pass"),
  tc("TC-PEN-002", "Validasi format email", "Perlu Review", { type: "validasi", severity: "Minor" }),
  tc("TC-PEN-003", "Nama dengan apostrof", "Fail", {
    type: "boundary",
    severity: "Major",
    status_final: "Fail",
    expected: "Pengguna O'Brien tersimpan",
    actual: "Internal Server Error",
  }),
];

export const detail: CaseDetailResponse = {
  ...cases[2],
  log: [
    { step_no: 1, action: "type", actor: "ai", text: "Isi field 'Nama' dengan 'O'Brien'", result: "ok", guard: "allowed", thought: "", location: "", screenshot_url: "/api/runs/9/files/screenshots/a.png" },
    { step_no: 2, action: "click", actor: "ai", text: "Klik tombol 'Simpan'", result: "ok", guard: "allowed", thought: "", location: "", screenshot_url: "/api/runs/9/files/screenshots/b.png" },
    { step_no: 3, action: "done", actor: "ai", text: "Verifikasi hasil akhir (fail)", result: "ok", guard: "allowed", thought: "", location: "", screenshot_url: "/api/runs/9/files/screenshots/c.png" },
  ],
  technical: ["HTTP 500 POST http://hr-dev.kantor.local/users"],
};
