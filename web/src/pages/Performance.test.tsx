import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "@/lib/api";
import type { PerfRun, PerfTest } from "@/lib/types";
import { app, renderWithProviders } from "@/test/render";
import { PerformancePage } from "./Performance";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listApps: vi.fn(), listPerfTests: vi.fn(), createPerfTest: vi.fn(), updatePerfTest: vi.fn(), deletePerfTest: vi.fn(),
      importCurl: vi.fn(), runPerfTest: vi.fn(), listPerfRuns: vi.fn(), getPerfRun: vi.fn(), stopPerfRun: vi.fn(),
    },
  };
});
const mocked = vi.mocked(api);
beforeEach(() => {
  vi.clearAllMocks();
  mocked.listApps.mockResolvedValue([app]);
});

const config = {
  requests: [{ name: "Daftar WO", method: "GET" as const, url: "http://hr-dev.kantor.local/wo", headers: {}, body: "", weight: 1, expect_status: null }],
  profile: { vus: 20, duration_s: 60, ramp_up_s: 10, think_ms: 500 },
  thresholds: { p95_ms: 1000, error_rate_pct: 1 },
  environment: "dev" as const,
  approved_hosts: [],
};
const test: PerfTest = { id: 5, app_id: 3, name: "Daftar WO 20 user", config, has_secret_headers: true, updated_at: "" };

describe("Performance", () => {
  it("skenario baru dari cURL, header rahasia dipisah, host luar minta konfirmasi", async () => {
    mocked.listPerfTests.mockResolvedValue([]);
    mocked.importCurl.mockResolvedValue({
      request: { name: "wo", method: "GET", url: "https://api.lain.test/wo", headers: {}, body: "", weight: 1, expect_status: null },
      secret_headers: "Authorization: Bearer abc",
    });
    mocked.createPerfTest
      .mockRejectedValueOnce(new ApiError(422, "Host api.lain.test bukan domain aplikasi ini. Konfirmasi bahwa Anda berwenang"))
      .mockResolvedValueOnce(test);
    renderWithProviders(<PerformancePage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Nama uji"), "Daftar WO 20 user");
    await user.type(screen.getByLabelText("Atau tempel perintah cURL"), "curl https://api.lain.test/wo -H 'Authorization: Bearer abc'");
    await user.click(screen.getByRole("button", { name: "Tambahkan" }));
    expect(await screen.findByDisplayValue("https://api.lain.test/wo")).toBeInTheDocument();
    expect(screen.getByLabelText("Header rahasia untuk semua request")).toHaveValue("Authorization: Bearer abc");
    await user.click(screen.getByRole("button", { name: /Simpan skenario/ }));
    await user.click(await screen.findByRole("button", { name: /Saya berwenang, simpan/ }));
    await waitFor(() => expect(mocked.createPerfTest).toHaveBeenCalledTimes(2));
    expect(mocked.createPerfTest.mock.calls[1][1]).toMatchObject({ approved_hosts: ["api.lain.test"], secret_headers: "Authorization: Bearer abc" });
  });

  it("jalankan, tampilkan hasil lulus/tidak dengan angka p95 dan error", async () => {
    mocked.listPerfTests.mockResolvedValue([test]);
    mocked.listPerfRuns.mockResolvedValue([]);
    const done: PerfRun = {
      id: 9, test_id: 5, name: test.name, status: "completed", config, note: "", started_at: "2026-11-10T10:00:00", finished_at: "2026-11-10T10:01:00",
      result: {
        summary: { total: 1200, errors: 30, error_rate_pct: 2.5, rps: 20, duration_s: 60, vus: 20, p50_ms: 120, p90_ms: 600, p95_ms: 1450, p99_ms: 2100, min_ms: 40, max_ms: 3000, avg_ms: 300 },
        requests: [{ name: "Daftar WO", method: "GET", url: config.requests[0].url, count: 1200, errors: 30, error_rate_pct: 2.5, status_codes: { "200": 1170, "500": 30 }, p50_ms: 120, p90_ms: 600, p95_ms: 1450, p99_ms: 2100, min_ms: 40, max_ms: 3000, avg_ms: 300 }],
        timeline: [{ elapsed_s: 1, vus: 5, requests: 10, rps: 10, errors: 0, p95_ms: 200, total: 10 }, { elapsed_s: 2, vus: 10, requests: 20, rps: 20, errors: 1, p95_ms: 900, total: 30 }],
        verdict: { passed: false, checks: [{ name: "p95 latency", target: "≤ 1000 ms", actual: "1450 ms", passed: false }, { name: "Error rate", target: "≤ 1%", actual: "2.5%", passed: false }] },
      },
    };
    mocked.runPerfTest.mockResolvedValue({ ...done, status: "running" });
    mocked.getPerfRun.mockResolvedValue(done);
    renderWithProviders(<PerformancePage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Jalankan uji beban/ }));
    expect(await screen.findByText("TIDAK LULUS")).toBeInTheDocument();
    expect(screen.getByText("p95 latency: 1450 ms (target ≤ 1000 ms)")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Request per detik" })).toBeInTheDocument();
    expect(screen.getByText("200: 1170, 500: 30")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Excel/ })).toHaveAttribute("href", "/api/perf-runs/9/xlsx");
  });

  it("Production wajib konfirmasi risiko sebelum dijalankan", async () => {
    mocked.listPerfTests.mockResolvedValue([{ ...test, config: { ...config, environment: "production" } }]);
    mocked.listPerfRuns.mockResolvedValue([]);
    renderWithProviders(<PerformancePage />);
    const user = userEvent.setup();
    const run = await screen.findByRole("button", { name: /Jalankan uji beban/ });
    expect(run).toBeDisabled();
    await user.click(screen.getByLabelText(/Saya paham risikonya ke Production/));
    expect(run).toBeEnabled();
  });
});
