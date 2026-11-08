import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InterventionPanel } from "./InterventionPanel";

function setup(props: Partial<Parameters<typeof InterventionPanel>[0]> = {}) {
  const onCommand = vi.fn().mockResolvedValue(undefined);
  render(
    <InterventionPanel
      controlState="running"
      awaitingConfirm={false}
      confirmEachStep={false}
      active
      onCommand={onCommand}
      {...props}
    />,
  );
  return { onCommand, user: userEvent.setup() };
}

describe("InterventionPanel", () => {
  it("Pikir ulang hanya aktif saat dijeda", () => {
    setup({ controlState: "running" });
    expect(screen.getByRole("button", { name: /Pikir ulang/ })).toBeDisabled();
  });

  it("Pikir ulang aktif saat dijeda dan mengirim perintah", async () => {
    const { onCommand, user } = setup({ controlState: "paused" });
    await user.click(screen.getByRole("button", { name: /Pikir ulang/ }));
    expect(onCommand).toHaveBeenCalledWith({ command: "think_again" });
  });

  it("arahan dikirim lalu kotak dikosongkan", async () => {
    const { onCommand, user } = setup();
    const box = screen.getByLabelText("Arahkan agent");
    await user.type(box, "Cek juga halaman daftar");
    await user.click(screen.getByRole("button", { name: /Kirim/ }));
    expect(onCommand).toHaveBeenCalledWith({ command: "hint", text: "Cek juga halaman daftar" });
    expect(box).toHaveValue("");
  });

  it("input ketik & akhiri test case hanya saat ambil alih", async () => {
    setup({ controlState: "running" });
    expect(screen.queryByLabelText("Ketik ke halaman")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Akhiri: Pass/ })).not.toBeInTheDocument();
  });

  it("saat ambil alih: ketik teks, tombol, dan akhiri test case", async () => {
    const { onCommand, user } = setup({ controlState: "takeover" });
    await user.type(screen.getByLabelText("Ketik ke halaman"), "halo");
    await user.click(screen.getByRole("button", { name: "Ketik" }));
    expect(onCommand).toHaveBeenCalledWith({ command: "input", event: { kind: "type", text: "halo" } });
    await user.click(screen.getByRole("button", { name: "Enter" }));
    expect(onCommand).toHaveBeenCalledWith({ command: "input", event: { kind: "key", key: "Enter" } });
    await user.click(screen.getByRole("button", { name: /Akhiri: Fail/ }));
    expect(onCommand).toHaveBeenCalledWith({ command: "end_case", status: "fail", note: "" });
  });

  it("mode konfirmasi: tombol Jalankan langkah muncul saat menunggu", async () => {
    const { onCommand, user } = setup({ confirmEachStep: true, awaitingConfirm: true });
    await user.click(screen.getByRole("button", { name: /Jalankan langkah/ }));
    expect(onCommand).toHaveBeenCalledWith({ command: "confirm_step" });
  });

  it("semua kontrol nonaktif bila run tidak aktif", () => {
    setup({ active: false, controlState: null });
    expect(screen.getByRole("button", { name: /Kirim/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Lewati/ })).toBeDisabled();
  });
});
