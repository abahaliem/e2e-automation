import { CaretDown, CaretRight, DownloadSimple, FloppyDisk, Lightning, Play, Plus, Sparkle, Stop, Trash, Warning } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Alert, Button, Card, EmptyState, Field, Input, PageHeader, Select, Skeleton, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import type { ApiAssertion, ApiAssertionKind, ApiAssertionOp, ApiCaseCfg, ApiCaseResult, ApiImport, ApiMethod, ApiRun, ApiSuite, ApiSuiteInput } from "@/lib/types";

const METHODS: ApiMethod[] = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"];
const KINDS: [ApiAssertionKind, string][] = [["status", "Status HTTP"], ["json", "Isi JSON"], ["time", "Waktu respons (ms)"], ["body", "Body (teks)"], ["header", "Header"]];
const OPS: [ApiAssertionOp, string][] = [["eq", "="], ["ne", "≠"], ["contains", "mengandung"], ["lt", "<"], ["gt", ">"], ["exists", "ada"], ["not_exists", "tidak ada"], ["type", "bertipe"]];
const needsPath = (k: ApiAssertionKind) => k === "json" || k === "header";
const noValue = (op: ApiAssertionOp) => op === "exists" || op === "not_exists";

const emptyCase = (): ApiCaseCfg => ({
  name: "",
  method: "GET",
  url: "{{base_url}}/",
  headers: {},
  body: "",
  assertions: [{ kind: "status", op: "eq", expected: "200", path: "" }],
  capture: {},
});
const blank = (): ApiSuiteInput => ({ name: "", base_url: "", environment: "dev", approved_hosts: [], variables: {}, cases: [emptyCase()], secret_headers: "" });
const pairsText = (h: Record<string, string>, sep: string) => Object.entries(h).map(([k, v]) => `${k}${sep}${v}`).join("\n");
const parsePairs = (text: string, sep: string) =>
  Object.fromEntries(
    text
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.includes(sep))
      .map((l) => [l.slice(0, l.indexOf(sep)).trim(), l.slice(l.indexOf(sep) + sep.length).trim()]),
  );

/** API testing: suite per aplikasi, impor Postman/OpenAPI/cURL, susun dengan AI, jalankan, hasil per test case & Excel. */
export function ApiTestingPage() {
  const [params, setParams] = useSearchParams();
  const apps = useQuery({ queryKey: ["apps"], queryFn: api.listApps });
  const appId = Number(params.get("app")) || apps.data?.[0]?.id || null;
  const suites = useQuery({ queryKey: ["api-suites", appId], queryFn: () => api.listApiSuites(appId!), enabled: !!appId });
  const [selected, setSelected] = useState<number | "new" | null>(null);
  useEffect(() => setSelected(null), [appId]);
  const list = suites.data ?? [];
  const active = selected ?? list[0]?.id ?? "new";
  const current = typeof active === "number" ? list.find((s) => s.id === active) ?? null : null;

  return (
    <main className="flex flex-col gap-6 px-10 py-8">
      <PageHeader
        title="API Test"
        description="Uji endpoint API langsung: cek status, isi JSON, dan waktu respons. Nilai dari satu respons bisa dipakai request berikutnya."
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
              Suite API baru
            </Button>
            {suites.isLoading ? (
              <Skeleton className="h-24" />
            ) : (
              <div className="divide-y divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
                {list.map((s) => (
                  <button key={s.id} type="button" onClick={() => setSelected(s.id)}
                    className={cn("block w-full p-3 text-left text-sm", active === s.id && "bg-accent-soft")}>
                    <div className="font-medium">{s.name}</div>
                    <div className="text-xs text-fg-muted">
                      {s.config.cases.length} test case · {s.config.environment === "production" ? "Production" : "Dev / UAT"}
                    </div>
                  </button>
                ))}
                {!list.length && <p className="p-3 text-sm text-fg-muted">Belum ada suite.</p>}
              </div>
            )}
          </aside>
          <section className="flex min-w-0 flex-col gap-6">
            {appId && active === "new" && <SuiteEditor key={`new-${appId}`} appId={appId} suite={null} onSaved={(s) => setSelected(s.id)} />}
            {appId && current && (
              <>
                <SuiteEditor key={current.id} appId={appId} suite={current} onSaved={() => undefined} onDeleted={() => setSelected(null)} />
                <SuiteRuns suite={current} />
              </>
            )}
          </section>
        </div>
      )}
    </main>
  );
}

type Drafts = { headers: string[]; capture: string[] };
const draftsOf = (cases: ApiCaseCfg[]): Drafts => ({ headers: cases.map((c) => pairsText(c.headers, ": ")), capture: cases.map((c) => pairsText(c.capture, " = ")) });

function SuiteEditor({ appId, suite, onSaved, onDeleted }: { appId: number; suite: ApiSuite | null; onSaved: (s: ApiSuite) => void; onDeleted?: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<ApiSuiteInput>(() => (suite ? { ...suite.config, name: suite.name, secret_headers: "" } : blank()));
  const [drafts, setDrafts] = useState<Drafts>(() => draftsOf(form.cases));
  const [open, setOpen] = useState<number | null>(suite ? null : 0);
  const [varsText, setVarsText] = useState(() => pairsText(form.variables, " = "));
  const [error, setError] = useState<string | null>(null);
  const [hostToApprove, setHostToApprove] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const set = <K extends keyof ApiSuiteInput>(k: K, v: ApiSuiteInput[K]) => {
    setSaved(false);
    setForm((f) => ({ ...f, [k]: v }));
  };
  const setCase = (i: number, patch: Partial<ApiCaseCfg>) => set("cases", form.cases.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const setDraft = (key: keyof Drafts, i: number, value: string) =>
    setDrafts((d) => ({ ...d, [key]: d[key].map((x, j) => (j === i ? value : x)) }));
  const setAssert = (i: number, k: number, patch: Partial<ApiAssertion>) =>
    setCase(i, { assertions: form.cases[i].assertions.map((a, j) => (j === k ? { ...a, ...patch } : a)) });
  const removeCase = (i: number) => {
    set("cases", form.cases.filter((_, j) => j !== i));
    setDrafts((d) => ({ headers: d.headers.filter((_, j) => j !== i), capture: d.capture.filter((_, j) => j !== i) }));
    setOpen(null);
  };
  const addCases = (imported: ApiImport, replaceBlank = true) => {
    const blankOnly = replaceBlank && form.cases.length === 1 && !form.cases[0].name.trim();
    const cases = blankOnly ? imported.cases : [...form.cases, ...imported.cases];
    setForm((f) => ({
      ...f,
      cases,
      base_url: f.base_url || imported.base_url,
      secret_headers: imported.secret_headers ? imported.secret_headers : f.secret_headers,
    }));
    setDrafts(blankOnly ? draftsOf(imported.cases) : (d) => ({ headers: [...d.headers, ...draftsOf(imported.cases).headers], capture: [...d.capture, ...draftsOf(imported.cases).capture] }));
    setSaved(false);
    setError(null);
  };

  const save = useMutation({
    mutationFn: (approve?: string) => {
      const body: ApiSuiteInput = {
        ...form,
        variables: parsePairs(varsText, "="),
        cases: form.cases.map((c, i) => ({
          ...c,
          name: c.name.trim() || `${c.method} ${c.url}`,
          headers: parsePairs(drafts.headers[i] ?? "", ":"),
          capture: parsePairs(drafts.capture[i] ?? "", "="),
        })),
        approved_hosts: approve ? [...form.approved_hosts, approve] : form.approved_hosts,
      };
      if (suite && !form.secret_headers?.trim()) delete body.secret_headers; // kosong saat ubah = tidak diganti
      return suite ? api.updateApiSuite(suite.id, body) : api.createApiSuite(appId, body);
    },
    onSuccess: (s) => {
      setError(null);
      setHostToApprove(null);
      setSaved(true);
      setForm((f) => ({ ...f, approved_hosts: s.config.approved_hosts, secret_headers: "" }));
      qc.invalidateQueries({ queryKey: ["api-suites", appId] });
      onSaved(s);
    },
    onError: (e) => {
      const message = e instanceof ApiError ? Object.values(e.fieldErrors)[0] ?? e.message : String(e);
      setError(message);
      setHostToApprove(/^Host (\S+) bukan domain/.exec(message)?.[1] ?? null);
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteApiSuite(suite!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-suites", appId] });
      onDeleted?.();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return setError("Nama suite wajib diisi");
    if (!form.cases.length) return setError("Tambahkan minimal satu test case");
    if (form.cases.some((c) => c.url.includes("{{base_url}}")) && !/^https?:\/\//.test(form.base_url.trim()))
      return setError("Isi Base URL (diawali http:// atau https://) karena test case memakai {{base_url}}");
    save.mutate(undefined);
  };

  return (
    <Card className="p-6">
      <form onSubmit={submit} noValidate className="flex flex-col gap-5">
        <div className="flex items-start justify-between gap-4">
          <h2 className="flex items-center gap-2 font-semibold">
            <Lightning className="text-accent" />
            {suite ? suite.name : "Suite API baru"}
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
          <Alert tone="warning">Request POST/PUT/PATCH/DELETE ke Production mengubah data nyata. Saat dijalankan, Anda diminta konfirmasi dulu.</Alert>
        )}
        <div className="grid grid-cols-2 gap-4">
          <Field label="Nama suite" htmlFor="as-name">
            <Input id="as-name" value={form.name} placeholder="Work Order API" onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="Base URL" htmlFor="as-base" hint="Dipakai sebagai {{base_url}} di URL test case">
            <Input id="as-base" className="font-mono" value={form.base_url} placeholder="https://dev-api.kantor.local" onChange={(e) => set("base_url", e.target.value)} />
          </Field>
        </div>

        <ImportPanel appId={appId} onImported={addCases} />

        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">Test case ({form.cases.length})</span>
          {form.cases.map((c, i) => (
            <div key={i} className="rounded-lg border border-ink-700">
              <div className="flex items-center gap-2 p-3">
                <button type="button" aria-expanded={open === i} aria-label={`Ubah test case ${i + 1}`} onClick={() => setOpen(open === i ? null : i)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm">
                  {open === i ? <CaretDown /> : <CaretRight />}
                  <span className="w-14 shrink-0 font-mono text-xs text-accent">{c.method}</span>
                  <span className="truncate font-medium">{c.name || "(tanpa nama)"}</span>
                  <span className="truncate font-mono text-xs text-fg-dim">{c.url}</span>
                </button>
                <Button variant="ghost" size="sm" aria-label={`Hapus test case ${i + 1}`} onClick={() => removeCase(i)}>
                  <Trash />
                </Button>
              </div>
              {open === i && (
                <div className="flex flex-col gap-3 border-t border-ink-700 p-4">
                  <div className="grid grid-cols-[minmax(0,1fr)_110px_minmax(0,2fr)] items-end gap-3">
                    <Field label="Skenario" htmlFor={`ac-name-${i}`}>
                      <Input id={`ac-name-${i}`} value={c.name} placeholder="Detail WO valid" onChange={(e) => setCase(i, { name: e.target.value })} />
                    </Field>
                    <Field label="Method" htmlFor={`ac-method-${i}`}>
                      <Select id={`ac-method-${i}`} value={c.method} onChange={(e) => setCase(i, { method: e.target.value as ApiMethod })}>
                        {METHODS.map((m) => (
                          <option key={m}>{m}</option>
                        ))}
                      </Select>
                    </Field>
                    <Field label="URL" htmlFor={`ac-url-${i}`}>
                      <Input id={`ac-url-${i}`} className="font-mono" value={c.url} onChange={(e) => setCase(i, { url: e.target.value })} />
                    </Field>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Body" htmlFor={`ac-body-${i}`} hint="Boleh memakai {{variabel}} dan {{data:nama}}">
                      <Textarea id={`ac-body-${i}`} rows={3} className="font-mono" value={c.body} onChange={(e) => setCase(i, { body: e.target.value })} />
                    </Field>
                    <Field label="Header (bukan rahasia)" htmlFor={`ac-headers-${i}`}>
                      <Textarea id={`ac-headers-${i}`} rows={3} className="font-mono" placeholder="Content-Type: application/json" value={drafts.headers[i] ?? ""}
                        onChange={(e) => setDraft("headers", i, e.target.value)} />
                    </Field>
                  </div>
                  <div className="flex flex-col gap-2">
                    <span className="text-sm font-medium">Pengecekan</span>
                    {c.assertions.map((a, k) => (
                      <div key={k} className="grid grid-cols-[170px_minmax(0,1fr)_130px_minmax(0,1fr)_auto] items-center gap-2">
                        <Select aria-label={`Jenis cek ${k + 1}`} value={a.kind} onChange={(e) => setAssert(i, k, { kind: e.target.value as ApiAssertionKind })}>
                          {KINDS.map(([v, label]) => (
                            <option key={v} value={v}>{label}</option>
                          ))}
                        </Select>
                        <Input aria-label={`Path cek ${k + 1}`} className="font-mono" disabled={!needsPath(a.kind)} value={a.path}
                          placeholder={a.kind === "header" ? "content-type" : needsPath(a.kind) ? "data.status" : "-"} onChange={(e) => setAssert(i, k, { path: e.target.value })} />
                        <Select aria-label={`Operator cek ${k + 1}`} value={a.op} onChange={(e) => setAssert(i, k, { op: e.target.value as ApiAssertionOp })}>
                          {OPS.map(([v, label]) => (
                            <option key={v} value={v}>{label}</option>
                          ))}
                        </Select>
                        <Input aria-label={`Nilai cek ${k + 1}`} disabled={noValue(a.op)} value={a.expected}
                          placeholder={a.kind === "status" ? "200 atau 2xx" : ""} onChange={(e) => setAssert(i, k, { expected: e.target.value })} />
                        <Button variant="ghost" size="sm" aria-label={`Hapus cek ${k + 1}`}
                          onClick={() => setCase(i, { assertions: c.assertions.filter((_, j) => j !== k) })}>
                          <Trash />
                        </Button>
                      </div>
                    ))}
                    <div>
                      <Button size="sm" onClick={() => setCase(i, { assertions: [...c.assertions, { kind: "json", op: "eq", expected: "", path: "" }] })}>
                        <Plus />
                        Tambah cek
                      </Button>
                    </div>
                  </div>
                  <Field label="Simpan nilai respons ke variabel" htmlFor={`ac-capture-${i}`}
                    hint="'nama = path.json' per baris, mis. wo_id = data.id → dipakai sebagai {{wo_id}} di test case berikutnya">
                    <Textarea id={`ac-capture-${i}`} rows={2} className="font-mono" value={drafts.capture[i] ?? ""} onChange={(e) => setDraft("capture", i, e.target.value)} />
                  </Field>
                </div>
              )}
            </div>
          ))}
          <div>
            <Button size="sm" onClick={() => { set("cases", [...form.cases, emptyCase()]); setDrafts((d) => ({ headers: [...d.headers, ""], capture: [...d.capture, ""] })); setOpen(form.cases.length); }}>
              <Plus />
              Tambah test case
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Header rahasia untuk semua request" htmlFor="as-secret"
            hint={suite?.has_secret_headers ? "Tersimpan terenkripsi. Kosongkan bila tidak diganti." : "'Nama: nilai' per baris, mis. Authorization: Bearer ... Disimpan terenkripsi, tidak tampil di hasil."}>
            <Textarea id="as-secret" rows={2} className="font-mono" autoComplete="off" value={form.secret_headers ?? ""} onChange={(e) => set("secret_headers", e.target.value)} />
          </Field>
          <Field label="Variabel awal" htmlFor="as-vars" hint="'nama = nilai' per baris, dipakai sebagai {{nama}}">
            <Textarea id="as-vars" rows={2} className="font-mono" value={varsText} onChange={(e) => { setVarsText(e.target.value); setSaved(false); }} />
          </Field>
        </div>

        {error && <Alert tone="error">{error}</Alert>}
        {hostToApprove && (
          <Alert tone="warning" action={<Button size="sm" variant="primary" onClick={() => save.mutate(hostToApprove)}>Saya berwenang, simpan</Button>}>
            <Warning className="inline" /> Pastikan Anda berwenang menguji API <b>{hostToApprove}</b>.
          </Alert>
        )}
        {saved && <Alert tone="success">Suite disimpan.</Alert>}
        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={save.isPending}>
            <FloppyDisk />
            Simpan suite
          </Button>
          {suite && (
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

type Source = "postman" | "openapi" | "curl" | "ai";
const SOURCES: [Source, string][] = [["postman", "Postman"], ["openapi", "OpenAPI / Swagger"], ["curl", "cURL"], ["ai", "Susun dengan AI"]];

function ImportPanel({ appId, onImported }: { appId: number; onImported: (r: ApiImport) => void }) {
  const [source, setSource] = useState<Source | null>(null);
  const [text, setText] = useState("");
  const [focus, setFocus] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: () => (source === "ai" ? api.generateApiCases(appId, text, focus) : api.importApiCases(source!, text)),
    onSuccess: (r) => {
      onImported(r);
      setNote(`${r.cases.length} test case ditambahkan. Periksa dan sesuaikan sebelum disimpan.`);
      setText("");
    },
  });
  const loadFile = async (file: File | undefined) => {
    if (file) setText(await file.text());
  };
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-dashed border-ink-600 p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-fg-muted">Tambah test case dari:</span>
        {SOURCES.map(([s, label]) => (
          <button key={s} type="button" aria-pressed={source === s} onClick={() => { setSource(source === s ? null : s); setNote(null); run.reset(); }}
            className={cn("inline-flex items-center gap-1 rounded-md border px-2.5 py-1", source === s ? "border-accent bg-accent-soft" : "border-ink-700")}>
            {s === "ai" && <Sparkle />}
            {label}
          </button>
        ))}
      </div>
      {source && (
        <>
          <Field label={source === "curl" ? "Perintah cURL" : source === "postman" ? "Isi collection Postman (JSON)" : "Spesifikasi OpenAPI / Swagger (JSON atau YAML)"} htmlFor="imp-text"
            hint={source === "ai" ? "AI menyusun skenario positif, negatif, dan validasi per endpoint. Hasilnya bisa Anda ubah sebelum disimpan." : source === "curl" ? "Header Authorization/Cookie/token otomatis dipindah ke header rahasia." : "Tempel isinya atau pilih file."}>
            <Textarea id="imp-text" rows={4} className="font-mono" value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            {source !== "curl" && (
              <input type="file" aria-label="Pilih file" accept=".json,.yaml,.yml" className="text-xs" onChange={(e) => loadFile(e.target.files?.[0])} />
            )}
            {source === "ai" && (
              <Input aria-label="Fokus pengujian" className="flex-1" value={focus} placeholder="Fokus (opsional), mis. endpoint work order" onChange={(e) => setFocus(e.target.value)} />
            )}
            <Button variant="primary" onClick={() => run.mutate()} disabled={!text.trim() || run.isPending}>
              {run.isPending ? (source === "ai" ? "AI sedang menyusun…" : "Membaca…") : source === "ai" ? "Susun test case" : "Tambahkan"}
            </Button>
          </div>
          {run.error && <Alert tone="error">{(run.error as Error).message}</Alert>}
        </>
      )}
      {note && <Alert tone="success">{note}</Alert>}
    </div>
  );
}

function SuiteRuns({ suite }: { suite: ApiSuite }) {
  const qc = useQueryClient();
  const runs = useQuery({ queryKey: ["api-runs", suite.id], queryFn: () => api.listApiRuns(suite.id) });
  const [openId, setOpenId] = useState<number | null>(null);
  const [confirmProd, setConfirmProd] = useState(false);
  const start = useMutation({
    mutationFn: () => api.runApiSuite(suite.id, confirmProd),
    onSuccess: (r) => {
      setOpenId(r.id);
      setConfirmProd(false);
      qc.invalidateQueries({ queryKey: ["api-runs", suite.id] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteApiRun(id),
    onSuccess: (_, id) => {
      if (openId === id) setOpenId(null);
      qc.invalidateQueries({ queryKey: ["api-runs", suite.id] });
    },
  });
  const list = runs.data ?? [];
  const shown = openId ?? list[0]?.id ?? null;
  const writes = suite.config.cases.some((c) => !["GET", "HEAD"].includes(c.method));
  const guard = suite.config.environment === "production" && writes;
  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">Jalankan & hasil</h2>
        <div className="flex items-center gap-3">
          {guard && (
            <label className="flex items-center gap-2 text-sm text-review">
              <input type="checkbox" checked={confirmProd} onChange={(e) => setConfirmProd(e.target.checked)} />
              Saya paham suite ini mengubah data Production
            </label>
          )}
          <Button variant="primary" onClick={() => start.mutate()} disabled={start.isPending || (guard && !confirmProd)}>
            <Play weight="fill" />
            Jalankan suite
          </Button>
        </div>
      </div>
      {start.error && <Alert tone="error">{(start.error as Error).message}</Alert>}
      {shown && <RunView runId={shown} onFinished={() => qc.invalidateQueries({ queryKey: ["api-runs", suite.id] })} />}
      {list.length > 0 && (
        <table className="w-full text-sm">
          <thead className="border-b border-ink-700 text-left text-xs text-fg-muted">
            <tr>
              <th className="py-2 font-medium">Waktu</th>
              <th className="font-medium">Lulus</th>
              <th className="font-medium">Gagal</th>
              <th className="font-medium">Error</th>
              <th className="font-medium">Status</th>
              <th />
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-700">
            {list.map((r) => (
              <tr key={r.id} className={cn("cursor-pointer hover:bg-ink-850", shown === r.id && "bg-accent-soft")} onClick={() => setOpenId(r.id)}>
                <td className="py-2">{formatDateTime(r.started_at)}</td>
                <td className="text-pass">{r.summary?.passed ?? "-"}</td>
                <td className={cn(r.summary?.failed ? "text-fail" : "")}>{r.summary?.failed ?? "-"}</td>
                <td className={cn(r.summary?.errors ? "text-review" : "")}>{r.summary?.errors ?? "-"}</td>
                <td>
                  {r.status === "running" ? <span className="text-accent">Berjalan</span> : r.status === "failed" ? <span className="text-fail">Gagal jalan</span> : r.status === "stopped" ? "Dihentikan" : "Selesai"}
                </td>
                <td className="text-right">
                  {r.status !== "running" && (
                    <Button variant="ghost" size="sm" aria-label={`Hapus run ${formatDateTime(r.started_at)}`}
                      onClick={(e) => { e.stopPropagation(); remove.mutate(r.id); }}>
                      <Trash />
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function RunView({ runId, onFinished }: { runId: number; onFinished: () => void }) {
  const run = useQuery({
    queryKey: ["api-run", runId],
    queryFn: () => api.getApiRun(runId),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1000 : false),
  });
  const status = run.data?.status;
  useEffect(() => {
    if (status && status !== "running") onFinished();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);
  const stop = useMutation({ mutationFn: () => api.stopApiRun(runId) });
  const [expanded, setExpanded] = useState<number | null>(null);
  if (!run.data) return <Skeleton className="h-32" />;
  const r: ApiRun = run.data;
  const cases = r.result?.cases ?? [];
  const s = r.result?.summary;
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-ink-700 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm">
          {r.status === "running" ? (
            <span className="font-medium text-accent">Berjalan… {cases.length}/{r.result?.total ?? r.config.cases.length} test case</span>
          ) : s ? (
            <span className={cn("font-semibold", s.passed === s.total ? "text-pass" : "text-fail")}>
              {s.passed}/{s.total} lulus
              {s.failed > 0 && ` · ${s.failed} gagal`}
              {s.errors > 0 && ` · ${s.errors} error`}
            </span>
          ) : (
            <span className="text-fail">{r.note || "Selesai"}</span>
          )}
          {r.note && r.status !== "running" && s && <span className="ml-2 text-fg-muted">{r.note}</span>}
        </div>
        {r.status === "running" ? (
          <Button variant="danger" size="sm" onClick={() => stop.mutate()} disabled={stop.isPending}>
            <Stop />
            Hentikan
          </Button>
        ) : (
          <a href={api.apiXlsxUrl(runId)} download className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-ink-600 px-2.5 text-xs hover:bg-ink-850">
            <DownloadSimple />
            Excel
          </a>
        )}
      </div>
      <div className="divide-y divide-ink-700 rounded-lg border border-ink-700">
        {cases.map((c, i) => (
          <CaseRow key={i} c={c} open={expanded === i} onToggle={() => setExpanded(expanded === i ? null : i)} />
        ))}
        {!cases.length && <p className="p-3 text-sm text-fg-muted">Menunggu hasil…</p>}
      </div>
    </div>
  );
}

function CaseRow({ c, open, onToggle }: { c: ApiCaseResult; open: boolean; onToggle: () => void }) {
  const blocked = !!c.error && c.status === undefined;
  return (
    <div>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-3 p-3 text-left text-sm hover:bg-ink-850">
        <span className={cn("w-16 shrink-0 text-xs font-semibold", blocked ? "text-review" : c.passed ? "text-pass" : "text-fail")}>
          {blocked ? "ERROR" : c.passed ? "LULUS" : "GAGAL"}
        </span>
        <span className="min-w-0 flex-1 truncate font-medium">{c.name}</span>
        <span className="font-mono text-xs text-fg-dim">{c.request.method}</span>
        {c.status !== undefined && <span className="font-mono text-xs">{c.status}</span>}
        {c.ms !== undefined && <span className="w-16 text-right text-xs text-fg-muted">{c.ms} ms</span>}
      </button>
      {open && (
        <div className="flex flex-col gap-2 border-t border-ink-700 bg-ink-900 p-3 text-xs">
          <div className="font-mono break-all">
            {c.request.method} {c.request.url}
          </div>
          {c.request.body && <pre className="max-h-32 overflow-auto rounded bg-ink-850 p-2 font-mono whitespace-pre-wrap">{c.request.body}</pre>}
          <ul className="flex flex-col gap-1">
            {c.assertions.map((a, k) => (
              <li key={k} className={a.passed ? "text-pass" : "text-fail"}>
                {a.passed ? "✓" : "✗"} {a.description} <span className="text-fg-muted">— aktual: {a.actual}</span>
              </li>
            ))}
          </ul>
          {c.error && <p className="text-review">{c.error}</p>}
          {c.response && (
            <details>
              <summary className="cursor-pointer text-fg-muted">Respons</summary>
              <pre className="mt-1 max-h-48 overflow-auto rounded bg-ink-850 p-2 font-mono whitespace-pre-wrap">{c.response}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
