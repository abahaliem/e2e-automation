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

  it("error yang terdeteksi tampil dengan foto bukti saat muncul", async () => {
    const snap = snapshot();
    vi.mocked(useRunStream).mockReturnValue({
      snapshot: snap, steps: snap.steps, frame: null, connected: true,
      events: [
        { type: "signal", tc_id: "TC-PEN-002", signal: { kind: "ui_error", message: "Pesan muncul sesaat lalu hilang: Gagal simpan", screenshot: "screenshots/TC-PEN-002_step-02_error-1.png", at: "2026-11-11T10:25:10" } },
        { type: "signal", tc_id: "TC-PEN-002", signal: { kind: "http_error", message: "HTTP 404", status: 404, url: "http://hr/x" } },
        { type: "signal", tc_id: "TC-PEN-001", signal: { kind: "page_error", message: "dari test case lain" } },
      ],
    });
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    const panel = await screen.findByRole("alert", { name: "Error terdeteksi" });
    expect(panel).toHaveTextContent("Error terdeteksi di test case ini (1)");
    expect(panel).toHaveTextContent("10:25:10 Pesan error di layar: Pesan muncul sesaat lalu hilang: Gagal simpan");
    expect(screen.getByRole("img", { name: /Bukti error/ })).toHaveAttribute("src", expect.stringContaining("TC-PEN-002_step-02_error-1.png"));
  });

  it("penghitung waktu tidak berjalan selama dijeda", async () => {
    const now = Date.now();
    // run mulai 10 menit lalu, 3 menit dijeda sebelumnya, dan sedang dijeda sejak 2 menit lalu → 05:00
    const started = new Date(now - 10 * 60_000);
    const iso = `${started.getFullYear()}-${String(started.getMonth() + 1).padStart(2, "0")}-${String(started.getDate()).padStart(2, "0")}T${started.toTimeString().slice(0, 8)}`;
    mocked.getRun.mockResolvedValue({ ...run, started_at: iso } as never);
    setStream(snapshot({ control_state: "paused", paused_seconds: 180, paused_since: now - 120_000 }));
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    expect(await screen.findByText(/^05:0[01]$/)).toBeInTheDocument();
  });

  it("Jeda memanggil kontrol", async () => {
    setStream(snapshot());
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Jeda$/ }));
    expect(mocked.control).toHaveBeenCalledWith(9, { command: "pause" });
  });

  it("Seluruh aplikasi: agent bertanya lanjutkan memetakan atau selesai", async () => {
    mocked.getRun.mockResolvedValue({ ...run, mode: "explore", module: null } as never);
    setStream(snapshot({ control_state: "paused", current_tc: null, cases: [], screens: 3, asking: { screens: 3, modules: 2 } }));
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    const user = userEvent.setup();
    expect(await screen.findByText("Agent sudah memetakan 3 layar dalam 2 modul.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Lanjutkan memetakan" }));
    expect(mocked.control).toHaveBeenCalledWith(9, { command: "resume" });
    await user.click(screen.getByRole("button", { name: "Selesai" }));
    expect(mocked.control).toHaveBeenCalledWith(9, { command: "finish_explore" });
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

  it("run Android memakai bingkai HP, bukan bingkai browser", async () => {
    setStream(snapshot());
    mocked.getRun.mockResolvedValue({ ...run, platform: "android", url: "android://com.biznet.wfm.dev", device_serial: "202505G18414" } as never);
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    expect(await screen.findByTestId("phone-frame")).toBeInTheDocument();
    expect(screen.queryByText("android://com.biznet.wfm.dev")).not.toBeInTheDocument();
    expect(screen.getByText(/202505G18414/)).toBeInTheDocument();
  });

  it("run web tetap memakai bingkai browser", async () => {
    setStream(snapshot());
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    expect(await screen.findByTestId("browser-frame")).toBeInTheDocument();
    expect(screen.queryByTestId("phone-frame")).not.toBeInTheDocument();
  });

  it("status Dijeda ditampilkan", async () => {
    setStream(snapshot({ control_state: "paused" }));
    renderWithProviders(<RunLivePage />, { path: "/runs/9", route: "/runs/:runId" });
    expect(await screen.findByText("Dijeda")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Lanjutkan/ })).toBeInTheDocument();
  });
});
