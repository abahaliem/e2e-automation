import { fireEvent, render, screen } from "@testing-library/react";
import { LiveView, overlayStyle, toNormalized } from "./LiveView";

const rect = (left: number, top: number, width: number, height: number) =>
  ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;

describe("toNormalized", () => {
  it("sama untuk panel besar dan kecil (koordinat 0..1)", () => {
    expect(toNormalized(10 + 683, 20 + 384, rect(10, 20, 1366, 768))).toEqual({ x: 0.5, y: 0.5 });
    expect(toNormalized(10 + 341.5, 20 + 192, rect(10, 20, 683, 384))).toEqual({ x: 0.5, y: 0.5 });
    const small = toNormalized(5 + 120, 0 + 30, rect(5, 0, 400, 225));
    expect(small.x).toBeCloseTo(0.3);
    expect(small.y).toBeCloseTo(0.1333, 3);
  });

  it("dibatasi ke 0..1", () => {
    expect(toNormalized(-50, 9999, rect(0, 0, 100, 100))).toEqual({ x: 0, y: 1 });
  });
});

describe("overlayStyle", () => {
  it("persentase dari bbox dan viewport", () => {
    expect(overlayStyle([683, 192, 136.6, 38.4], { width: 1366, height: 768 })).toEqual({
      left: "50%",
      top: "25%",
      width: "10%",
      height: "5%",
    });
  });
});

describe("LiveView", () => {
  const frame = { url: "blob:x", width: 1366, height: 768 };

  it("klik saat ambil alih mengirim koordinat ternormalisasi", () => {
    const onInput = vi.fn();
    render(<LiveView frame={frame} overlay={null} takeover onInput={onInput} />);
    const surface = screen.getByTestId("live-surface");
    surface.getBoundingClientRect = () => rect(0, 0, 683, 384);
    fireEvent.click(surface, { clientX: 341.5, clientY: 96 });
    expect(onInput).toHaveBeenCalledWith({ kind: "click", x: 0.5, y: 0.25 });
    fireEvent.wheel(surface, { deltaY: 120 });
    expect(onInput).toHaveBeenLastCalledWith({ kind: "scroll", dy: 120 });
  });

  it("klik tanpa ambil alih tidak mengirim apa pun", () => {
    const onInput = vi.fn();
    render(<LiveView frame={frame} overlay={null} takeover={false} onInput={onInput} />);
    fireEvent.click(screen.getByTestId("live-surface"), { clientX: 10, clientY: 10 });
    expect(onInput).not.toHaveBeenCalled();
  });

  it("overlay elemen digambar dengan persentase", () => {
    render(
      <LiveView
        frame={frame}
        overlay={{ bbox: [683, 192, 136.6, 38.4], viewport: { width: 1366, height: 768 }, label: "Simpan" }}
        takeover={false}
        onInput={() => undefined}
      />,
    );
    const box = screen.getByTestId("live-overlay");
    expect(box.style.left).toBe("50%");
    expect(box.style.top).toBe("25%");
  });

  it("menampilkan placeholder sebelum frame pertama", () => {
    render(<LiveView frame={null} overlay={null} takeover={false} onInput={() => undefined} />);
    expect(screen.getByText(/Menunggu layar/)).toBeInTheDocument();
  });
});
