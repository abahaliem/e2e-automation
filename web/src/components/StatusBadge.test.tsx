import { render, screen } from "@testing-library/react";
import { StatusBadge } from "./StatusBadge";

const cases: [string | null, string, string][] = [
  ["Pass", "Pass", "text-pass"],
  ["Fail", "Fail", "text-fail"],
  ["Perlu Review", "Perlu Review", "text-review"],
  ["Blocked", "Blocked", "text-fg-muted"],
  ["Skipped", "Skipped", "text-fg-dim"],
  [null, "Belum dijalankan", "text-fg-dim"],
];

describe("StatusBadge", () => {
  it.each(cases)("status %s", (status, label, color) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(label);
    expect(badge.closest("[data-status]")).toHaveClass(color);
    expect(badge.closest("[data-status]")).toHaveAttribute("data-status", status ?? "none");
  });

  it("menampilkan severity bila ada", () => {
    render(<StatusBadge status="Fail" severity="Major" />);
    expect(screen.getByText("Fail, Major")).toBeInTheDocument();
  });
});
