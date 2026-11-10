import { FlowArrow, PencilSimple, Plus, Target, Trash } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, Field, Input, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { App, Flow } from "@/lib/types";

const EXAMPLE = `1. Buka menu Installation, pilih work order berstatus "Assigned to engineer"
2. Tap Start, lalu On The Way, lalu Arrive
3. Isi data instalasi dan unggah foto evidence
4. Tap Close order lalu konfirmasi
Expected: status work order menjadi CLOSED, hilang dari daftar aktif, dan muncul di History`;

/** Modul kustom: alur bisnis yang ditulis QA. Muncul di pilihan Satu modul pada Run baru. */
export function FlowsPanel({ app }: { app: App }) {
  const qc = useQueryClient();
  const flows = useQuery({ queryKey: ["flows", app.id], queryFn: () => api.listFlows(app.id) });
  const [editing, setEditing] = useState<Flow | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteFlow(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["flows", app.id] });
      qc.invalidateQueries({ queryKey: ["modules", app.id] });
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });
  const list = flows.data ?? [];
  const platform = app.platform === "android" ? "&platform=android" : "";

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 font-semibold">
            <FlowArrow className="text-accent" />
            Alur bisnis (modul kustom)
          </h2>
          <p className="mt-1 text-sm text-fg-muted">
            Proses yang melintasi beberapa menu, mis. buka work order sampai closed. Tulis langkahnya sekali; alur muncul di pilihan{" "}
            <b>Satu modul</b> dan AI menyusun test case positif, negatif, dan validasi dari alur ini. Butuh aplikasi yang sudah
            dipetakan.
          </p>
        </div>
        {editing === null && (
          <Button onClick={() => setEditing("new")}>
            <Plus />
            Tambah alur
          </Button>
        )}
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      {editing !== null && (
        <FlowForm
          appId={app.id}
          flow={editing === "new" ? null : editing}
          onDone={() => setEditing(null)}
        />
      )}
      {list.length > 0 && (
        <ul className="divide-y divide-ink-700 rounded-lg border border-ink-700">
          {list.map((f) => (
            <li key={f.id} className="flex items-start gap-4 p-4">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{f.name}</div>
                <pre className="mt-1 line-clamp-3 whitespace-pre-wrap font-sans text-sm text-fg-muted">{f.steps}</pre>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {app.explored && (
                  <Link
                    to={`/runs/new?app=${app.id}&module=${encodeURIComponent(f.name)}${platform}`}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-semibold text-white hover:bg-accent-hover"
                  >
                    <Target />
                    Uji alur ini
                  </Link>
                )}
                <Button size="sm" variant="ghost" aria-label={`Ubah alur ${f.name}`} onClick={() => setEditing(f)}>
                  <PencilSimple />
                </Button>
                <Button size="sm" variant="ghost" className="text-fail!" aria-label={`Hapus alur ${f.name}`} onClick={() => remove.mutate(f.id)}>
                  <Trash />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {list.length === 0 && editing === null && !flows.isLoading && (
        <p className="rounded-lg border border-dashed border-ink-600 p-4 text-sm text-fg-muted">Belum ada alur bisnis untuk aplikasi ini.</p>
      )}
    </Card>
  );
}

function FlowForm({ appId, flow, onDone }: { appId: number; flow: Flow | null; onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(flow?.name ?? "");
  const [steps, setSteps] = useState(flow?.steps ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => (flow ? api.updateFlow(flow.id, { name: name.trim(), steps }) : api.createFlow(appId, { name: name.trim(), steps })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["flows", appId] });
      qc.invalidateQueries({ queryKey: ["modules", appId] });
      onDone();
    },
    onError: (e) => setErrors(e instanceof ApiError && Object.keys(e.fieldErrors).length ? e.fieldErrors : { _: String((e as Error).message) }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!name.trim()) next.name = "Wajib diisi";
    if (!steps.trim()) next.steps = "Tulis langkah alurnya";
    setErrors(next);
    if (!Object.keys(next).length) save.mutate();
  };
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4 rounded-lg border border-accent-line bg-accent-soft/40 p-4">
      <Field label="Nama alur" htmlFor="flow-name" error={errors.name}>
        <Input id="flow-name" value={name} placeholder="Alur work order sampai closed" onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field
        label="Langkah alur dan hasil yang diharapkan"
        htmlFor="flow-steps"
        error={errors.steps}
        hint="Satu langkah per baris, sebut nama menu/tombol. Tulis juga hasil akhir yang diharapkan. Data uji yang diperlukan (mis. work order berstatus tertentu) sebaiknya disebut."
      >
        <Textarea id="flow-steps" rows={7} value={steps} placeholder={EXAMPLE} onChange={(e) => setSteps(e.target.value)} />
      </Field>
      {errors._ && <Alert tone="error">{errors._}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {flow ? "Simpan alur" : "Tambah alur"}
        </Button>
        <Button onClick={onDone}>Batal</Button>
      </div>
    </form>
  );
}
