import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { cases, detail, run } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { RunResultPage, bugReportText } from "./RunResult";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, getRun: vi.fn(), listCases: vi.fn(), caseDetail: vi.fn(), patchCase: vi.fn() } };
});
const mocked = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getRun.mockResolvedValue(run);
  mocked.listCases.mockResolvedValue(cases);
  mocked.caseDetail.mockResolvedValue(detail);
});

const open = () => renderWithProviders(<RunResultPage />, { path: "/runs/9/result", route: "/runs/:runId/result" });

describe("Hasil Run", () => {
  it("filter Semua / Temuan / Belum direview", async () => {
    open();
    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    await within(table).findByText("Tambah pengguna valid");
    await user.click(screen.getByRole("button", { name: /Temuan 2/ }));
    expect(within(table).queryByText("Tambah pengguna valid")).not.toBeInTheDocument();
    expect(within(table).getByText("Validasi format email")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Belum direview 1/ }));
    expect(within(table).queryByText("Nama dengan apostrof")).not.toBeInTheDocument();
    expect(within(table).getByText("Validasi format email")).toBeInTheDocument();
  });

  it("panel detail menampilkan expected, actual, bukti teknis, dan evidence", async () => {
    open();
    const user = userEvent.setup();
    await user.click(await within(await screen.findByRole("table")).findByText("Nama dengan apostrof"));
    const panel = await screen.findByRole("region", { name: "Detail test case" });
    expect(await within(panel).findByText("Pengguna O'Brien tersimpan")).toBeInTheDocument();
    expect(within(panel).getByText("Internal Server Error")).toBeInTheDocument();
    expect(within(panel).getByText("HTTP 500 POST http://hr-dev.kantor.local/users")).toBeInTheDocument();
    expect(within(panel).getAllByRole("img").length).toBe(3);
  });

  it("ubah Status Final memanggil PATCH dan menampilkan peringatan Excel terkunci", async () => {
    mocked.patchCase.mockResolvedValue({ case: { ...cases[2], status_final: "Pass", effective_status: "Pass" }, warning: "Tutup report.xlsx di Excel supaya laporan bisa diperbarui." });
    open();
    const user = userEvent.setup();
    await user.click(await within(await screen.findByRole("table")).findByText("Nama dengan apostrof"));
    const panel = await screen.findByRole("region", { name: "Detail test case" });
    await within(panel).findByText("Pengguna O'Brien tersimpan");
    await user.selectOptions(within(panel).getByLabelText("Status final"), "Pass");
    await user.type(within(panel).getByLabelText("Catatan reviewer"), "Sudah diperbaiki");
    await user.click(within(panel).getByRole("button", { name: /Simpan review/ }));
    await waitFor(() => expect(mocked.patchCase).toHaveBeenCalled());
    expect(mocked.patchCase.mock.calls[0]).toEqual([9, "TC-PEN-003", { status_final: "Pass", severity: "Major", reviewer_note: "Sudah diperbaiki" }]);
    expect(await screen.findByText(/Tutup report.xlsx/)).toBeInTheDocument();
  });

  it("tombol unduh menunjuk endpoint download", async () => {
    open();
    expect(await screen.findByRole("link", { name: /Excel/ })).toHaveAttribute("href", "/api/runs/9/download/xlsx");
    expect(screen.getByRole("link", { name: /HTML/ })).toHaveAttribute("href", "/api/runs/9/download/html");
    expect(screen.getByRole("link", { name: /Laporan PDF/ })).toHaveAttribute("href", "/api/runs/9/download/pdf");
  });

  it("salin laporan bug berisi langkah reproduksi", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    open();
    const user = userEvent.setup(); // userEvent memasang clipboard tiruan; timpa sesudahnya
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await user.click(await within(await screen.findByRole("table")).findByText("Nama dengan apostrof"));
    const panel = await screen.findByRole("region", { name: "Detail test case" });
    await within(panel).findByText("Pengguna O'Brien tersimpan");
    await user.click(within(panel).getByRole("button", { name: /Salin sebagai laporan bug/ }));
    expect(writeText).toHaveBeenCalled();
    const text = writeText.mock.calls[0][0] as string;
    expect(text).toContain("Langkah reproduksi");
    expect(text).toContain("1. Isi field 'Nama' dengan 'O'Brien'");
    expect(text).not.toContain("Verifikasi hasil akhir");
    expect(await screen.findByText("Disalin")).toBeInTheDocument();
  });

  it("bugReportText memakai status efektif dan bukti teknis", () => {
    const text = bugReportText(detail, run);
    expect(text).toContain("[TC-PEN-003] Nama dengan apostrof");
    expect(text).toContain("Status: Fail (Major)");
    expect(text).toContain("HTTP 500 POST");
  });
});
