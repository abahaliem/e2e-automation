import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { DevicesPage } from "./Devices";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, listDevices: vi.fn(), devicePackages: vi.fn(), connectDevice: vi.fn() } };
});
const mocked = vi.mocked(api);

beforeEach(() => vi.clearAllMocks());

describe("Halaman Perangkat", () => {
  it("menampilkan HP siap dan HP yang belum diizinkan", async () => {
    mocked.listDevices.mockResolvedValue({
      devices: [
        { serial: "R58M123", state: "device", model: "SM A546E", emulator: false, android_version: "14" },
        { serial: "ZY22", state: "unauthorized", model: "", emulator: false, android_version: null },
        { serial: "emulator-5554", state: "device", model: "sdk gphone64", emulator: true, android_version: "15" },
      ],
    });
    renderWithProviders(<DevicesPage />);
    expect(await screen.findByText("SM A546E")).toBeInTheDocument();
    expect(screen.getByText("Android 14")).toBeInTheDocument();
    expect(screen.getByText(/Izinkan USB debugging/)).toBeInTheDocument();
    expect(screen.getByText("Emulator")).toBeInTheDocument();
  });

  it("belum ada perangkat: petunjuk mengaktifkan USB debugging", async () => {
    mocked.listDevices.mockResolvedValue({ devices: [] });
    renderWithProviders(<DevicesPage />);
    expect(await screen.findByText("Belum ada HP yang tersambung")).toBeInTheDocument();
    expect(screen.getByText(/Opsi pengembang/)).toBeInTheDocument();
  });

  it("sambungkan HP lewat jaringan dengan kode pairing", async () => {
    mocked.listDevices.mockResolvedValue({ devices: [] });
    mocked.connectDevice.mockResolvedValue({ address: "192.168.1.20:5555", message: "connected to 192.168.1.20:5555" });
    renderWithProviders(<DevicesPage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Alamat HP (IP:port)"), "192.168.1.20:5555");
    await user.click(screen.getByLabelText(/Pasangkan dulu dengan kode pairing/));
    await user.type(screen.getByLabelText("Alamat pairing (IP:port)"), "192.168.1.20:37001");
    await user.type(screen.getByLabelText("Kode pairing"), "123456");
    await user.click(screen.getByRole("button", { name: "Sambungkan" }));
    expect(mocked.connectDevice).toHaveBeenCalledWith({
      address: "192.168.1.20:5555", pair_address: "192.168.1.20:37001", pair_code: "123456",
    });
    expect(await screen.findByText(/Tersambung: connected to 192.168.1.20:5555/)).toBeInTheDocument();
  });

  it("adb belum terpasang", async () => {
    mocked.listDevices.mockRejectedValue(new ApiError(503, "adb (Android platform-tools) belum terpasang di laptop ini."));
    renderWithProviders(<DevicesPage />);
    expect(await screen.findByText(/platform-tools\) belum terpasang/)).toBeInTheDocument();
  });
});
