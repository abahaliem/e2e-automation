import { screen, waitFor } from "@testing-library/react";
import { api } from "@/lib/api";
import { app, profile, renderWithProviders } from "@/test/render";
import { GuidePage } from "./Guide";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, listProfiles: vi.fn(), listApps: vi.fn(), listRuns: vi.fn() } };
});
const mocked = vi.mocked(api);
beforeEach(() => vi.clearAllMocks());

describe("Panduan", () => {
  it("pengguna baru: langkah berikutnya Atur Model AI", async () => {
    mocked.listProfiles.mockResolvedValue([]);
    mocked.listApps.mockResolvedValue([]);
    mocked.listRuns.mockResolvedValue([]);
    renderWithProviders(<GuidePage />);
    const first = (await screen.findByRole("heading", { name: "Atur Model AI" })).closest("li")!;
    await waitFor(() => expect(first).toHaveTextContent("Langkah berikutnya"));
    expect(screen.getByRole("link", { name: /Buka Pengaturan, Model AI/ })).toHaveAttribute("href", "/settings");
  });

  it("aplikasi belum dipetakan: langkah berikutnya Petakan aplikasi", async () => {
    mocked.listProfiles.mockResolvedValue([profile]);
    mocked.listApps.mockResolvedValue([{ ...app, explored: false }]);
    mocked.listRuns.mockResolvedValue([]);
    renderWithProviders(<GuidePage />);
    expect(await screen.findAllByLabelText("Sudah")).toHaveLength(2);
    const step = screen.getByRole("heading", { name: "Petakan aplikasi (Seluruh aplikasi)" }).closest("li")!;
    expect(step).toHaveTextContent("Langkah berikutnya");
    expect(screen.getByText("Pilihan Satu modul tidak bisa dipilih")).toBeInTheDocument();
  });
});
