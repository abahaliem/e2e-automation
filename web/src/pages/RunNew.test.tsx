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
      getRun: vi.fn(),
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
    expect(await screen.findByText("Web HR belum dipetakan. Jalankan Seluruh aplikasi dulu untuk memetakan modul")).toBeInTheDocument();
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
      device_serial: null,
    });
    expect(await screen.findByTestId("navigated")).toBeInTheDocument();
  });

  it("Review test case dulu ikut terkirim untuk Satu modul", async () => {
    mocked.listApps.mockResolvedValue([app]);
    mocked.appModules.mockResolvedValue({ modules: ["Pengguna"], explored: true });
    mocked.createRun.mockResolvedValue({ id: 43 } as never);
    renderWithProviders(<RunNewPage />, { path: "/runs/new?app=3", route: "/runs/new" });
    const user = userEvent.setup();
    expect(screen.queryByRole("switch", { name: /Review test case dulu/ })).not.toBeInTheDocument(); // hanya Satu modul
    const card = await screen.findByRole("radio", { name: /Satu modul/ });
    await waitFor(() => expect(card).toBeEnabled());
    await user.click(card);
    await user.selectOptions(await screen.findByLabelText("Modul"), "Pengguna");
    await user.click(screen.getByRole("switch", { name: /Review test case dulu/ }));
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    await waitFor(() => expect(mocked.createRun).toHaveBeenCalled());
    expect(mocked.createRun.mock.calls[0][0]).toMatchObject({ mode: "deep", module: "Pengguna", review_first: true });
  });

  it("?reuse= memakai test case run sebelumnya (regresi) dan memilih modulnya", async () => {
    mocked.listApps.mockResolvedValue([app]);
    mocked.appModules.mockResolvedValue({ modules: ["Dashboard", "Pengguna"], explored: true });
    mocked.getRun.mockResolvedValue({ id: 9, app_id: 3, module: "Pengguna" } as never);
    mocked.createRun.mockResolvedValue({ id: 44 } as never);
    renderWithProviders(<RunNewPage />, { path: "/runs/new?app=3&reuse=9", route: "/runs/new" });
    const user = userEvent.setup();
    expect(await screen.findByText(/Memakai test case yang sama dengan run #9/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Modul")).toHaveValue("Pengguna"));
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    await waitFor(() => expect(mocked.createRun).toHaveBeenCalled());
    expect(mocked.createRun.mock.calls[0][0]).toMatchObject({ mode: "deep", module: "Pengguna", reuse_cases_from: 9 });
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

  it("PRD selalu tampil (mockup 01) dan ikut dikirim saat run Seluruh aplikasi", async () => {
    mocked.listApps.mockResolvedValue([app]);
    mocked.appModules.mockResolvedValue({ modules: [], explored: false });
    mocked.createRun.mockResolvedValue({ id: 3 } as never);
    renderWithProviders(<RunNewPage />, { path: "/runs/new?app=3", route: "/runs/new" });
    const user = userEvent.setup();
    const input = await screen.findByLabelText("File PRD");
    await user.upload(input, new File(["# PRD\nEmail wajib valid"], "prd-pengguna.md", { type: "text/markdown" }));
    expect(await screen.findByText("prd-pengguna.md")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    await waitFor(() => expect(mocked.createRun).toHaveBeenCalled());
    expect(mocked.createRun.mock.calls[0][0]).toMatchObject({ mode: "explore", prd_text: "# PRD\nEmail wajib valid" });
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


describe("Hasil penjelajahan", () => {
  it("Run baru ?module= memilih modul dari hasil penjelajahan", async () => {
    mocked.listApps.mockResolvedValue([app]);
    mocked.appModules.mockResolvedValue({ modules: ["Dashboard", "Pengguna"], explored: true });
    renderWithProviders(<RunNewPage />, { path: "/runs/new?app=3&module=Pengguna", route: "/runs/new" });
    await waitFor(() => expect(screen.getByLabelText("Modul")).toHaveValue("Pengguna"));
  });
});

describe("Alur bisnis di Run baru", () => {
  it("alur muncul di pilihan modul dan bisa dipilih lewat ?module=", async () => {
    mocked.listApps.mockResolvedValue([app]);
    mocked.appModules.mockResolvedValue({ modules: ["Pengguna"], explored: true, flows: [{ id: 5, name: "Alur tambah pengguna" }] });
    mocked.createRun.mockResolvedValue({ id: 50 } as never);
    renderWithProviders(<RunNewPage />, { path: "/runs/new?app=3&module=Alur%20tambah%20pengguna", route: "/runs/new" });
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByLabelText("Modul")).toHaveValue("Alur tambah pengguna"));
    expect(screen.getByRole("option", { name: "Alur: Alur tambah pengguna" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Mulai run/ }));
    await waitFor(() => expect(mocked.createRun).toHaveBeenCalled());
    expect(mocked.createRun.mock.calls[0][0]).toMatchObject({ mode: "deep", module: "Alur tambah pengguna" });
  });
});