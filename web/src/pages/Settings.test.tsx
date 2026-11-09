import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { profile, renderWithProviders } from "@/test/render";
import { SettingsPage } from "./Settings";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return {
    ...mod,
    api: {
      listProfiles: vi.fn(),
      createProfile: vi.fn(),
      updateProfile: vi.fn(),
      deleteProfile: vi.fn(),
      listModels: vi.fn(),
      testProfile: vi.fn(),
      listApps: vi.fn().mockResolvedValue([]),
      listAccounts: vi.fn().mockResolvedValue([]),
    },
  };
});

const mocked = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listApps.mockResolvedValue([]);
});

describe("Pengaturan > Model AI", () => {
  it("base URL wajib untuk OpenAI-compatible (validasi sebelum kirim)", async () => {
    mocked.listProfiles.mockResolvedValue([]);
    renderWithProviders(<SettingsPage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Nama profil"), "GPT");
    await user.type(screen.getByLabelText("Model"), "gpt-4.1-mini");
    await user.click(screen.getByRole("button", { name: /Simpan/ }));
    expect(await screen.findByText("Base URL wajib diisi untuk endpoint OpenAI-compatible")).toBeInTheDocument();
    expect(mocked.createProfile).not.toHaveBeenCalled();
  });

  it("Anthropic tidak butuh base URL dan field disembunyikan", async () => {
    mocked.listProfiles.mockResolvedValue([]);
    mocked.createProfile.mockResolvedValue({ ...profile, id: 9, provider: "anthropic" });
    renderWithProviders(<SettingsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("radio", { name: "Anthropic (Claude)" }));
    expect(screen.queryByLabelText("Base URL endpoint")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Nama profil"), "Claude");
    await user.type(screen.getByLabelText("Model"), "claude-sonnet-5-5");
    await user.type(screen.getByLabelText("API key"), "sk-ant-123");
    await user.click(screen.getByRole("button", { name: /Simpan/ }));
    await waitFor(() => expect(mocked.createProfile).toHaveBeenCalled());
    expect(mocked.createProfile.mock.calls[0][0]).toMatchObject({ provider: "anthropic", api_key: "sk-ant-123" });
  });

  it("API key tersamar, tombol Ganti membuka input kosong", async () => {
    mocked.listProfiles.mockResolvedValue([profile]);
    renderWithProviders(<SettingsPage />);
    const user = userEvent.setup();
    expect(await screen.findByText("sk-••••3f9a")).toBeInTheDocument();
    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ganti" }));
    const input = screen.getByLabelText("API key") as HTMLInputElement;
    expect(input.value).toBe("");
    expect(input.type).toBe("password");
  });

  it("server 422 ditampilkan di bawah field", async () => {
    mocked.listProfiles.mockResolvedValue([profile]);
    const { ApiError } = await import("@/lib/api");
    mocked.updateProfile.mockRejectedValue(new ApiError(422, "Periksa", { model: "Wajib diisi" }));
    renderWithProviders(<SettingsPage />);
    const user = userEvent.setup();
    await screen.findByText("sk-••••3f9a");
    await user.click(screen.getByRole("button", { name: /Simpan/ }));
    expect(await screen.findByText("Wajib diisi")).toBeInTheDocument();
  });

  it("Tes koneksi menampilkan hasil sukses dan gagal", async () => {
    mocked.listProfiles.mockResolvedValue([profile]);
    mocked.testProfile.mockResolvedValueOnce({ text_ok: true, vision_ok: true, latency_ms: 1400, message: "Koneksi berhasil" });
    mocked.testProfile.mockResolvedValueOnce({ text_ok: false, vision_ok: false, latency_ms: 30, message: "Gagal: 401" });
    renderWithProviders(<SettingsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Tes koneksi/ }));
    expect(await screen.findByText("Terhubung")).toBeInTheDocument();
    expect(screen.getByText(/Teks OK dan gambar OK/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Tes koneksi/ }));
    expect(await screen.findByText("Tidak terhubung")).toBeInTheDocument();
    expect(screen.getByText("Gagal: 401")).toBeInTheDocument();
  });

  it("Ambil daftar model mengisi pilihan", async () => {
    mocked.listProfiles.mockResolvedValue([profile]);
    mocked.listModels.mockResolvedValue({ models: ["deepseek/deepseek-v4-flash", "z-ai/glm-5.3-flash"], message: "" });
    renderWithProviders(<SettingsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Ambil daftar model/ }));
    const option = await screen.findByRole("button", { name: "deepseek/deepseek-v4-flash" });
    await user.click(option);
    expect((screen.getByLabelText("Model") as HTMLInputElement).value).toBe("deepseek/deepseek-v4-flash");
  });

  it("lima tab sesuai mockup 04", async () => {
    mocked.listProfiles.mockResolvedValue([]);
    renderWithProviders(<SettingsPage />);
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Model AI", "Skill QA", "Akun test", "Keamanan", "Laporan"]);
    expect(tabs.every((t) => !(t as HTMLButtonElement).disabled)).toBe(true);
  });});
