import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { ReportTab } from "./SettingsReport";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return {
    ...mod,
    api: { ...mod.api, reportSettings: vi.fn(), patchReportSettings: vi.fn(), uploadTemplate: vi.fn(), deleteTemplate: vi.fn(), uploadLogo: vi.fn(), deleteLogo: vi.fn() },
  };
});
const mocked = vi.mocked(api);

beforeEach(() => vi.clearAllMocks());

describe("Pengaturan > Laporan", () => {
  it("nama perusahaan disimpan", async () => {
    mocked.reportSettings.mockResolvedValue({ company_name: "", excel_template: null });
    mocked.patchReportSettings.mockResolvedValue({ company_name: "PT Biznet", excel_template: null });
    renderWithProviders(<ReportTab />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Nama perusahaan / instansi"), "PT Biznet");
    await user.click(screen.getByRole("button", { name: "Simpan" }));
    await waitFor(() => expect(mocked.patchReportSettings).toHaveBeenCalledWith({ company_name: "PT Biznet" }));
    expect(screen.getByText(/format standar QA Agent/)).toBeInTheDocument();
  });

  it("unggah template Excel kantor dan tampilkan pemetaan kolom", async () => {
    mocked.reportSettings.mockResolvedValue({ company_name: "", excel_template: null });
    mocked.uploadTemplate.mockResolvedValue({
      company_name: "",
      excel_template: {
        name: "template-kantor.xlsx",
        columns: [
          { header: "No. TC", maps_to: "TC ID" },
          { header: "Kolom Lain", maps_to: null },
        ],
      },
    });
    renderWithProviders(<ReportTab />);
    const user = userEvent.setup();
    const file = new File(["PK"], "template-kantor.xlsx");
    await user.upload(await screen.findByLabelText("File template Excel"), file);
    expect(await screen.findByText("template-kantor.xlsx")).toBeInTheDocument();
    expect(screen.getByText("No. TC")).toBeInTheDocument();
    expect(screen.getByText("TC ID")).toBeInTheDocument();
    expect(screen.getByText("Tidak dikenali, dibiarkan kosong")).toBeInTheDocument();
  });
  it("unggah logo perusahaan dan tampil di pratinjau kepala PDF", async () => {
    mocked.reportSettings.mockResolvedValue({ company_name: "PT Biznet", excel_template: null, logo: null });
    mocked.uploadLogo.mockResolvedValue({
      company_name: "PT Biznet", excel_template: null, logo: { name: "logo-biznet.png", url: "/api/settings/report/logo?v=1" },
    });
    renderWithProviders(<ReportTab />);
    const user = userEvent.setup();
    expect(await screen.findByText("Belum ada logo")).toBeInTheDocument();
    await user.upload(screen.getByLabelText("File logo perusahaan"), new File(["png"], "logo-biznet.png", { type: "image/png" }));
    expect(await screen.findByText("logo-biznet.png")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Logo perusahaan" })).toHaveAttribute("src", "/api/settings/report/logo?v=1");
    expect(screen.getByText("Pratinjau kepala PDF")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Hapus logo/ })).toBeInTheDocument();
  });
});
