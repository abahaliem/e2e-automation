import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { HistoryPage } from "./History";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, listApps: vi.fn(), listRuns: vi.fn(), deleteRun: vi.fn() } };
});
const mocked = vi.mocked(api);

const run = (id: number, status: string, extra = {}) => ({
  id, app_id: 4, app_name: "WFM", platform: "android", mode: "deep", module: "Autentikasi", status, environment: "dev",
  counts: {}, started_at: "2026-11-09T08:00:00", finished_at: null, note: "", url: "android://x", ...extra,
});

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listApps.mockResolvedValue([]);
});

describe("Riwayat run", () => {
  it("hapus run selesai dengan konfirmasi; run berjalan tidak bisa dihapus", async () => {
    mocked.listRuns.mockResolvedValue([run(19, "completed"), run(21, "running")] as never);
    mocked.deleteRun.mockResolvedValue(undefined);
    renderWithProviders(<HistoryPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByLabelText("Hapus run 19"));
    expect(screen.queryByLabelText("Hapus run 21")).not.toBeInTheDocument();
    expect(screen.getByText("Hapus permanen?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hapus" }));
    await waitFor(() => expect(mocked.deleteRun).toHaveBeenCalledWith(19));
    expect(await screen.findByText("Run #19 dan evidence-nya dihapus.")).toBeInTheDocument();
  });

  it("run menunggu review menautkan ke halaman review", async () => {
    mocked.listRuns.mockResolvedValue([run(20, "paused", { awaiting_review: true })] as never);
    renderWithProviders(<HistoryPage />);
    expect(await screen.findByText("Menunggu review")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review test case" })).toHaveAttribute("href", "/runs/20/review");
  });
});
