import type { Run, Status } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

function parse(iso: string): Date {
  return new Date(iso);
}

export function timeAgo(iso: string, now: Date = new Date()): string {
  const diff = (now.getTime() - parse(iso).getTime()) / 1000;
  if (diff < 60) return "baru saja";
  if (diff < 3600) return `${Math.floor(diff / 60)} menit lalu`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} jam lalu`;
  if (diff < 172800) return "kemarin";
  return `${Math.floor(diff / 86400)} hari lalu`;
}

export function formatDateTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "-";
  const d = parse(iso);
  const hm = `${String(d.getHours()).padStart(2, "0")}.${String(d.getMinutes()).padStart(2, "0")}`;
  const sameDay = d.toDateString() === now.toDateString();
  const yesterday = new Date(now.getTime() - 86400000).toDateString() === d.toDateString();
  if (sameDay) return `Hari ini, ${hm}`;
  if (yesterday) return `Kemarin, ${hm}`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${hm}`;
}

export function duration(startIso: string, endIso?: string | null, now: Date = new Date()): string {
  const end = endIso ? parse(endIso) : now;
  const secs = Math.max(0, Math.floor((end.getTime() - parse(startIso).getTime()) / 1000));
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function percent(value: number | null | undefined): string {
  if (value == null) return "-";
  return `${(value * 100).toLocaleString("id-ID", { maximumFractionDigits: 1 })}%`;
}

export function scopeLabel(run: Pick<Run, "mode" | "module">): string {
  return run.mode === "explore" ? "Seluruh aplikasi" : `Modul ${run.module ?? ""}`.trim();
}

export const RUN_STATUS_LABEL: Record<string, string> = {
  queued: "Menunggu",
  running: "Berjalan",
  paused: "Dijeda",
  completed: "Selesai",
  interrupted: "Terhenti",
};

export const STATUS_ORDER: Status[] = ["Pass", "Fail", "Perlu Review", "Blocked", "Skipped"];
