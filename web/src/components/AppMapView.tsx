import { CheckCircle, LockSimpleOpen, MagnifyingGlassPlus, Target, X } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, EmptyState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { MapScreen, Run } from "@/lib/types";

/** Hasil run Seluruh aplikasi: modul dan layar yang dipetakan, detail tiap layar, dan tombol uji per modul. */
export function AppMapView({ run }: { run: Run }) {
  const map = useQuery({ queryKey: ["run-map", run.id], queryFn: () => api.runMap(run.id) });
  const [open, setOpen] = useState<{ screen: MapScreen; module: string } | null>(null);
  const qc = useQueryClient();
  const accept = useMutation({
    mutationFn: () => api.acceptMap(run.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["run", run.id] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["apps"] });
      qc.invalidateQueries({ queryKey: ["modules"] });
    },
  });
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
  const testLink = (module: string) => `/runs/new?app=${run.app_id}&module=${encodeURIComponent(module)}${platform}`;
  const unfinished = run.status !== "completed" && !run.active;
  return (
    <div className="flex flex-col gap-5">
      {unfinished && (
        <Alert
          tone="warning"
          action={
            <Button size="sm" variant="primary" onClick={() => accept.mutate()} disabled={accept.isPending}>
              <CheckCircle />
              Pakai hasil pemetaan ini
            </Button>
          }
        >
          Pemetaan ini berhenti sebelum selesai, jadi tombol <b>Uji modul ini</b> dan <b>Alur bisnis</b> belum bisa dipakai.
          Klik <b>Pakai hasil pemetaan ini</b> untuk memakai {map.data?.screens} layar yang sudah terpetakan, atau jalankan
          Seluruh aplikasi lagi untuk memetakan lebih banyak menu.
        </Alert>
      )}
      {accept.error && <Alert tone="error">{(accept.error as Error).message}</Alert>}
      <p className="text-sm text-fg-muted">
        {map.data?.screens} layar dipetakan dalam {modules.length} modul. Klik layar untuk melihat detailnya. Untuk menguji, klik{" "}
        <b>Uji modul ini</b> pada modulnya; AI menyusun test case dari layar-layar di modul itu. Alur yang melintasi beberapa
        modul (mis. buka work order sampai closed) bisa dibuat sebagai <b>Alur bisnis</b> di halaman{" "}
        <Link to={`/apps?app=${run.app_id}`} className="text-accent">
          Aplikasi
        </Link>
        .
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
                to={testLink(m.name)}
                className="inline-flex h-9 items-center gap-2 rounded-lg bg-accent px-3.5 text-sm font-semibold text-white hover:bg-accent-hover"
              >
                <Target />
                Uji modul ini
              </Link>
            )}
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
            {m.screens.map((s) => (
              <button
                key={s.url}
                type="button"
                onClick={() => setOpen({ screen: s, module: m.name })}
                aria-label={`Detail layar ${s.page_name}`}
                className="group flex flex-col overflow-hidden rounded-lg border border-ink-700 bg-ink-900 text-left transition hover:border-accent-line hover:shadow-md focus:outline-none focus-visible:ring-4 focus-visible:ring-accent-soft"
              >
                <div className="relative grid h-56 w-full place-items-center overflow-hidden bg-ink-850">
                  {s.screenshot_url ? (
                    <img src={s.screenshot_url} alt={`Layar ${s.page_name}`} className="h-full w-full object-contain object-top" loading="lazy" />
                  ) : (
                    <span className="text-xs text-fg-dim">Tanpa screenshot</span>
                  )}
                  <span className="absolute right-2 top-2 rounded-md bg-ink-900/90 p-1 text-fg-muted opacity-0 transition group-hover:opacity-100">
                    <MagnifyingGlassPlus />
                  </span>
                </div>
                <span className="flex flex-col gap-1 p-3 text-xs">
                  <span className="flex items-center gap-1.5 text-sm font-medium text-fg">
                    {s.page_name}
                    {s.public && (
                      <span title="Bisa dibuka tanpa login">
                        <LockSimpleOpen className="text-fg-dim" />
                      </span>
                    )}
                  </span>
                  {s.purpose && <span className="line-clamp-3 text-fg-muted">{s.purpose}</span>}
                </span>
              </button>
            ))}
          </div>
        </Card>
      ))}
      {open && (
        <ScreenDialog
          screen={open.screen}
          module={open.module}
          testHref={run.status === "completed" ? testLink(open.module) : null}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}

function ScreenDialog({ screen: s, module, testHref, onClose }: { screen: MapScreen; module: string; testHref: string | null; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-6" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Layar ${s.page_name}`}
        className="grid max-h-[90dvh] w-full max-w-4xl grid-cols-[minmax(0,1fr)_320px] overflow-hidden rounded-xl bg-ink-900 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="grid place-items-center overflow-auto bg-ink-850 p-4">
          {s.screenshot_url ? (
            <img src={s.screenshot_url} alt={`Screenshot ${s.page_name}`} className="max-h-[80dvh] w-auto object-contain" />
          ) : (
            <span className="text-sm text-fg-dim">Tanpa screenshot</span>
          )}
        </div>
        <div className="flex flex-col gap-4 overflow-auto p-5 text-sm">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs text-fg-muted">Modul {module}</div>
              <h3 className="text-lg font-semibold">{s.page_name}</h3>
            </div>
            <button type="button" aria-label="Tutup" onClick={onClose} className="rounded-md p-1.5 text-fg-muted hover:bg-ink-850">
              <X />
            </button>
          </div>
          {s.purpose && <p className="text-fg-muted">{s.purpose}</p>}
          <Detail label="Form">{s.forms.length ? s.forms.join(", ") : "Tidak ada form"}</Detail>
          {s.actions.length > 0 && (
            <Detail label="Aksi di layar ini">
              <ul className="list-disc pl-4">
                {s.actions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </Detail>
          )}
          <Detail label="Akses">{s.public ? "Bisa dibuka tanpa login" : "Perlu login"}</Detail>
          <Detail label="Lokasi">
            <span className="break-all font-mono text-xs">{s.url}</span>
          </Detail>
          {testHref && (
            <Link
              to={testHref}
              className="mt-auto inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-white hover:bg-accent-hover"
            >
              <Target />
              Uji modul {module}
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-fg-muted">{label}</div>
      <div>{children}</div>
    </div>
  );
}
