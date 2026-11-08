import { cn } from "@/lib/cn";

const STYLES: Record<string, { color: string; bg: string; dot: string }> = {
  Pass: { color: "text-pass", bg: "bg-pass/10", dot: "bg-pass" },
  Fail: { color: "text-fail", bg: "bg-fail/10", dot: "bg-fail" },
  "Perlu Review": { color: "text-review", bg: "bg-review/10", dot: "bg-review" },
  Blocked: { color: "text-fg-muted", bg: "bg-ink-800", dot: "bg-fg-muted" },
  Skipped: { color: "text-fg-dim", bg: "bg-ink-850", dot: "bg-ink-500" },
  none: { color: "text-fg-dim", bg: "bg-transparent", dot: "bg-ink-600" },
};

export function statusColor(status: string | null | undefined): string {
  return (STYLES[status ?? "none"] ?? STYLES.none).color;
}

export function StatusBadge({
  status,
  severity,
  className,
}: {
  status: string | null | undefined;
  severity?: string | null;
  className?: string;
}) {
  const key = status && STYLES[status] ? status : "none";
  const style = STYLES[key];
  const label = status ? (severity && status === "Fail" ? `${status}, ${severity}` : status) : "Belum dijalankan";
  return (
    <span
      data-status={status ?? "none"}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium",
        style.color,
        style.bg,
        className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} aria-hidden />
      <span>{label}</span>
    </span>
  );
}
