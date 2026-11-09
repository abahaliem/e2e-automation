import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./AppShell";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell profile={{ name: "GLM kantor", model: "z-ai/glm-5.3-flash", ok: true }} />}>
          <Route path="*" element={<div>isi</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppShell", () => {
  it("menandai menu aktif sesuai route", () => {
    renderAt("/runs/new");
    expect(screen.getByRole("link", { name: /Run baru/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Dashboard/ })).not.toHaveAttribute("aria-current");
  });

  it("riwayat aktif untuk halaman hasil run", () => {
    renderAt("/runs/12/result");
    expect(screen.getByRole("link", { name: /Riwayat run/ })).toHaveAttribute("aria-current", "page");
  });

  it("menu Perangkat aktif", () => {
    renderAt("/devices");
    expect(screen.getByRole("link", { name: /Perangkat/ })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByText("segera")).not.toBeInTheDocument();
  });

  it("menampilkan profil AI di bawah", () => {
    renderAt("/");
    expect(screen.getByText("z-ai/glm-5.3-flash")).toBeInTheDocument();
    expect(screen.getByText("GLM kantor")).toBeInTheDocument();
  });
});
