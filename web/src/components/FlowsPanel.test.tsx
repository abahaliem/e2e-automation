import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "@/lib/api";
import { app, renderWithProviders } from "@/test/render";
import { FlowsPanel } from "./FlowsPanel";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, listFlows: vi.fn(), createFlow: vi.fn(), updateFlow: vi.fn(), deleteFlow: vi.fn() } };
});
const mocked = vi.mocked(api);
beforeEach(() => vi.clearAllMocks());

const flow = { id: 5, app_id: 3, name: "Alur WO sampai Closed", steps: "1. Buka WO\n2. Close", created_at: "", updated_at: "" };

describe("Alur bisnis (modul kustom)", () => {
  it("tambah alur baru dengan validasi", async () => {
    mocked.listFlows.mockResolvedValue([]);
    mocked.createFlow.mockResolvedValue(flow);
    renderWithProviders(<FlowsPanel app={app} />);
    const user = userEvent.setup();
    expect(await screen.findByText("Belum ada alur bisnis untuk aplikasi ini.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tambah alur" }));
    await user.click(screen.getAllByRole("button", { name: "Tambah alur" }).at(-1)!);
    expect(screen.getByText("Tulis langkah alurnya")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Nama alur"), "Alur WO sampai Closed");
    await user.type(screen.getByLabelText("Langkah alur dan hasil yang diharapkan"), "1. Buka WO{enter}2. Close");
    await user.click(screen.getAllByRole("button", { name: "Tambah alur" }).at(-1)!);
    await waitFor(() => expect(mocked.createFlow).toHaveBeenCalledWith(3, { name: "Alur WO sampai Closed", steps: "1. Buka WO\n2. Close" }));
  });

  it("daftar alur dengan Uji alur ini, ubah, dan pesan error nama bentrok", async () => {
    mocked.listFlows.mockResolvedValue([flow]);
    mocked.updateFlow.mockRejectedValue(new ApiError(422, "Periksa", { name: "Nama ini sama dengan modul hasil penjelajahan" }));
    renderWithProviders(<FlowsPanel app={{ ...app, platform: "android" }} />);
    const user = userEvent.setup();
    expect(await screen.findByRole("link", { name: /Uji alur ini/ })).toHaveAttribute(
      "href", "/runs/new?app=3&module=Alur%20WO%20sampai%20Closed&platform=android");
    await user.click(screen.getByLabelText("Ubah alur Alur WO sampai Closed"));
    const name = screen.getByLabelText("Nama alur");
    await user.clear(name);
    await user.type(name, "Work Order");
    await user.click(screen.getByRole("button", { name: "Simpan alur" }));
    expect(await screen.findByText("Nama ini sama dengan modul hasil penjelajahan")).toBeInTheDocument();
  });
});
