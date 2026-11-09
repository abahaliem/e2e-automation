import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import type { PlanResponse } from "@/lib/types";
import { renderWithProviders } from "@/test/render";
import { RunReviewPage } from "./RunReview";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, getRun: vi.fn(), getPlan: vi.fn(), savePlan: vi.fn(), resumeRun: vi.fn() } };
});
const mocked = vi.mocked(api);
beforeEach(() => vi.clearAllMocks());

const SIGNIN = "android://com.biznet.wfm.dev/MainActivity#7e6aae0a";
const LEMBUR = "android://com.biznet.wfm.dev/MainActivity#8825073c";
const tc = (id: string, title: string, start = SIGNIN) => ({
  id, title, page: "Sign In", type: "positif" as const, priority: "High" as const, precondition: "", test_data: "",
  steps: ["Isi username", "Tap Sign In"], expected: "Masuk", start_url: start,
});
const plan: PlanResponse = {
  editable: true,
  module: "Autentikasi",
  cases: [tc("TC-AUT-001", "Sign In valid"), tc("TC-AUT-002", "Submit reason lembur", LEMBUR)],
  screens: [
    { url: SIGNIN, page_name: "Sign In" },
    { url: LEMBUR, page_name: "Form Reason Lembur" },
  ],
};

function setup() {
  mocked.getRun.mockResolvedValue({ id: 20, app_name: "WFM", module: "Autentikasi" } as never);
  mocked.getPlan.mockResolvedValue(plan);
  return renderWithProviders(<RunReviewPage />, { path: "/runs/20/review", route: "/runs/:runId/review" });
}

describe("Review test case", () => {
  it("hapus, edit, tambah, lalu simpan & jalankan", async () => {
    mocked.savePlan.mockResolvedValue(plan);
    mocked.resumeRun.mockResolvedValue({} as never);
    setup();
    const user = userEvent.setup();
    expect(await screen.findByDisplayValue("Submit reason lembur")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Hapus test case 2"));
    expect(screen.queryByDisplayValue("Submit reason lembur")).not.toBeInTheDocument();

    const title = screen.getByLabelText("Skenario");
    await user.clear(title);
    await user.type(title, "Sign In dengan akun tersimpan");
    await user.click(screen.getByRole("button", { name: "Tambah test case" }));
    const cards = screen.getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    // test case baru masih kosong → ditolak dengan pesan jelas
    await user.click(screen.getByRole("button", { name: /Simpan & jalankan 2 test case/ }));
    expect(screen.getByText(/Test case ke-2: judul, langkah, dan expected result wajib diisi/)).toBeInTheDocument();
    expect(mocked.savePlan).not.toHaveBeenCalled();

    const fresh = within(cards[1]);
    await user.type(fresh.getByLabelText("Skenario"), "Toggle lihat password");
    await user.type(fresh.getByLabelText("Langkah (satu per baris)"), "Tap ikon mata{enter}Lihat field password");
    await user.type(fresh.getByLabelText("Expected result"), "Password terlihat");
    await user.click(screen.getByRole("button", { name: /Simpan & jalankan 2 test case/ }));
    await waitFor(() => expect(mocked.resumeRun).toHaveBeenCalledWith(20));
    const [, sent] = mocked.savePlan.mock.calls[0];
    expect(sent.map((c) => c.title)).toEqual(["Sign In dengan akun tersimpan", "Toggle lihat password"]);
    expect(sent[0].id).toBe("TC-AUT-001");
    expect(sent[1]).toMatchObject({ steps: ["Tap ikon mata", "Lihat field password"], start_url: SIGNIN, page: "Sign In" });
  });

  it("run yang sudah dijalankan hanya bisa dilihat", async () => {
    mocked.getRun.mockResolvedValue({ id: 20, app_name: "WFM", module: "Autentikasi" } as never);
    mocked.getPlan.mockResolvedValue({ ...plan, editable: false });
    renderWithProviders(<RunReviewPage />, { path: "/runs/20/review", route: "/runs/:runId/review" });
    expect(await screen.findByText(/tidak bisa diubah lagi/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Simpan & jalankan/ })).not.toBeInTheDocument();
    expect(screen.getAllByLabelText("Skenario")[0]).toBeDisabled();
  });
});
