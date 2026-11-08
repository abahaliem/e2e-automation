import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { app, profile, renderWithProviders } from "@/test/render";
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
    },
  };
});

const mocked = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listProfiles.mockResolvedValue([profile]);
  mocked.listAccounts.mockResolvedValue([{ id: 7, app_id: 3, role: "admin", username: "qa.admin", has_password: true }]);
});

describe("Run baru", () => {
  it("Satu modul nonaktif dengan petunjuk bila aplikasi belum di-explore", async () => {
    mocked.listApps.mockResolvedValue([{ ...app, explored: false }]);
    mocked.appModules.mockResolvedValue({ modules: [], explored: false });
    renderWithProviders(<RunNewPage />, { path: "/runs/new?app=3" });
    const card = await screen.findByRole("radio", { name: /Satu modul/ });
    await waitFor(() => expect(card).toBeDisabled());
    expect(screen.getByText("Jalankan Seluruh aplikasi dulu untuk memetakan modul")).toBeInTheDocument();
  });

  it("mengirim body run sesuai API dan pindah ke layar live", async () => {
    mocked.listApps.mockResolvedValue([app]);
    mocked.appModules.mockResolvedValue({ modules: ["Dashboard", "Pengguna"], explored: true });
    mocked.createRun.mockResolvedValue({ id: 42 } as never);
    renderWithProviders(<RunNewPage />, { path: "/runs/new?app=3", route: "/runs/new" });
    const user = userEvent.setup();
    const card = await screen.findByRole("radio", { name: /Satu modul/ });
    await waitFor(() => expect(card).toBeEnabled());
    await user.click(card);
    await user.selectOptions(await screen.findByLabelText("Modul"), "Pengguna");
    await user.click(screen.getByRole("switch", { name: /Konfirmasi tiap langkah/ }));
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    await waitFor(() => expect(mocked.createRun).toHaveBeenCalled());
    expect(mocked.createRun.mock.calls[0][0]).toEqual({
      app_id: 3,
      mode: "deep",
      module: "Pengguna",
      prd_text: null,
      profile_id: 1,
      account_id: 7,
      environment: "dev",
      confirm_each_step: true,
    });
    expect(await screen.findByTestId("navigated")).toBeInTheDocument();
  });

  it("URL baru dibuat sebagai aplikasi sebelum run", async () => {
    mocked.listApps.mockResolvedValue([]);
    mocked.createApp.mockResolvedValue({ ...app, id: 11, explored: false });
    mocked.createRun.mockResolvedValue({ id: 5 } as never);
    renderWithProviders(<RunNewPage />, { route: "/" });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("URL aplikasi"), "https://portal.kantor.local");
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    await waitFor(() => expect(mocked.createApp).toHaveBeenCalled());
    expect(mocked.createApp.mock.calls[0][0]).toMatchObject({ name: "portal.kantor.local", url: "https://portal.kantor.local" });
    await waitFor(() => expect(mocked.createRun).toHaveBeenCalled());
    expect(mocked.createRun.mock.calls[0][0]).toMatchObject({ app_id: 11, mode: "explore" });
  });

  it("URL tidak valid ditolak", async () => {
    mocked.listApps.mockResolvedValue([]);
    renderWithProviders(<RunNewPage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("URL aplikasi"), "portal");
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    expect(await screen.findByText("URL harus diawali http:// atau https://")).toBeInTheDocument();
    expect(mocked.createRun).not.toHaveBeenCalled();
  });
});
