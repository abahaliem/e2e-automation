import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { app, renderWithProviders } from "@/test/render";
import { AppsPage } from "./Apps";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return {
    ...mod,
    api: {
      listApps: vi.fn(),
      createApp: vi.fn(),
      updateApp: vi.fn(),
      deleteApp: vi.fn(),
      listAccounts: vi.fn(),
      createAccount: vi.fn(),
      updateAccountPassword: vi.fn(),
      deleteAccount: vi.fn(),
      importRuns: vi.fn(),
    },
  };
});

const mocked = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Halaman Aplikasi", () => {
  it("validasi URL dan mengirim domain sebagai daftar", async () => {
    mocked.listApps.mockResolvedValue([]);
    mocked.createApp.mockResolvedValue(app);
    mocked.listAccounts.mockResolvedValue([]);
    renderWithProviders(<AppsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Tambah aplikasi/ }));
    await user.type(screen.getByLabelText("Nama aplikasi"), "Web HR");
    await user.type(screen.getByLabelText("URL aplikasi"), "hr-dev.kantor.local");
    await user.click(screen.getByRole("button", { name: /Simpan aplikasi/ }));
    expect(await screen.findByText("URL harus diawali http:// atau https://")).toBeInTheDocument();
    expect(mocked.createApp).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("URL aplikasi"));
    await user.type(screen.getByLabelText("URL aplikasi"), "http://hr-dev.kantor.local");
    await user.type(screen.getByLabelText("Domain yang boleh dibuka"), "hr-dev.kantor.local, sso.kantor.local");
    await user.click(screen.getByRole("button", { name: /Simpan aplikasi/ }));
    await waitFor(() => expect(mocked.createApp).toHaveBeenCalled());
    expect(mocked.createApp.mock.calls[0][0]).toMatchObject({
      name: "Web HR",
      url: "http://hr-dev.kantor.local",
      allowed_domains: ["hr-dev.kantor.local", "sso.kantor.local"],
    });
  });

  it("akun test: password tidak pernah diisi ulang dari server", async () => {
    mocked.listApps.mockResolvedValue([app]);
    mocked.listAccounts.mockResolvedValue([{ id: 7, app_id: 3, role: "admin", username: "qa@kantor.local", has_password: true }]);
    mocked.createAccount.mockResolvedValue({ id: 8, app_id: 3, role: "staf", username: "staf@kantor.local", has_password: true });
    renderWithProviders(<AppsPage />);
    const user = userEvent.setup();
    const row = await screen.findByText("qa@kantor.local");
    const item = row.closest("li")!;
    expect(within(item).getByText("Password tersimpan")).toBeInTheDocument();
    expect(item.textContent).not.toContain("••••••••");
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    expect(password.value).toBe("");
    expect(password.type).toBe("password");
    await user.type(screen.getByLabelText("Peran"), "staf");
    await user.type(screen.getByLabelText("Username / email"), "staf@kantor.local");
    await user.type(password, "rahasia!");
    await user.click(screen.getByRole("button", { name: /Tambah akun/ }));
    await waitFor(() => expect(mocked.createAccount).toHaveBeenCalledWith(3, { role: "staf", username: "staf@kantor.local", password: "rahasia!" }));
    await waitFor(() => expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe(""));
  });

  it("aplikasi Android: paket divalidasi, tanpa isian domain web", async () => {
    const androidApp = { ...app, id: 9, name: "CMC Mobile", platform: "android" as const, url: "android://com.biznet.cmc" };
    mocked.listApps.mockResolvedValue([androidApp]);
    mocked.listAccounts.mockResolvedValue([]);
    mocked.updateApp.mockResolvedValue(androidApp);
    renderWithProviders(<AppsPage />);
    const user = userEvent.setup();
    const pkg = await screen.findByLabelText("Paket aplikasi Android");
    expect(screen.queryByLabelText("Domain yang boleh dibuka")).not.toBeInTheDocument();
    await user.clear(pkg);
    await user.type(pkg, "https://salah.test");
    await user.click(screen.getByRole("button", { name: /Simpan aplikasi/ }));
    expect(await screen.findByText(/Paket aplikasi Android tidak valid/)).toBeInTheDocument();
    await user.clear(pkg);
    await user.type(pkg, "android://com.biznet.cmc");
    await user.click(screen.getByRole("button", { name: /Simpan aplikasi/ }));
    await waitFor(() => expect(mocked.updateApp).toHaveBeenCalled());
  });

  it("state kosong", async () => {
    mocked.listApps.mockResolvedValue([]);
    renderWithProviders(<AppsPage />);
    expect(await screen.findByText("Belum ada aplikasi")).toBeInTheDocument();
  });
});

describe("Aplikasi dari tautan", () => {
  it("?app= memilih aplikasi tersebut", async () => {
    const second = { ...app, id: 9, name: "WFM Dev", platform: "android" as const, url: "android://com.biznet.wfm.dev" };
    mocked.listApps.mockResolvedValue([app, second]);
    mocked.listAccounts.mockResolvedValue([]);
    renderWithProviders(<AppsPage />, { path: "/apps?app=9" });
    expect(await screen.findByDisplayValue("android://com.biznet.wfm.dev")).toBeInTheDocument();
  });
});
