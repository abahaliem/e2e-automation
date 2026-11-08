import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import type { Snapshot } from "@/lib/types";
import { useRunStream } from "@/lib/ws";
import { renderWithProviders } from "@/test/render";
import { RunLivePage } from "./RunLive";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, getRun: vi.fn(), control: vi.fn(), resumeRun: vi.fn() } };
});
vi.mock("@/lib/ws", async (orig) => {
  const mod = await orig<typeof import("@/lib/ws")>();
  return { ...mod, useRunStream: vi.fn() };
});

const mocked = vi.mocked(api);
const run = {
  id: 9, app_id: 3, app_name: "Web HR", platform: "web", url: "http://hr", mode: "deep", module: "Pengguna",
  environment: "dev", profile_id: 1, profile_name: "GLM", account_id: 7, status: "running",
  started_at: "2026-11-08T10:00:00", finished_at: null, folder: "x", counts: {}, note: "", model: "glm",
  confirm_each_step: false, active: true, control_state: "running",
};

function snapshot(over: Partial<Snapshot> = {}): Snapshot {
  return {
    type: "snapshot", run_id: 9, seq: 3, status: "running", control_state: "running", awaiting_confirm: false,
    confirm_each_step: false, note: "", counts: {}, current_tc: "TC-PEN-002", planned: null, screens: 0,
    steps: [{ type: "step.done", tc_id: "TC-PEN-002", step_no: 1, result: "ok", screenshot: "screenshots/a.png", description: "Isi field 'Nama'", actor: "ai" }],
    cases: [
      { tc_id: "TC-PEN-001", title: "Tambah pengguna valid", status: "Pass" },
      { tc_id: "TC-PEN-002", title: "Validasi format email", status: null },
    ],
    ...over,
  };
}

function setStream(snap: Snapshot | null) {
  vi.mocked(useRunStream).mockReturnValue({ snapshot: snap, steps: snap?.steps ?? [], events: [], frame: null, connected: true });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getRun.mockResolvedValue(run as never);
  mocked.control.mockResolvedValue({ state: "paused" });
});

describe("Run berjalan", () => {
  it("menampilkan antrian test case, langkah, dan progres", async () => {
    setStream(snapshot());
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    expect(await screen.findByText("Tambah pengguna valid")).toBeInTheDocument();
    expect(screen.getByText("Test case 2 dari 2")).toBeInTheDocument();
    expect(screen.getAllByText("Isi field 'Nama'").length).toBeGreaterThan(0);
  });

  it("Jeda memanggil kontrol", async () => {
    setStream(snapshot());
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Jeda$/ }));
    expect(mocked.control).toHaveBeenCalledWith(9, { command: "pause" });
  });

  it("banner AI tidak merespons menampilkan Coba lagi", async () => {
    setStream(snapshot({ status: "paused", control_state: null, note: "Endpoint AI bermasalah: timeout" }));
    mocked.getRun.mockResolvedValue({ ...run, status: "paused", active: false, note: "Endpoint AI bermasalah: timeout" } as never);
    mocked.resumeRun.mockResolvedValue(run as never);
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    const user = userEvent.setup();
    expect(await screen.findByText(/Endpoint AI bermasalah: timeout/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Coba lagi/ }));
    expect(mocked.resumeRun).toHaveBeenCalledWith(9);
  });

  it("run selesai menautkan ke halaman hasil", async () => {
    setStream(snapshot({ status: "completed", control_state: null }));
    mocked.getRun.mockResolvedValue({ ...run, status: "completed", active: false } as never);
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    expect(await screen.findByRole("link", { name: /Lihat hasil/ })).toHaveAttribute("href", "/runs/9/result");
  });

  it("tombol Jalankan langkah hilang setelah diklik (tidak bisa klik ganda)", async () => {
    const planned = {
      type: "step.planned" as const, tc_id: "TC-PEN-002", step_no: 2, action: "click", element: null,
      thought: "", risk: "low", description: "Klik tombol 'Simpan'", viewport: null,
    };
    setStream(snapshot({ planned, awaiting_confirm: true, confirm_each_step: true }));
    mocked.control.mockResolvedValue({ state: "running" });
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Jalankan langkah/ }));
    expect(mocked.control).toHaveBeenCalledWith(9, { command: "confirm_step" });
    expect(screen.queryByRole("button", { name: /Jalankan langkah/ })).not.toBeInTheDocument();
  });

  it("status Dijeda ditampilkan", async () => {
    setStream(snapshot({ control_state: "paused" }));
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    expect(await screen.findByText("Dijeda")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Lanjutkan/ })).toBeInTheDocument();
  });
});
