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
      listApps: vi.fn(),
      listProfiles: vi.fn(),
      listAccounts: vi.fn(),
      appModules: vi.fn(),
      createApp: vi.fn(),
      createRun: vi.fn(),
      listDevices: vi.fn(),
      devicePackages: vi.fn(),
      installApk: vi.fn(),
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
  mocked.devicePackages.mockResolvedValue({ packages: ["com.biznet.cmc", "com.demo.app"] });
  mocked.createApp.mockImplementation(async (body) => ({
    id: 21, name: body.name, platform: "android", url: body.url, allowed_domains: [], login_endpoints: [],
    default_profile_id: null, explored: false, last_run_at: null, accounts: 0,
  }));
  mocked.createRun.mockResolvedValue({ id: 7 } as never);
});

async function openAndroid() {
  renderWithProviders(<RunNewPage />, { route: "/" });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("radio", { name: /Android/ }));
  return user;
}

describe("Run baru: Android", () => {
  it("aplikasi terpasang: membuat aplikasi android dan run dengan perangkat", async () => {
    const user = await openAndroid();
    const device = await screen.findByLabelText("Perangkat");
    await waitFor(() => expect(device).toHaveValue("R58M123"));
    expect(screen.getByRole("option", { name: /ZY22/ })).toBeDisabled();
    const pkg = await screen.findByLabelText("Aplikasi di HP");
    await waitFor(() => expect(screen.getByRole("option", { name: "com.demo.app" })).toBeInTheDocument());
    await user.selectOptions(pkg, "com.demo.app");
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    await waitFor(() => expect(mocked.createRun).toHaveBeenCalled());
    expect(mocked.createApp.mock.calls[0][0]).toMatchObject({ name: "com.demo.app", platform: "android", url: "android://com.demo.app" });
    expect(mocked.createRun.mock.calls[0][0]).toMatchObject({ app_id: 21, mode: "explore", device_serial: "R58M123" });
  });

  it("upload APK memasang lalu memilih paketnya", async () => {
    mocked.installApk.mockResolvedValue({ package: "com.baru.app", packages: ["com.baru.app", "com.demo.app"], message: "", file: "x.apk" });
    const user = await openAndroid();
    await waitFor(() => expect(screen.getByLabelText("Perangkat")).toHaveValue("R58M123"));
    await user.click(screen.getByRole("radio", { name: /Upload APK/ }));
    const file = new File(["PK"], "Demo.apk", { type: "application/vnd.android.package-archive" });
    await user.upload(screen.getByLabelText("File APK"), file);
    await waitFor(() => expect(mocked.installApk).toHaveBeenCalledWith("R58M123", file));
    expect(await screen.findByText(/com.baru.app terpasang/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    await waitFor(() => expect(mocked.createRun).toHaveBeenCalled());
    expect(mocked.createApp.mock.calls[0][0]).toMatchObject({ url: "android://com.baru.app" });
  });

  it("tanpa perangkat siap: tombol run nonaktif dengan petunjuk", async () => {
    mocked.listDevices.mockResolvedValue({ devices: [] });
    await openAndroid();
    expect(await screen.findByText(/Belum ada HP yang tersambung/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Mulai run/ })).toBeDisabled();
  });
});
