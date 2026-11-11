import { MonitorPlay } from "@phosphor-icons/react";
import { useRef, useState, type CSSProperties, type MouseEvent, type WheelEvent } from "react";
import { cn } from "@/lib/cn";
import type { Frame, ManualEvent } from "@/lib/types";

export type Overlay = {
  bbox: [number, number, number, number];
  viewport: { width: number; height: number };
  label?: string;
} | null;

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const round = (v: number) => Math.round(v * 10000) / 10000;

/** Posisi klik di panel live → koordinat ternormalisasi 0..1 (tidak bergantung ukuran panel). */
export function toNormalized(clientX: number, clientY: number, rect: DOMRect): { x: number; y: number } {
  const x = rect.width > 0 ? (clientX - rect.left) / rect.width : 0;
  const y = rect.height > 0 ? (clientY - rect.top) / rect.height : 0;
  return { x: round(clamp01(x)), y: round(clamp01(y)) };
}

const pct = (v: number) => `${Math.round(v * 10000) / 100}%`;

/** Kotak elemen digambar dalam persen terhadap viewport browser yang diuji. */
export function overlayStyle(bbox: [number, number, number, number], viewport: { width: number; height: number }): CSSProperties {
  const [x, y, w, h] = bbox;
  return {
    left: pct(clamp01(x / viewport.width)),
    top: pct(clamp01(y / viewport.height)),
    width: pct(clamp01(w / viewport.width)),
    height: pct(clamp01(h / viewport.height)),
  };
}

export function LiveView({
  frame,
  overlay,
  takeover,
  onInput,
  className,
  placeholder = false,
}: {
  frame: Frame | null;
  overlay: Overlay;
  takeover: boolean;
  onInput: (event: ManualEvent) => void;
  className?: string;
  /** Tampilkan placeholder dengan ukuran dari frame (mis. bingkai HP sebelum frame pertama). */
  placeholder?: boolean;
}) {
  const ratio = frame ? `${frame.width} / ${frame.height}` : "16 / 9";
  const portrait = !!frame && frame.height > frame.width;
  // HP (potret): tinggi dibatasi, lebar mengikuti rasio, di tengah panel
  const sizing: CSSProperties = portrait
    ? { aspectRatio: ratio, height: "min(68vh, 860px)", width: "auto", maxWidth: "100%" }
    : { aspectRatio: ratio };
  // Tanda di titik klik QA saat Ambil alih, supaya jelas bagian mana yang dikirim
  const [marks, setMarks] = useState<{ id: number; x: number; y: number; n: number }[]>([]);
  const counter = useRef(0);
  const handleClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!takeover) return;
    const { x, y } = toNormalized(e.clientX, e.clientY, e.currentTarget.getBoundingClientRect());
    onInput({ kind: "click", x, y });
    const id = Date.now() + Math.random();
    counter.current += 1;
    const n = counter.current;
    setMarks((m) => [...m.slice(-4), { id, x, y, n }]);
    window.setTimeout(() => setMarks((m) => m.filter((k) => k.id !== id)), 3000);
  };
  const handleWheel = (e: WheelEvent<HTMLDivElement>) => {
    if (!takeover) return;
    onInput({ kind: "scroll", dy: Math.round(e.deltaY) });
  };
  return (
    <div
      data-testid="live-surface"
      onClick={handleClick}
      onWheel={handleWheel}
      style={sizing}
      className={cn(
        "relative select-none overflow-hidden bg-white",
        portrait ? "mx-auto" : "w-full",
        takeover ? "cursor-crosshair ring-2 ring-inset ring-accent" : "cursor-default",
        className,
      )}
    >
      {frame && !placeholder ? (
        <img src={frame.url} alt="Tampilan langsung browser yang sedang diuji agent" draggable={false} className="block h-full w-full object-contain" />
      ) : (
        <div className="absolute inset-0 grid place-items-center bg-ink-850 text-fg-muted">
          <div className="flex flex-col items-center gap-2 text-sm">
            <MonitorPlay className="text-3xl" />
            {placeholder ? "Menunggu layar dari HP..." : "Menunggu layar dari browser..."}
          </div>
        </div>
      )}
      {takeover &&
        marks.map((m, i) => (
          <div
            key={m.id}
            data-testid="click-mark"
            className={cn("pointer-events-none absolute -translate-x-1/2 -translate-y-1/2", i < marks.length - 1 && "opacity-40")}
            style={{ left: pct(m.x), top: pct(m.y) }}
          >
            <span className="absolute -left-4 -top-4 h-8 w-8 animate-ping rounded-full bg-accent/40" />
            <span className="absolute -left-3 -top-3 h-6 w-6 rounded-full border-2 border-accent bg-accent/25 shadow-[0_0_0_3px_rgba(255,255,255,0.8)]" />
            <span className="absolute left-4 -top-7 whitespace-nowrap rounded bg-accent px-1.5 py-0.5 text-[11px] font-medium text-white shadow">
              Klik #{m.n}
            </span>
          </div>
        ))}
      {overlay && !takeover && (
        <div
          data-testid="live-overlay"
          className="pointer-events-none absolute rounded-[3px] border-2 border-accent bg-accent/10 shadow-[0_0_0_4px_rgba(37,96,232,0.15)] transition-all duration-200"
          style={overlayStyle(overlay.bbox, overlay.viewport)}
        >
          {overlay.label && (
            <span className="absolute -top-6 left-0 whitespace-nowrap rounded bg-accent px-1.5 py-0.5 text-[11px] font-medium text-white">
              {overlay.label}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
