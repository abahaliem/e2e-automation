import { act, screen, waitFor } from "@testing-library/react";
import { api } from "@/lib/api";
import type { RunEvent } from "@/lib/types";
import { useGlobalEvents } from "@/lib/ws";
import { run } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { DashboardPage } from "./Dashboard";
import { HistoryPage } from "./History";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, stats: vi.fn(), listRuns: vi.fn(), findings: vi.fn(), listApps: vi.fn(), resumeRun: vi.fn(), runState: vi.fn() } };
});
vi.mock("@/lib/ws", async (orig) => {
  const mod = await orig<typeof import("@/lib/ws")>();
  return { ...mod, useGlobalEvents: vi.fn() };
});
const mocked = vi.mocked(api);
let handler: ((e: RunEvent) => void) | null = null;

const stats = {
  total_runs: 48, web_runs: 31, android_runs: 17, cases_executed: 612, findings: 23, fail: 14, review: 9,
  pass_rate: 0.814, pass_rate_prev: 0.752, total_runs_prev: 40, findings_prev: 20, running: 1, days: 30,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useGlobalEvents).mockImplementation((fn) => {
    handler = fn;
    return true;
  });
  mocked.stats.mockResolvedValue(stats);
  mocked.findings.mockResolvedValue([
    { run_id: 9, tc_id: "TC-PEN-003", title: "Nama dengan apostrof menyebabkan error server", module: "Pengguna", status: "Fail", severity: "Major", app_name: "Web HR", platform: "web", started_at: "2026-11-05T10:12:00" },
  ]);
  mocked.listApps.mockResolvedValue([]);
});

describe("Dashboard", () => {
  it("angka dari /api/stats", async () => {
    mocked.listRuns.mockResolvedValue([]);
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("48")).toBeInTheDocument();
    expect(screen.getByText("612")).toBeInTheDocument();
    expect(screen.getByText("81,4%")).toBeInTheDocument();
    expect(screen.getByText(/naik 6,2%/)).toBeInTheDocument();
    expect(screen.getByText("14 Fail")).toBeInTheDocument();
    expect(screen.getByText("Nama dengan apostrof menyebabkan error server")).toBeInTheDocument();
  });

  it("kartu Sedang berjalan diperbarui dari event global", async () => {
    mocked.listRuns.mockImplementation(async (params) => (params?.status === "completed" ? [] : []));
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("Tidak ada run yang sedang berjalan")).toBeInTheDocument();
    mocked.listRuns.mockImplementation(async (params) =>
      params?.status === "completed" ? [] : [{ ...run, status: "running", active: true, control_state: "running" }],
    );
    act(() => handler?.({ type: "run.status", run_id: 9, status: "running" }));
    expect(await screen.findByRole("link", { name: /Lihat live/ })).toHaveAttribute("href", "/runs/9");
  });

  it("kartu Sedang berjalan (mockup 05): cuplikan layar, progres test case, timer", async () => {
    mocked.listRuns.mockImplementation(async (params) =>
      params?.status === "completed" ? [] : [{ ...run, status: "running", active: true, control_state: "running" }],
    );
    mocked.runState.mockResolvedValue({
      type: "snapshot", run_id: 9, seq: 5, status: "running", control_state: "running", awaiting_confirm: false,
      confirm_each_step: false, note: "", counts: {}, current_tc: "TC-PEN-003", planned: null, steps: [], screens: 0,
      cases: [
        { tc_id: "TC-PEN-001", title: "a", status: "Pass" },
        { tc_id: "TC-PEN-002", title: "b", status: "Fail" },
        { tc_id: "TC-PEN-003", title: "c", status: null },
        { tc_id: "TC-PEN-004", title: "d", status: null },
      ],
    });
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("Test case 3 dari 4")).toBeInTheDocument();
    const img = screen.getByAltText(/Layar live run Web HR/);
    expect(img.getAttribute("src")).toContain("/api/runs/9/thumbnail");
    expect(screen.getByTestId("run-timer").textContent).toMatch(/^\d{2}:\d{2}|^\d+:\d{2}:\d{2}/);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  });

  it("tabel Selesai dengan tombol dokumen", async () => {
    mocked.listRuns.mockImplementation(async (params) => (params?.status === "completed" ? [run] : []));
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByRole("link", { name: /Excel/ })).toHaveAttribute("href", "/api/runs/9/download/xlsx");
    expect(screen.getByRole("link", { name: /HTML/ })).toHaveAttribute("href", "/api/runs/9/download/html");
    expect(screen.getByText("Modul Pengguna")).toBeInTheDocument();
  });

  it("skeleton saat memuat", async () => {
    mocked.stats.mockReturnValue(new Promise(() => undefined));
    mocked.listRuns.mockReturnValue(new Promise(() => undefined));
    const { container } = renderWithProviders(<DashboardPage />);
    await waitFor(() => expect(container.querySelectorAll(".skeleton").length).toBeGreaterThan(0));
  });
});

describe("Riwayat", () => {
  it("daftar run dan tautan hasil", async () => {
    mocked.listRuns.mockResolvedValue([run]);
    renderWithProviders(<HistoryPage />);
    expect(await screen.findByText("Web HR")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Lihat hasil/ })).toHaveAttribute("href", "/runs/9/result");
  });

  it("state kosong", async () => {
    mocked.listRuns.mockResolvedValue([]);
    renderWithProviders(<HistoryPage />);
    expect(await screen.findByText("Belum ada run")).toBeInTheDocument();
  });
});
