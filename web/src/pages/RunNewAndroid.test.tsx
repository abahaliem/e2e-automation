import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { profile, renderWithProviders } from "@/test/render";
import { RunNewPage } from "./RunNew";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listApps: vi.fn(),
      listProfiles: vi.fn(),
      listAccounts: vi.fn(),
      appModules: vi.fn(),
      createApp: vi.fn(),
      createRun: vi.fn(),
      listDevices: vi.fn(),
      devicePackages: vi.fn(),
      installApk: vi.fn(),
      uploadApk: vi.fn(),
    },
  };
});
const mocked = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listProfiles.mockResolvedValue([profile]);
  mocked.listApps.mockResolvedValue([]);
  mocked.listAccounts.mockResolvedValue([]);
  mocked.appModules.mockResolvedValue({ modules: [], explored: false });
  mocked.listDevices.mockResolvedValue({
    devices: [
      { serial: "R58M123", state: "device", model: "SM A546E", emulator: false, android_version: "14" },
      { serial: "ZY22", state: "unauthorized", model: "", emulator: false, android_version: null },
    ],
  });
  mocked.devicePackages.mockResolvedValue({
    packages: ["com.biznet.cmc", "com.demo.app"],
    apps: [
      { package: "com.biznet.cmc", version: "2.1" },
      { package: "com.demo.app", version: "3.8.1" },
    ],
  });
  mocked.createApp.mockImplementation(async (body) => ({
    id: 21, name: body.name, platform: "android", url: body.url, allowed_domains: [], login_endpoints: [],
    default_profile_id: null, explored: false, last_run_at: null, accounts: 0,
  }));
  mocked.createRun.mockResolvedValue({ id: 7 } as never);
});

async function openAndroid() {
  renderWithProviders(<RunNewPage />, { route: "/" });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("radio", { name: /^Android$/ }));
  return user;
}

describe("Run baru: Android (sesuai mockup)", () => {
  it("kartu perangkat, daftar aplikasi dengan versi, lalu run dengan perangkat terpilih", async () => {
    const user = await openAndroid();
    const ready = await screen.findByRole("radio", { name: /SM A546E/ });
    await waitFor(() => expect(ready).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByRole("radio", { name: /Butuh izin/ })).toBeDisabled();
    expect(screen.getByText("Emulator Android")).toBeInTheDocument();
    expect(await screen.findByText("versi 3.8.1")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Cari aplikasi"), "demo");
    expect(screen.queryByRole("radio", { name: /com.biznet.cmc/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /com.demo.app/ }));
    expect(screen.getByRole("radio", { name: /com.demo.app/ })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    await waitFor(() => expect(mocked.createRun).toHaveBeenCalled());
    expect(mocked.createApp.mock.calls[0][0]).toMatchObject({ name: "com.demo.app", platform: "android", url: "android://com.demo.app" });
    expect(mocked.createRun.mock.calls[0][0]).toMatchObject({ app_id: 21, mode: "explore", device_serial: "R58M123" });
  });

  it("panel Layar HP menampilkan pratinjau perangkat terpilih", async () => {
    await openAndroid();
    const img = await screen.findByAltText(/Layar SM A546E/);
    expect(img.getAttribute("src")).toContain("/api/devices/R58M123/screen");
  });

  it("upload APK (mockup 02b): kartu file, info versi terpasang, opsi, dipasang saat run", async () => {
    mocked.uploadApk.mockResolvedValue({
      file: "20261109-1200_hr-mobile-3.9.0-debug.apk", package: "com.demo.app", version: "3.9.0", version_code: 39,
      size_bytes: 50_540_000, installed_version: "3.8.1",
    });
    const user = await openAndroid();
    await waitFor(() => expect(screen.getByRole("radio", { name: /SM A546E/ })).toHaveAttribute("aria-checked", "true"));
    await user.click(screen.getByRole("radio", { name: /Upload APK/ }));
    const file = new File(["PK"], "hr-mobile-3.9.0-debug.apk", { type: "application/vnd.android.package-archive" });
    await user.upload(screen.getByLabelText("File APK"), file);
    await waitFor(() => expect(mocked.uploadApk).toHaveBeenCalledWith("R58M123", file));
    expect(await screen.findByText("hr-mobile-3.9.0-debug.apk")).toBeInTheDocument();
    expect(screen.getByText("Siap di-install")).toBeInTheDocument();
    expect(screen.getByText(/versi 3.9.0, 48,2 MB/)).toBeInTheDocument();
    expect(screen.getByText(/sudah punya com.demo.app versi 3.8.1/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Beri semua izin/ })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: /Hapus aplikasi setelah run/ }));
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    await waitFor(() => expect(mocked.createRun).toHaveBeenCalled());
    expect(mocked.createApp.mock.calls[0][0]).toMatchObject({ url: "android://com.demo.app" });
    expect(mocked.createRun.mock.calls[0][0]).toMatchObject({
      apk_file: "20261109-1200_hr-mobile-3.9.0-debug.apk", apk_grant: true, apk_uninstall: true, device_serial: "R58M123",
    });
    expect(mocked.installApk).not.toHaveBeenCalled();
  });

  it("baris bawah sesuai mockup: Profil AI, Yang diuji, Akun test", async () => {
    await openAndroid();
    expect(await screen.findByLabelText("Profil AI")).toBeInTheDocument();
    expect(screen.getByLabelText("Yang diuji")).toHaveValue("explore");
    expect(screen.getByLabelText("Akun test")).toBeInTheDocument();
  });
  it("tanpa perangkat: petunjuk dan tombol run nonaktif", async () => {
    mocked.listDevices.mockResolvedValue({ devices: [] });
    await openAndroid();
    expect(await screen.findByText(/Belum ada HP yang tersambung/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Mulai run/ })).toBeDisabled();
  });
});

describe("Simpan aplikasi", () => {
  it("menyimpan aplikasi Android lalu membuka halaman Aplikasi untuk mengisi akun test", async () => {
    const user = await openAndroid();
    await user.click(await screen.findByRole("radio", { name: /com.demo.app/ }));
    expect(screen.getByText(/belum punya akun test/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Simpan aplikasi/ }));
    await waitFor(() => expect(mocked.createApp).toHaveBeenCalled());
    expect(mocked.createApp.mock.calls[0][0]).toMatchObject({ platform: "android", url: "android://com.demo.app" });
    expect(await screen.findByTestId("navigated")).toBeInTheDocument();
    expect(mocked.createRun).not.toHaveBeenCalled();
  });
});
