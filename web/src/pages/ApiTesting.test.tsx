import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "@/lib/api";
import type { ApiRun, ApiSuite, ApiSuiteConfig } from "@/lib/types";
import { app, renderWithProviders } from "@/test/render";
import { ApiTestingPage } from "./ApiTesting";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listApps: vi.fn(), listApiSuites: vi.fn(), createApiSuite: vi.fn(), updateApiSuite: vi.fn(), deleteApiSuite: vi.fn(),
      importApiCases: vi.fn(), generateApiCases: vi.fn(), runApiSuite: vi.fn(), listApiRuns: vi.fn(), getApiRun: vi.fn(),
      stopApiRun: vi.fn(), deleteApiRun: vi.fn(),
    },
  };
});
const mocked = vi.mocked(api);
beforeEach(() => {
  vi.clearAllMocks();
  mocked.listApps.mockResolvedValue([app]);
});

const config: ApiSuiteConfig = {
  base_url: "http://hr-dev.kantor.local",
  environment: "dev",
  approved_hosts: [],
  variables: {},
  cases: [{ name: "Detail WO", method: "GET", url: "{{base_url}}/wo/1", headers: {}, body: "",
    assertions: [{ kind: "json", op: "eq", expected: "CLOSED", path: "data.status" }], capture: {} }],
};
const suite: ApiSuite = { id: 4, app_id: 3, name: "Work Order API", config, has_secret_headers: true, updated_at: "" };

describe("API Test", () => {
  it("impor OpenAPI mengisi test case dan base URL, host luar minta konfirmasi saat simpan", async () => {
    mocked.listApiSuites.mockResolvedValue([]);
    mocked.importApiCases.mockResolvedValue({
      base_url: "https://api.lain.test",
      cases: [{ name: "Buat WO", method: "POST", url: "{{base_url}}/wo", headers: {}, body: "{}", assertions: [], capture: { wo_id: "data.id" } }],
    });
    mocked.createApiSuite
      .mockRejectedValueOnce(new ApiError(422, "Host api.lain.test bukan domain aplikasi ini. Konfirmasi bahwa Anda berwenang"))
      .mockResolvedValueOnce(suite);
    renderWithProviders(<ApiTestingPage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Nama suite"), "Work Order API");
    await user.click(screen.getByRole("button", { name: "OpenAPI / Swagger" }));
    await user.type(screen.getByLabelText(/Spesifikasi OpenAPI/), "openapi: 3.0.0");
    await user.click(screen.getByRole("button", { name: "Tambahkan" }));
    expect(await screen.findByText(/1 test case ditambahkan/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Base URL/)).toHaveValue("https://api.lain.test");
    expect(screen.getByText("Buat WO")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Simpan suite/ }));
    await user.click(await screen.findByRole("button", { name: /Saya berwenang, simpan/ }));
    await waitFor(() => expect(mocked.createApiSuite).toHaveBeenCalledTimes(2));
    expect(mocked.createApiSuite.mock.calls[1][1]).toMatchObject({
      approved_hosts: ["api.lain.test"],
      cases: [{ name: "Buat WO", capture: { wo_id: "data.id" } }],
    });
  });

  it("AI menyusun test case dari spesifikasi dengan fokus", async () => {
    mocked.listApiSuites.mockResolvedValue([]);
    mocked.generateApiCases.mockResolvedValue({ base_url: "", cases: [
      { name: "Buat WO valid", method: "POST", url: "{{base_url}}/wo", headers: {}, body: "{}", assertions: [], capture: {} },
      { name: "Buat WO tanpa teknisi", method: "POST", url: "{{base_url}}/wo", headers: {}, body: "{}", assertions: [], capture: {} }] });
    renderWithProviders(<ApiTestingPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Susun dengan AI/ }));
    await user.type(screen.getByLabelText(/Spesifikasi OpenAPI/), "openapi");
    await user.type(screen.getByLabelText("Fokus pengujian"), "work order");
    await user.click(screen.getByRole("button", { name: "Susun test case" }));
    expect(await screen.findByText("Buat WO tanpa teknisi")).toBeInTheDocument();
    expect(mocked.generateApiCases).toHaveBeenCalledWith(3, "openapi", "work order");
  });

  it("jalankan suite, tampilkan hasil per test case dengan nilai aktual", async () => {
    mocked.listApiSuites.mockResolvedValue([suite]);
    mocked.listApiRuns.mockResolvedValue([]);
    const done: ApiRun = {
      id: 8, suite_id: 4, app_id: 3, name: suite.name, status: "completed", config, note: "", started_at: "2026-11-10T10:00:00", finished_at: "2026-11-10T10:00:02",
      result: {
        cases: [{ name: "Detail WO", request: { method: "GET", url: "http://hr-dev.kantor.local/wo/1", body: "" }, status: 200, ms: 35, response: "{}",
          assertions: [{ description: "JSON data.status = CLOSED", passed: false, actual: "OPEN" }], error: "", passed: false }],
        summary: { total: 1, passed: 0, failed: 1, errors: 0 },
      },
    };
    mocked.runApiSuite.mockResolvedValue({ ...done, status: "running", result: {} });
    mocked.getApiRun.mockResolvedValue(done);
    renderWithProviders(<ApiTestingPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Jalankan suite/ }));
    expect(await screen.findByText("0/1 lulus · 1 gagal")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /GAGAL.*Detail WO/ }));
    expect(screen.getByText(/JSON data.status = CLOSED/)).toBeInTheDocument();
    expect(screen.getByText(/aktual: OPEN/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Excel/ })).toHaveAttribute("href", "/api/api-runs/8/xlsx");
  });

  it("suite Production yang mengubah data wajib konfirmasi", async () => {
    mocked.listApiSuites.mockResolvedValue([{ ...suite, config: { ...config, environment: "production", cases: [{ ...config.cases[0], method: "POST" }] } }]);
    mocked.listApiRuns.mockResolvedValue([]);
    renderWithProviders(<ApiTestingPage />);
    const user = userEvent.setup();
    const run = await screen.findByRole("button", { name: /Jalankan suite/ });
    expect(run).toBeDisabled();
    await user.click(screen.getByLabelText(/mengubah data Production/));
    expect(run).toBeEnabled();
  });
});
