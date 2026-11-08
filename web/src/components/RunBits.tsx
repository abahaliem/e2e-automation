import { AndroidLogo, FileHtml, FileXls, Globe } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import { STATUS_ORDER } from "@/lib/format";
import type { Run } from "@/lib/types";

export function PlatformIcon({ platform }: { platform: string }) {
  return platform === "android" ? <AndroidLogo className="text-pass" /> : <Globe className="text-accent" />;
}

const COUNT_COLOR: Record<string, string> = {
  Pass: "text-pass",
  Fail: "text-fail",
  "Perlu Review": "text-review",
  Blocked: "text-fg-dim",
  Skipped: "text-fg-dim",
};

export function CountsInline({ run }: { run: Pick<Run, "counts" | "mode"> }) {
  const items = STATUS_ORDER.filter((s) => run.counts[s]);
  if (!items.length) return <span className="text-xs text-fg-muted">{run.mode === "explore" ? "Inventaris fitur" : "-"}</span>;
  return (
    <div className="flex gap-3 text-xs">
      {items.map((s) => (
        <span key={s} className={COUNT_COLOR[s]}>
          {run.counts[s]} {s === "Perlu Review" ? "Review" : s}
        </span>
      ))}
    </div>
  );
}

export function DocButtons({ runId }: { runId: number }) {
  return (
    <div className="flex justify-end gap-2">
      <a href={api.downloadUrl(runId, "xlsx")} download className="flex h-8 items-center gap-1.5 rounded-md border border-ink-700 px-2.5 text-xs hover:bg-ink-850">
        <FileXls className="text-pass" />
        Excel
      </a>
      <a href={api.downloadUrl(runId, "html")} download className="flex h-8 items-center gap-1.5 rounded-md border border-ink-700 px-2.5 text-xs hover:bg-ink-850">
        <FileHtml className="text-accent" />
        HTML
      </a>
    </div>
  );
}
