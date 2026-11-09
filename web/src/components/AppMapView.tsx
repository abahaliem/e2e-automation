import { LockSimpleOpen, Target } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, EmptyState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { Run } from "@/lib/types";

/** Hasil run Seluruh aplikasi: modul dan layar yang dipetakan, dengan tombol uji per modul. */
export function AppMapView({ run }: { run: Run }) {
  const map = useQuery({ queryKey: ["run-map", run.id], queryFn: () => api.runMap(run.id) });
  if (map.isLoading) return <Skeleton className="h-64" />;
  const modules = map.data?.modules ?? [];
  if (!modules.length) {
    return (
      <Card>
        <EmptyState title="Belum ada layar yang dipetakan" description="Run berhenti sebelum menemukan layar. Jalankan Seluruh aplikasi lagi." />
      </Card>
    );
  }
  const platform = run.platform === "android" ? "&platform=android" : "";
  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-fg-muted">
        {map.data?.screens} layar dipetakan dalam {modules.length} modul. Pilih modul untuk diuji mendalam; AI menyusun test case dari
        layar-layar di modul itu.
      </p>
      {modules.map((m) => (
        <Card key={m.name} className="flex flex-col gap-4 p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="font-semibold">{m.name}</h2>
              <p className="text-xs text-fg-muted">{m.screens.length} layar</p>
            </div>
            {run.status === "completed" && (
              <Link
                to={`/runs/new?app=${run.app_id}&module=${encodeURIComponent(m.name)}${platform}`}
                className="inline-flex h-9 items-center gap-2 rounded-lg bg-accent px-3.5 text-sm font-semibold text-white hover:bg-accent-hover"
              >
                <Target />
                Uji modul ini
              </Link>
            )}
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
            {m.screens.map((s) => (
              <figure key={s.url} className="flex flex-col overflow-hidden rounded-lg border border-ink-700 bg-ink-900">
                <div className="grid h-56 place-items-center overflow-hidden bg-ink-850">
                  {s.screenshot_url ? (
                    <img src={s.screenshot_url} alt={`Layar ${s.page_name}`} className="h-full w-full object-contain object-top" loading="lazy" />
                  ) : (
                    <span className="text-xs text-fg-dim">Tanpa screenshot</span>
                  )}
                </div>
                <figcaption className="flex flex-col gap-1 p-3 text-xs">
                  <span className="flex items-center gap-1.5 text-sm font-medium text-fg">
                    {s.page_name}
                    {s.public && (
                      <span title="Bisa dibuka tanpa login">
                        <LockSimpleOpen className="text-fg-dim" />
                      </span>
                    )}
                  </span>
                  {s.purpose && <span className="text-fg-muted">{s.purpose}</span>}
                  {s.forms.length > 0 && <span className="text-fg-dim">Form: {s.forms.join(", ")}</span>}
                </figcaption>
              </figure>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}
