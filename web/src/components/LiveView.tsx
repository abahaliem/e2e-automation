import { MonitorPlay } from "@phosphor-icons/react";
import type { CSSProperties, MouseEvent, WheelEvent } from "react";
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
}: {
  frame: Frame | null;
  overlay: Overlay;
  takeover: boolean;
  onInput: (event: ManualEvent) => void;
  className?: string;
}) {
  const ratio = frame ? `${frame.width} / ${frame.height}` : "16 / 9";
  const handleClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!takeover) return;
    const { x, y } = toNormalized(e.clientX, e.clientY, e.currentTarget.getBoundingClientRect());
    onInput({ kind: "click", x, y });
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
      style={{ aspectRatio: ratio }}
      className={cn(
        "relative w-full select-none overflow-hidden bg-white",
        takeover ? "cursor-crosshair ring-2 ring-inset ring-accent" : "cursor-default",
        className,
      )}
    >
      {frame ? (
        <img src={frame.url} alt="Tampilan langsung browser yang sedang diuji agent" draggable={false} className="block h-full w-full object-contain" />
      ) : (
        <div className="absolute inset-0 grid place-items-center bg-ink-850 text-fg-muted">
          <div className="flex flex-col items-center gap-2 text-sm">
            <MonitorPlay className="text-3xl" />
            Menunggu layar dari browser...
          </div>
        </div>
      )}
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
