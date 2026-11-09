import { Trash } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { CountsInline, DocButtons, PlatformIcon } from "@/components/RunBits";
import { Alert, Button, Card, EmptyState, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { RUN_STATUS_LABEL, formatDateTime, scopeLabel } from "@/lib/format";

const STATUS_TONE: Record<string, string> = {
  queued: "text-fg-muted",
  running: "text-accent",
  paused: "text-review",
  completed: "text-pass",
  interrupted: "text-fail",
};

export function HistoryPage() {
  const [status, setStatus] = useState("");
  const [appId, setAppId] = useState<number | "">("");
  const apps = useQuery({ queryKey: ["apps"], queryFn: api.listApps });
  const can = useCan();
  const [deleted, setDeleted] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const runs = useQuery({
    queryKey: ["runs", "history", status, appId],
    queryFn: () => api.listRuns({ status: status || undefined, app_id: appId || undefined, limit: 200 }),
  });

  return (
    <main className="flex flex-col gap-6 px-10 py-8">
      <PageHeader
        title="Riwayat run"
        description="Semua run beserta dokumen hasil pengujiannya."
        actions={
          <>
            <Select aria-label="Filter aplikasi" className="w-48" value={appId} onChange={(e) => setAppId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Semua aplikasi</option>
              {(apps.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
            <Select aria-label="Filter status" className="w-44" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Semua status</option>
              {Object.entries(RUN_STATUS_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </>
        }
      />
      {error && <Alert tone="error">{error}</Alert>}
      {deleted && <Alert tone="success">Run #{deleted} dan evidence-nya dihapus.</Alert>}
      <Card className="overflow-hidden">
        {runs.isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </div>
        ) : runs.data && runs.data.length > 0 ? (
          <table className="w-full text-sm [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap">
            <thead className="border-b border-ink-700 bg-ink-850 text-left text-xs text-fg-muted">
              <tr>
                <th className="px-4 py-2.5 font-medium">Aplikasi</th>
                <th className="px-4 py-2.5 font-medium">Cakupan</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Hasil</th>
                <th className="px-4 py-2.5 font-medium">Mulai</th>
                <th className="px-4 py-2.5 font-medium" />
                <th className="px-4 py-2.5 text-right font-medium">Dokumen</th>
                {can.write && <th className="px-4 py-2.5" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-700">
              {runs.data.map((r) => {
                const live = r.status === "running" || r.status === "queued";
                return (
                  <tr key={r.id} className="hover:bg-ink-850">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 font-medium">
                        <PlatformIcon platform={r.platform} />
                        {r.app_name}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-fg-muted">
                      {scopeLabel(r)}
                      {r.environment === "production" && <span className="ml-2 rounded bg-review/10 px-1.5 py-0.5 text-xs text-review">Production</span>}
                    </td>
                    <td className={cn("px-4 py-3 font-medium", STATUS_TONE[r.status])}>{r.awaiting_review ? "Menunggu review" : RUN_STATUS_LABEL[r.status] ?? r.status}</td>
                    <td className="px-4 py-3">
                      <CountsInline run={r} />
                    </td>
                    <td className="px-4 py-3 text-fg-muted">{formatDateTime(r.started_at)}</td>
                    <td className="px-4 py-3">
                      {r.awaiting_review ? (
                        <Link to={`/runs/${r.id}/review`} className="text-accent">
                          Review test case
                        </Link>
                      ) : (
                        <Link to={live ? `/runs/${r.id}` : `/runs/${r.id}/result`} className="text-accent">
                          {live ? "Lihat live" : "Lihat hasil"}
                        </Link>
                      )}
                    </td>
                    <td className="px-4 py-3">{!live && <DocButtons runId={r.id} />}</td>
                    {can.write && (
                      <td className="px-4 py-3 text-right">{!live && <DeleteRun runId={r.id} onDeleted={() => setDeleted(r.id)} onError={setError} />}</td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <EmptyState
            title="Belum ada run"
            description="Mulai run baru, atau impor folder runs/ dari CLI lama di halaman Aplikasi."
            action={
              <Link to="/runs/new" className="text-sm text-accent">
                Mulai run baru
              </Link>
            }
          />
        )}
      </Card>
    </main>
  );
}

/** Hapus run (konfirmasi dua langkah): data, screenshot, dan dokumen run ikut terhapus permanen. */
function DeleteRun({ runId, onDeleted, onError }: { runId: number; onDeleted: () => void; onError: (msg: string | null) => void }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const remove = useMutation({
    mutationFn: () => api.deleteRun(runId),
    onSuccess: () => {
      onError(null);
      onDeleted();
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (e) => onError(e instanceof Error ? e.message : String(e)),
  });
  if (!confirm) {
    return (
      <Button size="sm" variant="ghost" aria-label={`Hapus run ${runId}`} onClick={() => setConfirm(true)}>
        <Trash />
      </Button>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className="text-fg-muted">Hapus permanen?</span>
      <Button size="sm" variant="danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
        Hapus
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>
        Batal
      </Button>
    </span>
  );
}