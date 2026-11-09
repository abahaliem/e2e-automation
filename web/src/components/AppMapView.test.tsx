import { screen } from "@testing-library/react";
import { api } from "@/lib/api";
import type { Run } from "@/lib/types";
import { renderWithProviders } from "@/test/render";
import { AppMapView } from "./AppMapView";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, runMap: vi.fn() } };
});
const mocked = vi.mocked(api);

describe("Peta aplikasi (hasil Seluruh aplikasi)", () => {
  it("menampilkan layar per modul dan tombol Uji modul ini", async () => {
    mocked.runMap.mockResolvedValue({
      screens: 3,
      modules: [
        { name: "Autentikasi", screens: [{ page_name: "Sign In", purpose: "Masuk", url: "a", public: true, depth: 0, forms: ["Login"], actions: [], screenshot_url: "/api/runs/21/files/s1.png" }] },
        { name: "Work Order", screens: [
          { page_name: "Daftar Work Order", purpose: "Daftar WO", url: "b", public: false, depth: 0, forms: [], actions: [], screenshot_url: null },
          { page_name: "Troubleshoot", purpose: "", url: "c", public: false, depth: 1, forms: [], actions: [], screenshot_url: null },
        ] },
      ],
    });
    const run = { id: 21, app_id: 4, platform: "android", status: "completed", mode: "explore" } as Run;
    renderWithProviders(<AppMapView run={run} />);
    expect(await screen.findByText("3 layar dipetakan dalam 2 modul", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Layar Sign In" })).toHaveAttribute("src", "/api/runs/21/files/s1.png");
    const links = screen.getAllByRole("link", { name: /Uji modul ini/ });
    expect(links[1]).toHaveAttribute("href", "/runs/new?app=4&module=Work%20Order&platform=android");
  });
});