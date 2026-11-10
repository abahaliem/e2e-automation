import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { UNAUTHORIZED_EVENT, api, request } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      authStatus: vi.fn(),
      login: vi.fn(),
      logout: vi.fn(),
      listProfiles: vi.fn().mockResolvedValue([]),
      stats: vi.fn().mockResolvedValue({ runs_total: 0, cases_total: 0, pass_rate: 0, findings_open: 0, running: 0 }),
      listRuns: vi.fn().mockResolvedValue([]),
      listApps: vi.fn().mockResolvedValue([]),
    },
  };
});
const mocked = vi.mocked(api);

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/settings?tab=security"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("Login (mode server)", () => {
  it("mode server tanpa sesi menampilkan halaman login, lalu masuk", async () => {
    mocked.authStatus.mockResolvedValueOnce({ auth_required: true, user: null });
    mocked.authStatus.mockResolvedValue({ auth_required: true, user: { id: 1, username: "admin", role: "admin" } });
    mocked.login.mockResolvedValue({ user: { id: 1, username: "admin", role: "admin" } });
    renderApp();
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { name: "Masuk" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "admin-pass-1");
    await user.click(screen.getByRole("button", { name: "Masuk" }));
    expect(mocked.login).toHaveBeenCalledWith("admin", "admin-pass-1");
    expect(await screen.findByRole("button", { name: "Keluar" })).toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();
  });

  it("mode lokal langsung masuk dashboard tanpa login", async () => {
    mocked.authStatus.mockResolvedValue({ auth_required: false, user: null });
    renderApp();
    expect(await screen.findByRole("heading", { name: "Pengaturan" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Keluar" })).not.toBeInTheDocument();
  });

  it("sesi habis (401) kembali ke halaman login", async () => {
    mocked.authStatus.mockResolvedValueOnce({ auth_required: true, user: { id: 1, username: "admin", role: "admin" } });
    renderApp();
    await screen.findByRole("button", { name: "Keluar" });
    mocked.authStatus.mockResolvedValue({ auth_required: true, user: null });
    act(() => {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    });
    await waitFor(() => expect(screen.getByRole("heading", { name: "Masuk" })).toBeInTheDocument());
  });
});

describe("request()", () => {
  it("selalu mengirim header X-QA-Agent dan memberi tahu saat 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Silakan masuk dulu" }), { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const heard = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, heard);
    await expect(request("/api/apps", { method: "POST", json: {} })).rejects.toThrow("Silakan masuk dulu");
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers).toMatchObject({ "X-QA-Agent": "1" });
    expect(heard).toHaveBeenCalledTimes(1);
    window.removeEventListener(UNAUTHORIZED_EVENT, heard);
    vi.unstubAllGlobals();
  });
});
