import { ArrowCounterClockwise, Database, Lightning, PencilSimple, Play, Plus, Trash } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Alert, Button, Card, Field, Input, Select, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { App, Hook, HookInput } from "@/lib/types";

const fieldErrors = (e: unknown) =>
  e instanceof ApiError && Object.keys(e.fieldErrors).length ? e.fieldErrors : { _: e instanceof Error ? e.message : String(e) };

/** Data uji per aplikasi: kumpulan nilai (mis. wo_id) yang dipakai sekali oleh test case lewat {{data:nama}}. */
export function TestDataPanel({ app }: { app: App }) {
  const qc = useQueryClient();
  const sets = useQuery({ queryKey: ["test-data", app.id], queryFn: () => api.listTestData(app.id) });
  const [adding, setAdding] = useState<string | null>(null); // nama kumpulan yang sedang ditambah ("" = baru)
  const refresh = () => qc.invalidateQueries({ queryKey: ["test-data", app.id] });
  const reset = useMutation({ mutationFn: api.resetTestData, onSuccess: refresh });
  const removeValue = useMutation({ mutationFn: api.deleteTestData, onSuccess: refresh });
  const removeSet = useMutation({ mutationFn: (name: string) => api.deleteTestDataSet(app.id, name), onSuccess: refresh });
  const list = sets.data ?? [];

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 font-semibold">
            <Database className="text-accent" />
            Data uji
          </h2>
          <p className="mt-1 text-sm text-fg-muted">
            Data yang harus sudah ada di aplikasi, mis. nomor work order uji. Tulis <span className="font-mono text-fg">{"{{data:wo_id}}"}</span>{" "}
            di langkah test case atau alur bisnis; setiap test case memakai nilai yang belum terpakai, lalu nilai ditandai terpakai.
            AI penyusun test case juga diberi tahu data yang tersedia.
          </p>
        </div>
        {adding === null && (
          <Button onClick={() => setAdding("")}>
            <Plus />
            Tambah data
          </Button>
        )}
      </div>
      {adding !== null && <AddValues appId={app.id} name={adding} onDone={() => setAdding(null)} />}
      {list.map((s) => (
        <div key={s.name} className="rounded-lg border border-ink-700">
          <div className="flex items-center gap-3 border-b border-ink-700 bg-ink-850 px-4 py-2.5">
            <span className="font-mono text-sm font-medium">{`{{data:${s.name}}}`}</span>
            <span className={cn("rounded px-1.5 py-0.5 text-xs", s.available ? "bg-pass/10 text-pass" : "bg-fail/10 text-fail")}>
              {s.available} tersedia dari {s.values.length}
            </span>
            <div className="ml-auto flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => setAdding(s.name)}>
                <Plus />
                Tambah nilai
              </Button>
              <Button size="sm" variant="ghost" className="text-fail!" aria-label={`Hapus data ${s.name}`} onClick={() => removeSet.mutate(s.name)}>
                <Trash />
              </Button>
            </div>
          </div>
          <ul className="max-h-56 divide-y divide-ink-700 overflow-y-auto text-sm">
            {s.values.map((v) => (
              <li key={v.id} className="flex items-center gap-3 px-4 py-2">
                <span className={cn("font-mono", v.used_by && "text-fg-dim line-through")}>{v.value}</span>
                {v.used_by ? (
                  <span className="truncate text-xs text-fg-muted">Terpakai: {v.used_by}</span>
                ) : (
                  <span className="text-xs text-pass">Tersedia</span>
                )}
                <div className="ml-auto flex shrink-0 gap-1">
                  {v.used_by && (
                    <Button size="sm" variant="ghost" aria-label={`Pakai lagi ${v.value}`} title="Tandai tersedia lagi" onClick={() => reset.mutate(v.id)}>
                      <ArrowCounterClockwise />
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" aria-label={`Hapus nilai ${v.value}`} onClick={() => removeValue.mutate(v.id)}>
                    <Trash />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {!list.length && adding === null && !sets.isLoading && (
        <p className="rounded-lg border border-dashed border-ink-600 p-4 text-sm text-fg-muted">Belum ada data uji untuk aplikasi ini.</p>
      )}
    </Card>
  );
}

function AddValues({ appId, name: initial, onDone }: { appId: number; name: string; onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(initial);
  const [values, setValues] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const add = useMutation({
    mutationFn: () => api.addTestData(appId, { name: name.trim(), values }),
    onSuccess: (d) => {
      qc.setQueryData(["test-data", appId], d);
      onDone();
    },
    onError: (e) => setErrors(fieldErrors(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!/^[A-Za-z0-9_.-]{1,40}$/.test(name.trim())) next.name = "Huruf, angka, garis bawah, titik, atau strip (mis. wo_id)";
    if (!values.trim()) next.values = "Isi minimal satu nilai";
    setErrors(next);
    if (!Object.keys(next).length) add.mutate();
  };
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4 rounded-lg border border-accent-line bg-accent-soft/40 p-4">
      <Field label="Nama data" htmlFor="td-name" error={errors.name} hint="Dipakai sebagai {{data:nama}}">
        <Input id="td-name" className="font-mono" value={name} disabled={!!initial} placeholder="wo_id" onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Nilai (satu per baris)" htmlFor="td-values" error={errors.values}>
        <Textarea id="td-values" rows={4} className="font-mono" value={values} placeholder={"000090014541\n000090014542"} onChange={(e) => setValues(e.target.value)} />
      </Field>
      {errors._ && <Alert tone="error">{errors._}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={add.isPending}>
          Simpan data
        </Button>
        <Button onClick={onDone}>Batal</Button>
      </div>
    </form>
  );
}

/** Persiapan otomatis: permintaan HTTP sebelum run / sebelum setiap test case (mis. membuat WO uji baru). */
export function HooksPanel({ app }: { app: App }) {
  const qc = useQueryClient();
  const hooks = useQuery({ queryKey: ["hooks", app.id], queryFn: () => api.listHooks(app.id) });
  const [editing, setEditing] = useState<Hook | "new" | null>(null);
  const [result, setResult] = useState<Record<number, { ok: boolean; message: string; captured: Record<string, string> }>>({});
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["hooks", app.id] });
    qc.invalidateQueries({ queryKey: ["test-data", app.id] });
  };
  const toggle = useMutation({ mutationFn: (h: Hook) => api.updateHook(h.id, { active: !h.active }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: api.deleteHook, onSuccess: refresh });
  const test = useMutation({
    mutationFn: (h: Hook) => api.testHook(h.id),
    onSuccess: (r, h) => {
      setResult((x) => ({ ...x, [h.id]: r }));
      refresh();
    },
  });
  const list = hooks.data ?? [];

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 font-semibold">
            <Lightning className="text-accent" />
            Persiapan otomatis (HTTP)
          </h2>
          <p className="mt-1 text-sm text-fg-muted">
            Opsional. Panggil endpoint internal sebelum run atau sebelum setiap test case, mis. membuat work order uji baru. Nilai dari
            respons bisa langsung masuk Data uji (mis. <span className="font-mono">wo_id = data.id</span>) dan dipakai test case. Header
            (token) disimpan terenkripsi.
          </p>
        </div>
        {editing === null && (
          <Button onClick={() => setEditing("new")}>
            <Plus />
            Tambah persiapan
          </Button>
        )}
      </div>
      {editing !== null && <HookForm appId={app.id} hook={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      {list.length > 0 && (
        <ul className="divide-y divide-ink-700 rounded-lg border border-ink-700">
          {list.map((h) => (
            <li key={h.id} className="flex flex-col gap-2 p-4">
              <div className="flex items-center gap-3">
                <span className={cn("font-medium", !h.active && "text-fg-dim")}>{h.name}</span>
                <span className="rounded bg-ink-800 px-1.5 py-0.5 text-xs text-fg-muted">
                  {h.when === "run" ? "Sekali sebelum run" : "Sebelum tiap test case yang memakai data uji"}
                </span>
                {!h.active && <span className="text-xs text-fg-dim">Nonaktif</span>}
                <div className="ml-auto flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => test.mutate(h)} disabled={test.isPending}>
                    <Play />
                    Coba
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => toggle.mutate(h)}>
                    {h.active ? "Nonaktifkan" : "Aktifkan"}
                  </Button>
                  <Button size="sm" variant="ghost" aria-label={`Ubah persiapan ${h.name}`} onClick={() => setEditing(h)}>
                    <PencilSimple />
                  </Button>
                  <Button size="sm" variant="ghost" className="text-fail!" aria-label={`Hapus persiapan ${h.name}`} onClick={() => remove.mutate(h.id)}>
                    <Trash />
                  </Button>
                </div>
              </div>
              <div className="truncate font-mono text-xs text-fg-muted">
                {h.method} {h.url}
                {Object.keys(h.capture).length > 0 && ` → ${Object.entries(h.capture).map(([k, v]) => `${k} = ${v}`).join(", ")}`}
              </div>
              {result[h.id] && (
                <Alert tone={result[h.id].ok ? "success" : "error"}>
                  {result[h.id].message}
                  {result[h.id].ok && Object.keys(result[h.id].captured).length > 0 &&
                    `: ${Object.entries(result[h.id].captured).map(([k, v]) => `${k} = ${v}`).join(", ")}`}
                </Alert>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function HookForm({ appId, hook, onDone }: { appId: number; hook: Hook | null; onDone: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<HookInput>(() => ({
    name: hook?.name ?? "",
    when: hook?.when ?? "case",
    method: hook?.method ?? "POST",
    url: hook?.url ?? "",
    headers: "",
    body: hook?.body ?? "",
    capture: hook ? Object.entries(hook.capture).map(([k, v]) => `${k} = ${v}`).join("\n") : "",
  }));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof HookInput>(k: K, v: HookInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const save = useMutation({
    mutationFn: () => {
      if (!hook) return api.createHook(appId, form);
      const { headers, ...rest } = form;
      return api.updateHook(hook.id, headers.trim() ? form : rest); // header kosong saat ubah = tidak diganti
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["hooks", appId] });
      onDone();
    },
    onError: (e) => setErrors(fieldErrors(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "Wajib diisi";
    if (!/^https?:\/\//.test(form.url.trim())) next.url = "URL harus diawali http:// atau https://";
    setErrors(next);
    if (!Object.keys(next).length) save.mutate();
  };
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4 rounded-lg border border-accent-line bg-accent-soft/40 p-4">
      <div className="grid grid-cols-[minmax(0,1fr)_220px] gap-4">
        <Field label="Nama persiapan" htmlFor="hk-name" error={errors.name}>
          <Input id="hk-name" value={form.name} placeholder="Buat work order uji" onChange={(e) => set("name", e.target.value)} />
        </Field>
        <Field label="Kapan dijalankan" htmlFor="hk-when">
          <Select id="hk-when" value={form.when} onChange={(e) => set("when", e.target.value as HookInput["when"])}>
            <option value="case">Sebelum tiap test case</option>
            <option value="run">Sekali sebelum run</option>
          </Select>
        </Field>
      </div>
      <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-4">
        <Field label="Method" htmlFor="hk-method">
          <Select id="hk-method" value={form.method} onChange={(e) => set("method", e.target.value as HookInput["method"])}>
            {["POST", "GET", "PUT", "PATCH", "DELETE"].map((m) => (
              <option key={m}>{m}</option>
            ))}
          </Select>
        </Field>
        <Field label="URL" htmlFor="hk-url" error={errors.url}>
          <Input id="hk-url" className="font-mono" value={form.url} placeholder="https://dev-api.kantor.local/qa/work-orders" onChange={(e) => set("url", e.target.value)} />
        </Field>
      </div>
      <Field
        label="Header (rahasia)"
        htmlFor="hk-headers"
        error={errors.headers}
        hint={hook?.has_headers ? "Header tersimpan terenkripsi. Kosongkan bila tidak diganti." : "JSON atau 'Nama: nilai' per baris. Disimpan terenkripsi."}
      >
        <Textarea id="hk-headers" rows={2} className="font-mono" autoComplete="off" value={form.headers} placeholder="Authorization: Bearer ..." onChange={(e) => set("headers", e.target.value)} />
      </Field>
      <Field label="Body (JSON, opsional)" htmlFor="hk-body" hint="Boleh memakai {{data:nama}}, mis. ID teknisi; nilainya hanya dibaca.">
        <Textarea id="hk-body" rows={3} className="font-mono" value={form.body} placeholder={'{"teknisi": "{{data:teknisi}}"}'} onChange={(e) => set("body", e.target.value)} />
      </Field>
      <Field label="Simpan dari respons ke Data uji" htmlFor="hk-capture" error={errors.capture} hint="Satu per baris: nama_data = path.di.respons">
        <Input id="hk-capture" className="font-mono" value={form.capture} placeholder="wo_id = data.id" onChange={(e) => set("capture", e.target.value)} />
      </Field>
      {errors._ && <Alert tone="error">{errors._}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          Simpan persiapan
        </Button>
        <Button onClick={onDone}>Batal</Button>
      </div>
    </form>
  );
}
