import { DownloadSimple, FloppyDisk, Plus, Trash } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AccountsPanel } from "@/components/AccountsPanel";
import { FlowsPanel } from "@/components/FlowsPanel";
import { HooksPanel, TestDataPanel } from "@/components/TestDataPanel";
import { PlatformIcon } from "@/components/RunBits";
import { Alert, Button, Card, EmptyState, Field, Input, PageHeader, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { App } from "@/lib/types";

const splitList = (text: string) =>
  text
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);

export function AppsPage() {
  const [params] = useSearchParams();
  const apps = useQuery({ queryKey: ["apps"], queryFn: api.listApps });
  const [selected, setSelected] = useState<number | "new" | null>(null);

  useEffect(() => {
    if (selected !== null || !apps.data?.length) return;
    const wanted = Number(params.get("app"));
    setSelected(apps.data.some((a) => a.id === wanted) ? wanted : apps.data[0].id);
  }, [apps.data, selected]);

  const list = apps.data ?? [];
  const current = typeof selected === "number" ? list.find((a) => a.id === selected) ?? null : null;

  return (
    <main className="flex flex-col gap-8 px-10 py-8">
      <PageHeader
        title="Aplikasi"
        description="Aplikasi yang diuji, domain yang boleh dibuka agent, dan akun test-nya."
        actions={
          <Button variant="primary" onClick={() => setSelected("new")}>
            <Plus />
            Tambah aplikasi
          </Button>
        }
      />
      <div className="grid grid-cols-[300px_minmax(0,1fr)] gap-8">
        <aside className="flex flex-col gap-2">
          {apps.isLoading ? (
            <>
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </>
          ) : list.length === 0 ? (
            <Card>
              <EmptyState title="Belum ada aplikasi" description="Tambahkan URL aplikasi web yang ingin diuji." />
            </Card>
          ) : (
            list.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => setSelected(a.id)}
                className={cn(
                  "rounded-xl border p-4 text-left transition-colors",
                  selected === a.id ? "border-accent-line bg-accent-soft" : "border-ink-700 bg-ink-900 hover:bg-ink-850",
                )}
              >
                <div className="flex items-center gap-2 font-medium">
                  <PlatformIcon platform={a.platform} />
                  {a.name}
                </div>
                <div className="mt-1 truncate font-mono text-xs text-fg-dim">{a.url}</div>
                <div className="mt-2 text-xs text-fg-muted">
                  {a.explored ? "Sudah dipetakan" : "Belum dipetakan"} · {a.accounts} akun
                </div>
              </button>
            ))
          )}
        </aside>

        <section className="flex min-w-0 flex-col gap-6">
          {selected === "new" && <AppForm key="new" app={null} onSaved={(a) => setSelected(a.id)} />}
          {current && (
            <>
              <AppForm key={current.id} app={current} onSaved={() => undefined} onDeleted={() => setSelected(null)} />
              <Card className="flex flex-col gap-4 p-6">
                <div>
                  <h2 className="font-semibold">Akun test</h2>
                  <p className="mt-1 text-sm text-fg-muted">Dipakai agent untuk login. Tanpa OTP atau captcha.</p>
                </div>
                <AccountsPanel appId={current.id} />
              </Card>
              <FlowsPanel app={current} />
              <TestDataPanel app={current} />
              <HooksPanel app={current} />
              <ImportRuns app={current} />
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function AppForm({ app, onSaved, onDeleted }: { app: App | null; onSaved: (a: App) => void; onDeleted?: () => void }) {
  const qc = useQueryClient();
  const isAndroid = app?.platform === "android";
  const [name, setName] = useState(app?.name ?? "");
  const [url, setUrl] = useState(app?.url ?? "");
  const [domains, setDomains] = useState((app?.allowed_domains ?? []).join(", "));
  const [loginEndpoints, setLoginEndpoints] = useState((app?.login_endpoints ?? []).join(", "));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), url: url.trim(), allowed_domains: splitList(domains), login_endpoints: splitList(loginEndpoints) };
      return app ? api.updateApp(app.id, body) : api.createApp(body);
    },
    onSuccess: (a) => {
      setErrors({});
      setNotice("Aplikasi disimpan");
      qc.invalidateQueries({ queryKey: ["apps"] });
      onSaved(a);
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors(Object.keys(e.fieldErrors).length ? e.fieldErrors : { _: e.message });
    },
  });
  const [confirming, setConfirming] = useState(false);
  const appRuns = useQuery({
    queryKey: ["runs", "app", app?.id],
    queryFn: () => api.listRuns({ app_id: app!.id, limit: 500 }),
    enabled: confirming && !!app,
  });
  const remove = useMutation({
    mutationFn: () => api.deleteApp(app!.id, true),
    onSuccess: () => {
      setConfirming(false);
      qc.invalidateQueries({ queryKey: ["apps"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      onDeleted?.();
    },
    onError: (e) => setErrors({ _: e instanceof Error ? e.message : String(e) }),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setNotice(null);
    const next: Record<string, string> = {};
    if (!name.trim()) next.name = "Wajib diisi";
    if (isAndroid) {
      if (!/^android:\/\/[A-Za-z]\w*(\.[A-Za-z_]\w*)+$/.test(url.trim()))
        next.url = "Paket aplikasi Android tidak valid (contoh: android://com.perusahaan.aplikasi)";
    } else if (!/^https?:\/\//.test(url.trim())) next.url = "URL harus diawali http:// atau https://";
    setErrors(next);
    if (Object.keys(next).length === 0) save.mutate();
  };

  return (
    <Card className="p-6">
      <form onSubmit={submit} noValidate className="flex flex-col gap-5">
        <h2 className="font-semibold">{app ? "Detail aplikasi" : "Aplikasi baru"}</h2>
        <div className="grid grid-cols-2 gap-5">
          <Field label="Nama aplikasi" htmlFor="app-name" error={errors.name}>
            <Input id="app-name" value={name} placeholder="Web HR" onChange={(e) => setName(e.target.value)} aria-invalid={!!errors.name} />
          </Field>
          <Field label={isAndroid ? "Paket aplikasi Android" : "URL aplikasi"} htmlFor="app-url" error={errors.url}>
            <Input
              id="app-url"
              className="font-mono"
              value={url}
              placeholder={isAndroid ? "android://com.perusahaan.aplikasi" : "https://hr-dev.kantor.local"}
              onChange={(e) => setUrl(e.target.value)}
              aria-invalid={!!errors.url}
            />
          </Field>
          {!isAndroid && (
          <>
          <Field
            label="Domain yang boleh dibuka"
            htmlFor="app-domains"
            hint="Pisahkan dengan koma. Kosongkan untuk memakai domain dari URL saja."
            error={errors.allowed_domains}
          >
            <Input id="app-domains" className="font-mono" value={domains} placeholder="hr-dev.kantor.local, sso.kantor.local" onChange={(e) => setDomains(e.target.value)} />
          </Field>
          <Field
            label="Endpoint login (opsional)"
            htmlFor="app-login"
            hint="Untuk mode production: endpoint yang tetap boleh POST saat login, mis. /api/auth/login"
            error={errors.login_endpoints}
          >
            <Input id="app-login" className="font-mono" value={loginEndpoints} placeholder="/api/auth/login" onChange={(e) => setLoginEndpoints(e.target.value)} />
          </Field>
          </>
          )}
        </div>
        {errors._ && <Alert tone="error">{errors._}</Alert>}
        {notice && <Alert tone="success">{notice}</Alert>}
        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={save.isPending}>
            <FloppyDisk />
            Simpan aplikasi
          </Button>
          {app && (
            <Link to={`/runs/new?app=${app.id}`} className="text-sm text-accent">
              Jalankan pengujian
            </Link>
          )}
          {app && !confirming && (
            <Button variant="ghost" className="ml-auto text-fail! hover:bg-fail/5" onClick={() => { setErrors({}); setConfirming(true); }}>
              <Trash />
              Hapus
            </Button>
          )}
        </div>
        {app && confirming && (
          <div role="alertdialog" aria-label="Konfirmasi hapus aplikasi" className="flex flex-col gap-3 rounded-lg border border-fail/40 bg-fail/5 p-4 text-sm">
            <div className="font-medium text-fail">Hapus aplikasi {app.name} secara permanen?</div>
            <div className="text-fg-muted">
              Ikut terhapus:{" "}
              {appRuns.isLoading
                ? "menghitung riwayat run..."
                : `${appRuns.data?.length ?? 0} riwayat run beserta screenshot dan dokumennya`}
              , akun test, alur bisnis, data uji, dan persiapan otomatis. Tindakan ini tidak bisa dibatalkan.
            </div>
            <div className="flex gap-2">
              <Button variant="danger" disabled={remove.isPending || appRuns.isLoading} onClick={() => remove.mutate()}>
                <Trash />
                {remove.isPending ? "Menghapus..." : "Ya, hapus permanen"}
              </Button>
              <Button onClick={() => setConfirming(false)}>Batal</Button>
            </div>
          </div>
        )}
      </form>
    </Card>
  );
}

function ImportRuns({ app }: { app: App }) {
  const qc = useQueryClient();
  const [folder, setFolder] = useState("");
  const importer = useMutation({
    mutationFn: () => api.importRuns(folder, app.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
  return (
    <Card className="flex flex-col gap-4 p-6">
      <div>
        <h2 className="font-semibold">Impor run lama</h2>
        <p className="mt-1 text-sm text-fg-muted">Masukkan folder runs/ dari CLI qa-agent supaya hasilnya muncul di Riwayat dan Dashboard.</p>
      </div>
      <div className="flex gap-3">
        <Input aria-label="Folder run lama" className="font-mono" value={folder} placeholder="D:\proyek\runs" onChange={(e) => setFolder(e.target.value)} />
        <Button onClick={() => importer.mutate()} disabled={!folder.trim() || importer.isPending}>
          <DownloadSimple />
          Impor
        </Button>
      </div>
      {importer.data && (
        <Alert tone={importer.data.failed.length ? "warning" : "success"}>
          {importer.data.imported} run diimpor
          {importer.data.failed.length ? `, ${importer.data.failed.length} gagal` : ""}.
        </Alert>
      )}
      {importer.error && <Alert tone="error">{(importer.error as Error).message}</Alert>}
    </Card>
  );
}
