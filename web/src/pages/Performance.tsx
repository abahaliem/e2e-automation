import { ChartLineUp, DownloadSimple, FloppyDisk, Play, Plus, Stop, Trash, Warning } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Alert, Button, Card, EmptyState, Field, Input, PageHeader, Select, Skeleton, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import type { PerfPoint, PerfRequestCfg, PerfRun, PerfTest, PerfTestInput } from "@/lib/types";

const METHODS: PerfRequestCfg["method"][] = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"];
const emptyRequest = (): PerfRequestCfg => ({ name: "", method: "GET", url: "", headers: {}, body: "", weight: 1, expect_status: null });
const blank = (): PerfTestInput => ({
  name: "",
  requests: [emptyRequest()],
  profile: { vus: 10, duration_s: 60, ramp_up_s: 10, think_ms: 500 },
  thresholds: { p95_ms: 1000, error_rate_pct: 1 },
  environment: "dev",
  approved_hosts: [],
  secret_headers: "",
});
const headersText = (h: Record<string, string>) => Object.entries(h).map(([k, v]) => `${k}: ${v}`).join("\n");
const parseHeaders = (text: string) =>
  Object.fromEntries(
    text
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.includes(":"))
      .map((l) => [l.slice(0, l.indexOf(":")).trim(), l.slice(l.indexOf(":") + 1).trim()]),
  );

/** Uji beban HTTP: skenario per aplikasi, grafik live, hasil per request, unduh Excel. */
export function PerformancePage() {
  const [params, setParams] = useSearchParams();
  const apps = useQuery({ queryKey: ["apps"], queryFn: api.listApps });
  const appId = Number(params.get("app")) || apps.data?.[0]?.id || null;
  const tests = useQuery({ queryKey: ["perf-tests", appId], queryFn: () => api.listPerfTests(appId!), enabled: !!appId });
  const [selected, setSelected] = useState<number | "new" | null>(null);
  useEffect(() => setSelected(null), [appId]);
  const list = tests.data ?? [];
  const current = typeof selected === "number" ? list.find((t) => t.id === selected) ?? null : null;
  const active = selected ?? (list[0]?.id ?? "new");

  return (
    <main className="flex flex-col gap-6 px-10 py-8">
      <PageHeader
        title="Performance"
        description="Uji beban HTTP: banyak pengguna virtual mengakses endpoint aplikasi bersamaan, lalu dinilai dari waktu respons dan error."
        actions={
          <Select aria-label="Aplikasi" className="w-60" value={appId ?? ""} onChange={(e) => setParams({ app: e.target.value })}>
            {(apps.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        }
      />
      {!apps.isLoading && !apps.data?.length ? (
        <Card>
          <EmptyState title="Belum ada aplikasi" description="Tambahkan aplikasi di menu Aplikasi terlebih dulu." />
        </Card>
      ) : (
        <div className="grid grid-cols-[260px_minmax(0,1fr)] gap-8">
          <aside className="flex flex-col gap-3">
            <Button onClick={() => setSelected("new")}>
              <Plus />
              Uji beban baru
            </Button>
            {tests.isLoading ? (
              <Skeleton className="h-24" />
            ) : (
              <div className="divide-y divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
                {list.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setSelected(t.id)}
                    className={cn("block w-full p-3 text-left text-sm", active === t.id && "bg-accent-soft")}
                  >
                    <div className="font-medium">{t.name}</div>
                    <div className="text-xs text-fg-muted">
                      {t.config.profile.vus} user · {t.config.profile.duration_s} detik · {t.config.requests.length} request
                    </div>
                  </button>
                ))}
                {!list.length && <p className="p-3 text-sm text-fg-muted">Belum ada skenario.</p>}
              </div>
            )}
          </aside>
          <section className="flex min-w-0 flex-col gap-6">
            {appId && active === "new" && <PerfEditor key={`new-${appId}`} appId={appId} test={null} onSaved={(t) => setSelected(t.id)} />}
            {appId && current && typeof active === "number" && (
              <>
                <PerfEditor key={current.id} appId={appId} test={current} onSaved={() => undefined} onDeleted={() => setSelected(null)} />
                <PerfRuns test={current} />
              </>
            )}
            {appId && !current && typeof active === "number" && list[0] && (
              <>
                <PerfEditor key={list[0].id} appId={appId} test={list[0]} onSaved={() => undefined} onDeleted={() => setSelected(null)} />
                <PerfRuns test={list[0]} />
              </>
            )}
          </section>
        </div>
      )}
    </main>
  );
}

function PerfEditor({ appId, test, onSaved, onDeleted }: { appId: number; test: PerfTest | null; onSaved: (t: PerfTest) => void; onDeleted?: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<PerfTestInput>(() => (test ? { ...test.config, name: test.name, secret_headers: "" } : blank()));
  const [headerTexts, setHeaderTexts] = useState<string[]>(() => form.requests.map((r) => headersText(r.headers)));
  const [curl, setCurl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [hostToApprove, setHostToApprove] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const set = <K extends keyof PerfTestInput>(k: K, v: PerfTestInput[K]) => {
    setSaved(false);
    setForm((f) => ({ ...f, [k]: v }));
  };
  const setReq = (i: number, patch: Partial<PerfRequestCfg>) => set("requests", form.requests.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const save = useMutation({
    mutationFn: (approve?: string) => {
      const body: PerfTestInput = {
        ...form,
        requests: form.requests.map((r, i) => ({ ...r, name: r.name.trim() || r.url, headers: parseHeaders(headerTexts[i] ?? "") })),
        approved_hosts: approve ? [...form.approved_hosts, approve] : form.approved_hosts,
      };
      if (test && !form.secret_headers?.trim()) delete body.secret_headers; // kosong saat ubah = tidak diganti
      return test ? api.updatePerfTest(test.id, body) : api.createPerfTest(appId, body);
    },
    onSuccess: (t) => {
      setError(null);
      setHostToApprove(null);
      setSaved(true);
      setForm((f) => ({ ...f, approved_hosts: t.config.approved_hosts, secret_headers: "" }));
      qc.invalidateQueries({ queryKey: ["perf-tests", appId] });
      onSaved(t);
    },
    onError: (e) => {
      const message = e instanceof ApiError ? Object.values(e.fieldErrors)[0] ?? e.message : String(e);
      setError(message);
      const host = /^Host (\S+) bukan domain/.exec(message)?.[1];
      setHostToApprove(host ?? null);
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deletePerfTest(test!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["perf-tests", appId] });
      onDeleted?.();
    },
  });
  const importCurl = useMutation({
    mutationFn: () => api.importCurl(curl),
    onSuccess: ({ request, secret_headers }) => {
      const blankFirst = form.requests.length === 1 && !form.requests[0].url;
      set("requests", blankFirst ? [request] : [...form.requests, request]);
      setHeaderTexts((h) => (blankFirst ? [headersText(request.headers)] : [...h, headersText(request.headers)]));
      if (secret_headers) set("secret_headers", secret_headers);
      setCurl("");
      setError(null);
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return setError("Nama uji wajib diisi");
    if (form.requests.some((r) => !/^https?:\/\//.test(r.url.trim()))) return setError("Setiap request butuh URL yang diawali http:// atau https://");
    save.mutate(undefined);
  };
  const p = form.profile;
  const t = form.thresholds;
  const num = (v: string) => (v === "" ? null : Number(v));

  return (
    <Card className="p-6">
      <form onSubmit={submit} noValidate className="flex flex-col gap-5">
        <div className="flex items-start justify-between gap-4">
          <h2 className="flex items-center gap-2 font-semibold">
            <ChartLineUp className="text-accent" />
            {test ? test.name : "Uji beban baru"}
          </h2>
          <div role="radiogroup" aria-label="Environment" className="inline-flex rounded-lg border border-ink-700 p-1 text-sm">
            {(["dev", "production"] as const).map((env) => (
              <button key={env} type="button" role="radio" aria-checked={form.environment === env} onClick={() => set("environment", env)}
                className={cn("rounded-md px-3 py-1", form.environment === env ? "bg-ink-800 font-medium" : "text-fg-muted")}>
                {env === "dev" ? "Dev / UAT" : "Production"}
              </button>
            ))}
          </div>
        </div>
        {form.environment === "production" && (
          <Alert tone="warning">Uji beban ke Production bisa memperlambat atau menjatuhkan layanan untuk pengguna nyata. Jalankan di luar jam sibuk dan atas izin pemilik sistem.</Alert>
        )}
        <Field label="Nama uji" htmlFor="pf-name">
          <Input id="pf-name" value={form.name} placeholder="Daftar work order, 50 user" onChange={(e) => set("name", e.target.value)} />
        </Field>

        <div className="flex flex-col gap-3">
          <span className="text-sm font-medium">Request</span>
          {form.requests.map((r, i) => (
            <div key={i} className="flex flex-col gap-3 rounded-lg border border-ink-700 p-4">
              <div className="grid grid-cols-[minmax(0,1fr)_110px_minmax(0,2fr)_80px_auto] items-end gap-3">
                <Field label="Nama" htmlFor={`pr-name-${i}`}>
                  <Input id={`pr-name-${i}`} value={r.name} placeholder="Daftar WO" onChange={(e) => setReq(i, { name: e.target.value })} />
                </Field>
                <Field label="Method" htmlFor={`pr-method-${i}`}>
                  <Select id={`pr-method-${i}`} value={r.method} onChange={(e) => setReq(i, { method: e.target.value as PerfRequestCfg["method"] })}>
                    {METHODS.map((m) => (
                      <option key={m}>{m}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="URL" htmlFor={`pr-url-${i}`}>
                  <Input id={`pr-url-${i}`} className="font-mono" value={r.url} placeholder="https://dev-api.kantor.local/wo" onChange={(e) => setReq(i, { url: e.target.value })} />
                </Field>
                <Field label="Bobot" htmlFor={`pr-weight-${i}`}>
                  <Input id={`pr-weight-${i}`} type="number" min={1} value={r.weight} onChange={(e) => setReq(i, { weight: Math.max(1, Number(e.target.value) || 1) })} />
                </Field>
                <Button variant="ghost" aria-label={`Hapus request ${i + 1}`} disabled={form.requests.length === 1}
                  onClick={() => { set("requests", form.requests.filter((_, j) => j !== i)); setHeaderTexts((h) => h.filter((_, j) => j !== i)); }}>
                  <Trash />
                </Button>
              </div>
              {r.method !== "GET" && r.method !== "HEAD" && (
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Body" htmlFor={`pr-body-${i}`}>
                    <Textarea id={`pr-body-${i}`} rows={2} className="font-mono" value={r.body} onChange={(e) => setReq(i, { body: e.target.value })} />
                  </Field>
                  <Field label="Header (bukan rahasia)" htmlFor={`pr-headers-${i}`}>
                    <Textarea id={`pr-headers-${i}`} rows={2} className="font-mono" placeholder="Content-Type: application/json" value={headerTexts[i] ?? ""}
                      onChange={(e) => {
                        const value = e.target.value;
                        setHeaderTexts((h) => {
                          const next = [...h];
                          next[i] = value;
                          return next;
                        });
                      }} />
                  </Field>
                </div>
              )}
            </div>
          ))}
          <div className="flex gap-2">
            <Button size="sm" onClick={() => { set("requests", [...form.requests, emptyRequest()]); setHeaderTexts((h) => [...h, ""]); }}>
              <Plus />
              Tambah request
            </Button>
          </div>
          <Field label="Atau tempel perintah cURL" htmlFor="pf-curl" hint="Dari DevTools (Copy as cURL) atau Postman. Header Authorization/Cookie/token otomatis dipindah ke header rahasia.">
            <div className="flex gap-2">
              <Textarea id="pf-curl" rows={2} className="font-mono" value={curl} placeholder="curl 'https://dev-api.kantor.local/wo' -H 'Authorization: Bearer ...'" onChange={(e) => setCurl(e.target.value)} />
              <Button onClick={() => importCurl.mutate()} disabled={!curl.trim() || importCurl.isPending}>
                Tambahkan
              </Button>
            </div>
          </Field>
          <Field label="Header rahasia untuk semua request" htmlFor="pf-secret"
            hint={test?.has_secret_headers ? "Tersimpan terenkripsi. Kosongkan bila tidak diganti." : "'Nama: nilai' per baris, mis. Authorization: Bearer ... Disimpan terenkripsi."}>
            <Textarea id="pf-secret" rows={2} className="font-mono" autoComplete="off" value={form.secret_headers ?? ""} onChange={(e) => set("secret_headers", e.target.value)} />
          </Field>
        </div>

        <div className="grid grid-cols-4 gap-4">
          <Field label="Virtual user" htmlFor="pf-vus" hint="Maks 200">
            <Input id="pf-vus" type="number" min={1} max={200} value={p.vus} onChange={(e) => set("profile", { ...p, vus: Number(e.target.value) })} />
          </Field>
          <Field label="Durasi (detik)" htmlFor="pf-duration" hint="Maks 1800">
            <Input id="pf-duration" type="number" min={1} max={1800} value={p.duration_s} onChange={(e) => set("profile", { ...p, duration_s: Number(e.target.value) })} />
          </Field>
          <Field label="Ramp-up (detik)" htmlFor="pf-ramp" hint="User dinyalakan bertahap">
            <Input id="pf-ramp" type="number" min={0} value={p.ramp_up_s} onChange={(e) => set("profile", { ...p, ramp_up_s: Number(e.target.value) })} />
          </Field>
          <Field label="Jeda antar request (ms)" htmlFor="pf-think">
            <Input id="pf-think" type="number" min={0} value={p.think_ms} onChange={(e) => set("profile", { ...p, think_ms: Number(e.target.value) })} />
          </Field>
          <Field label="Ambang p95 (ms)" htmlFor="pf-p95" hint="95% request lebih cepat dari ini">
            <Input id="pf-p95" type="number" min={1} value={t.p95_ms ?? ""} onChange={(e) => set("thresholds", { ...t, p95_ms: num(e.target.value) })} />
          </Field>
          <Field label="Ambang error rate (%)" htmlFor="pf-err">
            <Input id="pf-err" type="number" min={0} max={100} step="0.1" value={t.error_rate_pct ?? ""} onChange={(e) => set("thresholds", { ...t, error_rate_pct: num(e.target.value) })} />
          </Field>
        </div>

        {error && <Alert tone="error">{error}</Alert>}
        {hostToApprove && (
          <Alert tone="warning" action={<Button size="sm" variant="primary" onClick={() => save.mutate(hostToApprove)}>Saya berwenang, simpan</Button>}>
            <Warning className="inline" /> Pastikan Anda berwenang menguji beban <b>{hostToApprove}</b>. Uji beban ke server milik pihak lain tanpa izin bisa melanggar aturan.
          </Alert>
        )}
        {saved && <Alert tone="success">Skenario disimpan.</Alert>}
        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={save.isPending}>
            <FloppyDisk />
            Simpan skenario
          </Button>
          {test && (
            <Button variant="ghost" className="ml-auto text-fail!" onClick={() => remove.mutate()}>
              <Trash />
              Hapus
            </Button>
          )}
        </div>
      </form>
    </Card>
  );
}

function PerfRuns({ test }: { test: PerfTest }) {
  const qc = useQueryClient();
  const runs = useQuery({ queryKey: ["perf-runs", test.id], queryFn: () => api.listPerfRuns(test.id) });
  const [openId, setOpenId] = useState<number | null>(null);
  const [confirmProd, setConfirmProd] = useState(false);
  const start = useMutation({
    mutationFn: () => api.runPerfTest(test.id, confirmProd),
    onSuccess: (r) => {
      setOpenId(r.id);
      setConfirmProd(false);
      qc.invalidateQueries({ queryKey: ["perf-runs", test.id] });
    },
  });
  const list = runs.data ?? [];
  const shown = openId ?? list[0]?.id ?? null;
  const prod = test.config.environment === "production";
  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">Jalankan & hasil</h2>
        <div className="flex items-center gap-3">
          {prod && (
            <label className="flex items-center gap-2 text-sm text-review">
              <input type="checkbox" checked={confirmProd} onChange={(e) => setConfirmProd(e.target.checked)} />
              Saya paham risikonya ke Production
            </label>
          )}
          <Button variant="primary" onClick={() => start.mutate()} disabled={start.isPending || (prod && !confirmProd)}>
            <Play weight="fill" />
            Jalankan uji beban
          </Button>
        </div>
      </div>
      {start.error && <Alert tone="error">{(start.error as Error).message}</Alert>}
      {shown && <PerfRunView runId={shown} onFinished={() => qc.invalidateQueries({ queryKey: ["perf-runs", test.id] })} />}
      {list.length > 0 && (
        <table className="w-full text-sm">
          <thead className="border-b border-ink-700 text-left text-xs text-fg-muted">
            <tr>
              <th className="py-2 font-medium">Waktu</th>
              <th className="font-medium">Request</th>
              <th className="font-medium">RPS</th>
              <th className="font-medium">p95</th>
              <th className="font-medium">Error</th>
              <th className="font-medium">Hasil</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-700">
            {list.map((r) => (
              <tr key={r.id} className={cn("cursor-pointer hover:bg-ink-850", shown === r.id && "bg-accent-soft")} onClick={() => setOpenId(r.id)}>
                <td className="py-2">{formatDateTime(r.started_at)}</td>
                <td>{r.summary?.total ?? "-"}</td>
                <td>{r.summary?.rps ?? "-"}</td>
                <td>{r.summary ? `${r.summary.p95_ms} ms` : "-"}</td>
                <td>{r.summary ? `${r.summary.error_rate_pct}%` : "-"}</td>
                <td>
                  {r.status === "running" ? (
                    <span className="text-accent">Berjalan</span>
                  ) : r.status === "failed" ? (
                    <span className="text-fail">Gagal jalan</span>
                  ) : r.passed ? (
                    <span className="text-pass">Lulus</span>
                  ) : (
                    <span className="text-fail">Tidak lulus</span>
                  )}
                  {r.status === "stopped" && <span className="ml-1 text-xs text-fg-muted">(dihentikan)</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function PerfRunView({ runId, onFinished }: { runId: number; onFinished: () => void }) {
  const run = useQuery({
    queryKey: ["perf-run", runId],
    queryFn: () => api.getPerfRun(runId),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1000 : false),
  });
  const status = run.data?.status;
  useEffect(() => {
    if (status && status !== "running") onFinished();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);
  const stop = useMutation({ mutationFn: () => api.stopPerfRun(runId) });
  if (!run.data) return <Skeleton className="h-48" />;
  const r: PerfRun = run.data;
  const timeline = r.result?.timeline ?? [];
  const s = r.result?.summary;
  const last = timeline[timeline.length - 1];
  return (
    <div className="flex flex-col gap-4 rounded-lg border border-ink-700 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm">
          {r.status === "running" ? (
            <span className="font-medium text-accent">Berjalan… {last ? `${last.elapsed_s} dtk · ${last.vus} user aktif · ${last.total} request` : "menyiapkan"}</span>
          ) : r.result?.verdict ? (
            <span className={cn("font-semibold", r.result.verdict.passed ? "text-pass" : "text-fail")}>
              {r.result.verdict.passed ? "LULUS" : "TIDAK LULUS"}
            </span>
          ) : (
            <span className="text-fail">{r.note || "Selesai"}</span>
          )}
          {r.note && r.status !== "running" && <span className="ml-2 text-fg-muted">{r.note}</span>}
        </div>
        <div className="flex gap-2">
          {r.status === "running" ? (
            <Button variant="danger" size="sm" onClick={() => stop.mutate()} disabled={stop.isPending}>
              <Stop />
              Hentikan
            </Button>
          ) : (
            <a href={api.perfXlsxUrl(runId)} download className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-ink-600 px-2.5 text-xs hover:bg-ink-850">
              <DownloadSimple />
              Excel
            </a>
          )}
        </div>
      </div>
      {s && (
        <div className="grid grid-cols-6 gap-3 text-center">
          {[
            ["Request", s.total],
            ["Req/detik", s.rps],
            ["p50", `${s.p50_ms} ms`],
            ["p95", `${s.p95_ms} ms`],
            ["p99", `${s.p99_ms} ms`],
            ["Error", `${s.error_rate_pct}%`],
          ].map(([label, value]) => (
            <div key={label as string} className="rounded-lg border border-ink-700 py-2">
              <div className="text-lg font-semibold">{value}</div>
              <div className="text-xs text-fg-muted">{label}</div>
            </div>
          ))}
        </div>
      )}
      {timeline.length > 1 && (
        <div className="grid grid-cols-2 gap-4">
          <LineChart title="Request per detik" points={timeline} pick={(p) => p.rps} color="var(--color-accent)" />
          <LineChart title="p95 latency (ms)" points={timeline} pick={(p) => p.p95_ms} color="var(--color-review)" />
        </div>
      )}
      {r.result?.verdict && r.result.verdict.checks.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          {r.result.verdict.checks.map((c) => (
            <span key={c.name} className={cn("rounded-md border px-2 py-1", c.passed ? "border-pass/40 text-pass" : "border-fail/40 text-fail")}>
              {c.name}: {c.actual} (target {c.target})
            </span>
          ))}
        </div>
      )}
      {r.result?.requests && (
        <table className="w-full text-sm">
          <thead className="border-b border-ink-700 text-left text-xs text-fg-muted">
            <tr>
              <th className="py-2 font-medium">Request</th>
              <th className="font-medium">Jumlah</th>
              <th className="font-medium">p50</th>
              <th className="font-medium">p95</th>
              <th className="font-medium">Error</th>
              <th className="font-medium">Kode status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-700">
            {r.result.requests.map((q) => (
              <tr key={q.name}>
                <td className="py-2">
                  <span className="font-medium">{q.name}</span> <span className="font-mono text-xs text-fg-dim">{q.method}</span>
                </td>
                <td>{q.count}</td>
                <td>{q.p50_ms} ms</td>
                <td>{q.p95_ms} ms</td>
                <td className={cn(q.errors ? "text-fail" : "")}>{q.error_rate_pct}%</td>
                <td className="text-xs text-fg-muted">{Object.entries(q.status_codes).map(([k, v]) => `${k}: ${v}`).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Grafik garis sederhana (SVG) untuk timeline per detik. */
function LineChart({ title, points, pick, color }: { title: string; points: PerfPoint[]; pick: (p: PerfPoint) => number; color: string }) {
  const W = 320;
  const H = 110;
  const values = points.map(pick);
  const max = Math.max(...values, 1);
  const maxT = Math.max(...points.map((p) => p.elapsed_s), 1);
  const path = points
    .map((p, i) => `${i ? "L" : "M"}${((p.elapsed_s / maxT) * (W - 10) + 5).toFixed(1)},${(H - 15 - (pick(p) / max) * (H - 30)).toFixed(1)}`)
    .join(" ");
  return (
    <figure className="rounded-lg border border-ink-700 p-3">
      <figcaption className="mb-1 flex justify-between text-xs text-fg-muted">
        <span>{title}</span>
        <span>maks {Math.round(max * 10) / 10}</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title} className="h-28 w-full">
        <line x1="5" y1={H - 15} x2={W - 5} y2={H - 15} stroke="currentColor" className="text-ink-700" />
        <path d={path} fill="none" stroke={color} strokeWidth="2" />
        <text x="5" y={H - 2} className="fill-current text-[9px] text-fg-dim">0 dtk</text>
        <text x={W - 5} y={H - 2} textAnchor="end" className="fill-current text-[9px] text-fg-dim">{maxT} dtk</text>
      </svg>
    </figure>
  );
}
