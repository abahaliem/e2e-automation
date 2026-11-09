import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import type { AuthStatus } from "@/lib/types";
import { renderWithProviders } from "@/test/render";
import { SecurityTab } from "./SettingsSecurity";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return {
    ...mod,
    api: { ...mod.api, listUsers: vi.fn(), createUser: vi.fn(), patchUser: vi.fn(), deleteUser: vi.fn(), changePassword: vi.fn() },
  };
});
const mocked = vi.mocked(api);
beforeEach(() => vi.clearAllMocks());

const admin: AuthStatus = { auth_required: true, user: { id: 1, username: "admin", role: "admin" } };
const qa: AuthStatus = { auth_required: true, user: { id: 2, username: "budi", role: "qa" } };
const row = (id: number, username: string, role: "admin" | "qa" | "viewer", active = true) => ({
  id, username, role, active, created_at: "2026-11-09T08:00:00", last_login: null,
});

function renderAs(status: AuthStatus) {
  return renderWithProviders(
    <AuthProvider value={{ status, logout: () => {} }}>
      <SecurityTab />
    </AuthProvider>,
  );
}

describe("Pengaturan > Keamanan", () => {
  it("mode lokal menjelaskan tanpa login dan cara pasang di server", () => {
    renderAs({ auth_required: false, user: null });
    expect(screen.getByText("Mode lokal")).toBeInTheDocument();
    expect(screen.getByText(/qa-agent serve --host 0.0.0.0 --auth/)).toBeInTheDocument();
    expect(mocked.listUsers).not.toHaveBeenCalled();
  });

  it("Admin menambah pengguna dan mengubah peran", async () => {
    mocked.listUsers.mockResolvedValue([row(1, "admin", "admin"), row(2, "budi", "qa")]);
    mocked.createUser.mockResolvedValue(row(3, "sari", "viewer"));
    mocked.patchUser.mockResolvedValue(row(2, "budi", "viewer"));
    renderAs(admin);
    const user = userEvent.setup();
    expect(await screen.findByText("budi")).toBeInTheDocument();
    expect(screen.getByText("Anda")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Peran budi"), "viewer");
    await waitFor(() => expect(mocked.patchUser).toHaveBeenCalledWith(2, { role: "viewer" }));

    await user.type(screen.getByLabelText("Username"), "sari");
    await user.type(screen.getByLabelText("Password awal"), "pendek");
    await user.click(screen.getByRole("button", { name: "Tambah" }));
    expect(screen.getByText("Password minimal 8 karakter")).toBeInTheDocument();
    expect(mocked.createUser).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("Password awal"));
    await user.type(screen.getByLabelText("Password awal"), "sari-pass-1");
    await user.selectOptions(screen.getByLabelText("Peran"), "viewer");
    await user.click(screen.getByRole("button", { name: "Tambah" }));
    await waitFor(() => expect(mocked.createUser).toHaveBeenCalledWith({ username: "sari", password: "sari-pass-1", role: "viewer" }));
  });

  it("menampilkan pesan bila admin terakhir mau dihapus", async () => {
    const { ApiError } = await import("@/lib/api");
    mocked.listUsers.mockResolvedValue([row(1, "admin", "admin"), row(2, "kepala", "admin")]);
    mocked.deleteUser.mockRejectedValue(new ApiError(409, "Minimal harus ada satu Admin aktif"));
    renderAs(admin);
    const user = userEvent.setup();
    await user.click(await screen.findByLabelText("Hapus kepala"));
    expect(await screen.findByText("Minimal harus ada satu Admin aktif")).toBeInTheDocument();
  });

  it("QA tidak melihat daftar pengguna tapi bisa ganti password sendiri", async () => {
    mocked.changePassword.mockResolvedValue(undefined);
    renderAs(qa);
    const user = userEvent.setup();
    expect(mocked.listUsers).not.toHaveBeenCalled();
    expect(screen.getByText(/Pengguna dan peran dikelola oleh Admin/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Password saat ini"), "lama-pass-1");
    await user.type(screen.getByLabelText("Password baru"), "baru-pass-1");
    await user.type(screen.getByLabelText("Ulangi password baru"), "beda-pass-1");
    await user.click(screen.getByRole("button", { name: "Simpan password" }));
    expect(screen.getByText("Konfirmasi password tidak sama")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Ulangi password baru"));
    await user.type(screen.getByLabelText("Ulangi password baru"), "baru-pass-1");
    await user.click(screen.getByRole("button", { name: "Simpan password" }));
    await waitFor(() => expect(mocked.changePassword).toHaveBeenCalledWith("lama-pass-1", "baru-pass-1"));
    expect(await screen.findByText("Password diganti")).toBeInTheDocument();
  });
});
