import { AndroidLogo, DeviceMobileCamera, Globe, MonitorPlay, PauseCircle, Play, TrendDown, TrendUp } from "@phosphor-icons/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CountsInline, DocButtons, PlatformIcon } from "@/components/RunBits";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, EmptyState, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { duration, formatDateTime, percent, scopeLabel } from "@/lib/format";
import type { Run } from "@/lib/types";
import { useGlobalEvents } from "@/lib/ws";

const ACTIVE = "running,paused,queued";

export function DashboardPage() {
  const qc = useQueryClient();
  const [days, setDays] = useState(30);
  const stats = useQuery({ queryKey: ["stats", days], queryFn: () => api.stats(days) });
  const running = useQuery({ queryKey: ["runs", "active"], queryFn: () => api.listRuns({ status: ACTIVE, limit: 20 }) });
  const done = useQuery({ queryKey: ["runs", "completed"], queryFn: () => api.listRuns({ status: "completed", limit: 6 }) });
  const findings = useQuery({ queryKey: ["findings"], queryFn: () => api.findings(6) });

  useGlobalEvents((event) => {
    if (event.type === "run.status") {
      qc.invalidateQueries({ queryKey: ["runs"] });
      if (event.status === "completed" || event.status === "interrupted") {
        qc.invalidateQueries({ queryKey: ["stats"] });
        qc.invalidateQueries({ queryKey: ["findings"] });
      }
    }
  });

  const s = stats.data;
  const webPct = s && s.total_runs ? (s.web_runs / s.total_runs) * 100 : 0;
  const delta = s && s.pass_rate != null && s.pass_rate_prev != null ? s.pass_rate - s.pass_rate_prev : null;

  return (
    <main className="flex flex-col gap-8 px-10 py-8">
      <PageHeader
        title="Dashboard"
        description={`Ringkasan pengujian web dan Android dalam ${days} hari terakhir.`}
        actions={
          <>
            <Select aria-label="Periode" value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-44">
              <option value={7}>7 hari terakhir</option>
              <option value={30}>30 hari terakhir</option>
              <option value={90}>90 hari terakhir</option>
            </Select>
            <Link to="/runs/new" className="flex h-10 items-center gap-2 whitespace-nowrap rounded-lg bg-accent px-5 text-sm font-semibold text-white hover:bg-accent-hover">
              <Play weight="fill" />
              Run baru
            </Link>
          </>
        }
      />

      <section className="grid grid-cols-[1.4fr_1fr_1fr_1fr] divide-x divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
        {!s ? (
          [0, 1, 2, 3].map((i) => (
            <div key={i} className="p-5">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="mt-3 h-9 w-20" />
            </div>
          ))
        ) : (
          <>
            <div className="p-5">
              <div className="text-sm text-fg-muted">Total pengujian</div>
              <div className="mt-2 flex items-end gap-6">
                <div className="text-4xl font-semibold tracking-tight">{s.total_runs}</div>
                <div className="flex gap-5 pb-1 text-sm">
                  <span className="flex items-center gap-1.5">
                    <Globe className="text-accent" />
                    <span className="font-medium">{s.web_runs}</span>
                    <span className="text-fg-muted">Web</span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    <AndroidLogo className="text-pass" />
                    <span className="font-medium">{s.android_runs}</span>
                    <span className="text-fg-muted">Android</span>
                  </span>
                </div>
              </div>
              <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-ink-800">
                <div className="bg-accent" style={{ width: `${webPct}%` }} />
                <div className="bg-pass" style={{ width: `${s.total_runs ? 100 - webPct : 0}%` }} />
              </div>
            </div>
            <div className="p-5">
              <div className="text-sm text-fg-muted">Test case dijalankan</div>
              <div className="mt-2 text-4xl font-semibold tracking-tight">{s.cases_executed}</div>
              <div className="mt-3 text-sm text-fg-muted">tanpa test case Skipped</div>
            </div>
            <div className="p-5">
              <div className="text-sm text-fg-muted">Temuan</div>
              <div className="mt-2 text-4xl font-semibold tracking-tight">{s.findings}</div>
              <div className="mt-3 flex gap-3 text-sm">
                <span className="text-fail">{s.fail} Fail</span>
                <span className="text-review">{s.review} Perlu Review</span>
              </div>
            </div>
            <div className="p-5">
              <div className="text-sm text-fg-muted">Pass rate</div>
              <div className="mt-2 text-4xl font-semibold tracking-tight">{percent(s.pass_rate)}</div>
              <div className={cn("mt-3 flex items-center gap-1 text-sm", delta == null ? "text-fg-muted" : delta >= 0 ? "text-pass" : "text-fail")}>
                {delta == null ? (
                  "belum ada pembanding"
                ) : (
                  <>
                    {delta >= 0 ? <TrendUp /> : <TrendDown />}
                    {delta >= 0 ? "naik" : "turun"} {percent(Math.abs(delta))} dari periode sebelumnya
                  </>
                )}
              </div>
            </div>
          </>
        )}
      </section>

      <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-8">
        <div className="flex min-w-0 flex-col gap-8">
          <section className="flex flex-col gap-3">
            <h2 className="font-semibold">
              Sedang berjalan <span className="font-normal text-fg-dim">{running.data?.length ?? ""}</span>
            </h2>
            {running.isLoading ? (
              <div className="grid grid-cols-2 gap-4">
                <Skeleton className="h-56" />
                <Skeleton className="h-56" />
              </div>
            ) : running.data && running.data.length > 0 ? (
              <div className="grid grid-cols-2 gap-4">
                {running.data.map((r) => (
                  <RunningCard key={r.id} run={r} />
                ))}
              </div>
            ) : (
              <Card>
                <EmptyState title="Tidak ada run yang sedang berjalan" description="Mulai run baru untuk menguji aplikasi web." />
              </Card>
            )}
          </section>

          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Selesai</h2>
              <Link to="/runs" className="text-sm text-accent">
                Lihat semua riwayat
              </Link>
            </div>
            <Card className="overflow-hidden">
              {done.isLoading ? (
                <div className="flex flex-col gap-2 p-4">
                  <Skeleton className="h-8" />
                  <Skeleton className="h-8" />
                </div>
              ) : done.data && done.data.length > 0 ? (
                <table className="w-full text-sm [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap">
                  <thead className="border-b border-ink-700 bg-ink-850 text-left text-xs text-fg-muted">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">Aplikasi</th>
                      <th className="px-4 py-2.5 font-medium">Cakupan</th>
                      <th className="px-4 py-2.5 font-medium">Hasil</th>
                      <th className="px-4 py-2.5 font-medium">Selesai</th>
                      <th className="px-4 py-2.5 text-right font-medium">Dokumen</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-700">
                    {done.data.map((r) => (
                      <tr key={r.id} className="hover:bg-ink-850">
                        <td className="px-4 py-3">
                          <Link to={`/runs/${r.id}/result`} className="flex items-center gap-2 font-medium hover:text-accent">
                            <PlatformIcon platform={r.platform} />
                            {r.app_name}
                          </Link>
                        </td>
                        <td className="px-4 py-3 text-fg-muted">{scopeLabel(r)}</td>
                        <td className="px-4 py-3">
                          <CountsInline run={r} />
                        </td>
                        <td className="px-4 py-3 text-fg-muted">{formatDateTime(r.finished_at ?? r.started_at)}</td>
                        <td className="px-4 py-3">
                          <DocButtons runId={r.id} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <EmptyState title="Belum ada run selesai" description="Dokumen test case dan evidence akan muncul di sini." />
              )}
            </Card>
          </section>
        </div>

        <aside className="flex flex-col gap-3">
          <h2 className="font-semibold">Temuan terbaru</h2>
          <Card className="divide-y divide-ink-700">
            {findings.isLoading ? (
              <div className="p-4">
                <Skeleton className="h-16" />
              </div>
            ) : findings.data && findings.data.length > 0 ? (
              findings.data.map((f) => (
                <Link key={`${f.run_id}-${f.tc_id}`} to={`/runs/${f.run_id}/result`} className="block p-4 hover:bg-ink-850">
                  <div className="flex items-center justify-between text-xs">
                    <StatusBadge status={f.status} severity={f.severity} />
                    <span className="text-fg-dim">{f.app_name}</span>
                  </div>
                  <div className="mt-2 text-sm font-medium">{f.title}</div>
                  <div className="mt-1 font-mono text-xs text-fg-dim">{f.tc_id}</div>
                </Link>
              ))
            ) : (
              <EmptyState title="Belum ada temuan" />
            )}
          </Card>
        </aside>
      </div>
    </main>
  );
}

function useTick(ms: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

function RunningCard({ run }: { run: Run }) {
  const qc = useQueryClient();
  const pausedByError = run.status === "paused";
  const pausedByQa = run.control_state === "paused";
  const queued = run.status === "queued";
  const state = useQuery({ queryKey: ["run-state", run.id], queryFn: () => api.runState(run.id), refetchInterval: 5000 });
  const tick = useTick(1000);
  const [thumbFailed, setThumbFailed] = useState(false);
  const thumbTick = Math.floor(tick / 5000);

  const cases = state.data?.cases ?? [];
  const done = cases.filter((c) => c.status).length;
  const total = cases.length;
  const progressText =
    run.mode === "explore"
      ? `${state.data?.screens ?? 0} layar dipetakan`
      : total
        ? `Test case ${Math.min(done + 1, total)} dari ${total}`
        : "Menyusun test case...";
  const pct = run.mode === "explore" ? Math.min(95, (state.data?.screens ?? 0) * 5) : total ? Math.round((done / total) * 100) : 0;
  const paused = pausedByError || pausedByQa;

  return (
    <article className="overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
      <div className="grid aspect-[16/7] place-items-center overflow-hidden border-b border-ink-700 bg-ink-850 text-fg-muted">
        {!thumbFailed && !queued ? (
          <img
            src={`/api/runs/${run.id}/thumbnail?t=${thumbTick}`}
            alt={`Layar live run ${run.app_name}`}
            onError={() => setThumbFailed(true)}
            className={cn("h-full w-full bg-white", run.platform === "android" ? "object-contain" : "object-cover object-top")}
          />
        ) : (
          <div className="flex flex-col items-center gap-2 text-xs">
            {run.platform === "android" ? <DeviceMobileCamera className="text-3xl" /> : <MonitorPlay className="text-3xl" />}
            <span className="font-mono">
              {run.platform === "android" ? `${run.device_serial ?? "HP"} tersambung` : run.url.replace(/^https?:\/\//, "")}
            </span>
          </div>
        )}
      </div>
      <div className="p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 font-medium">
            <PlatformIcon platform={run.platform} />
            {run.app_name}
          </div>
          {pausedByError || pausedByQa ? (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-review">
              <PauseCircle weight="fill" />
              Dijeda
            </span>
          ) : queued ? (
            <span className="text-xs font-medium text-fg-muted">Menunggu</span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-accent">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
              Berjalan
            </span>
          )}
        </div>
        <div className="mt-1 text-sm text-fg-muted">{run.mode === "explore" ? "Jelajahi seluruh aplikasi" : `Uji modul ${run.module}`}</div>
        {pausedByError && run.note && <div className="mt-2 line-clamp-2 text-xs text-review">{run.note}</div>}
        <div className="mt-3 flex items-center justify-between text-xs text-fg-muted">
          <span>{queued ? "Menunggu giliran" : progressText}</span>
          <span data-testid="run-timer" className="font-mono">
            {duration(run.started_at, null, new Date(tick))}
          </span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink-800"
        >
          <div className={cn("h-full", paused ? "bg-review" : "bg-accent")} style={{ width: `${pct}%` }} />
        </div>
        {pausedByError ? (
          <button
            type="button"
            onClick={async () => {
              await api.resumeRun(run.id);
              qc.invalidateQueries({ queryKey: ["runs"] });
            }}
            className="mt-4 flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-ink-600 text-sm hover:bg-ink-850"
          >
            <Play />
            Lanjutkan
          </button>
        ) : (
          <Link to={`/runs/${run.id}`} className="mt-4 flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-ink-600 text-sm hover:bg-ink-850">
            <MonitorPlay />
            Lihat live
          </Link>
        )}
      </div>
    </article>
  );
}
