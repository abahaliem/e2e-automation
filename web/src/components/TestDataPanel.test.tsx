import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { app, renderWithProviders } from "@/test/render";
import { HooksPanel, TestDataPanel } from "./TestDataPanel";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listTestData: vi.fn(), addTestData: vi.fn(), resetTestData: vi.fn(), deleteTestData: vi.fn(), deleteTestDataSet: vi.fn(),
      listHooks: vi.fn(), createHook: vi.fn(), updateHook: vi.fn(), deleteHook: vi.fn(), testHook: vi.fn(),
    },
  };
});
const mocked = vi.mocked(api);
beforeEach(() => vi.clearAllMocks());

const value = (id: number, v: string, used_by: string | null = null) => ({ id, app_id: 3, set_name: "wo_id", value: v, used_by, used_at: null });

describe("Data uji", () => {
  it("tambah nilai, lihat status tersedia/terpakai, dan pakai lagi", async () => {
    mocked.listTestData.mockResolvedValue([{ name: "wo_id", available: 1, values: [value(1, "000090014541", "Run #20 · TC-ALU-001"), value(2, "000090014542")] }]);
    mocked.addTestData.mockResolvedValue([]);
    mocked.resetTestData.mockResolvedValue(value(1, "000090014541"));
    renderWithProviders(<TestDataPanel app={app} />);
    const user = userEvent.setup();
    expect(await screen.findByText("1 tersedia dari 2")).toBeInTheDocument();
    expect(screen.getByText("Terpakai: Run #20 · TC-ALU-001")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Pakai lagi 000090014541"));
    await waitFor(() => expect(mocked.resetTestData).toHaveBeenCalled());
    expect(mocked.resetTestData.mock.calls[0][0]).toBe(1);

    await user.click(screen.getByRole("button", { name: "Tambah data" }));
    await user.type(screen.getByLabelText("Nama data"), "wo id");
    await user.click(screen.getByRole("button", { name: "Simpan data" }));
    expect(screen.getByText(/Huruf, angka, garis bawah/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Nama data"));
    await user.type(screen.getByLabelText("Nama data"), "teknisi");
    await user.type(screen.getByLabelText("Nilai (satu per baris)"), "T-01{enter}T-02");
    await user.click(screen.getByRole("button", { name: "Simpan data" }));
    await waitFor(() => expect(mocked.addTestData).toHaveBeenCalledWith(3, { name: "teknisi", values: "T-01\nT-02" }));
  });
});

describe("Persiapan otomatis", () => {
  it("buat persiapan dan coba jalankan", async () => {
    const hook = {
      id: 9, app_id: 3, name: "Buat WO uji", when: "case" as const, method: "POST" as const, url: "https://dev.test/wo",
      body: "", capture: { wo_id: "data.id" }, active: true, has_headers: true,
    };
    mocked.listHooks.mockResolvedValueOnce([]).mockResolvedValue([hook]);
    mocked.createHook.mockResolvedValue(hook);
    mocked.testHook.mockResolvedValue({ ok: true, message: "Berhasil", captured: { wo_id: "WO-999" } });
    renderWithProviders(<HooksPanel app={app} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Tambah persiapan" }));
    await user.type(screen.getByLabelText("Nama persiapan"), "Buat WO uji");
    await user.type(screen.getByLabelText("URL"), "https://dev.test/wo");
    await user.type(screen.getByLabelText("Header (rahasia)"), "Authorization: Bearer x");
    await user.type(screen.getByLabelText("Simpan dari respons ke Data uji"), "wo_id = data.id");
    await user.click(screen.getByRole("button", { name: "Simpan persiapan" }));
    await waitFor(() => expect(mocked.createHook).toHaveBeenCalled());
    expect(mocked.createHook.mock.calls[0][1]).toMatchObject({ name: "Buat WO uji", when: "case", method: "POST", capture: "wo_id = data.id" });
    await user.click(await screen.findByRole("button", { name: /Coba/ }));
    expect(await screen.findByText(/Berhasil: wo_id = WO-999/)).toBeInTheDocument();
  });
});
