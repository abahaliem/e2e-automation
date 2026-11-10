import { CaretRight, Copy, Play, Plus, Trash } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Alert, Button, Card, EmptyState, Field, Input, Select, Skeleton, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { PlanCase } from "@/lib/types";

const TYPES: PlanCase["type"][] = ["positif", "negatif", "validasi", "boundary", "navigasi"];
const TYPE_LABEL: Record<PlanCase["type"], string> = {
  positif: "Positif",
  negatif: "Negatif",
  validasi: "Validasi",
  boundary: "Boundary",
  navigasi: "Navigasi",
};
const PRIORITIES: PlanCase["priority"][] = ["High", "Medium", "Low"];

type Draft = PlanCase & { key: string; stepsText: string };

let seq = 0;
const toDraft = (c: PlanCase): Draft => ({ ...c, key: `k${++seq}`, stepsText: c.steps.join("\n") });
const fromDraft = ({ key: _key, stepsText, ...c }: Draft): PlanCase => ({
  ...c,
  steps: stepsText.split("\n").map((s) => s.trim()).filter(Boolean),
});

/** Review test case hasil susunan AI sebelum dijalankan: edit, hapus, tambah, lalu jalankan. */
export function RunReviewPage() {
  const runId = Number(useParams().runId);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.getRun(runId) });
  const plan = useQuery({ queryKey: ["plan", runId], queryFn: () => api.getPlan(runId) });
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (plan.data && drafts === null) setDrafts(plan.data.cases.map(toDraft));
  }, [plan.data, drafts]);

  const screens = plan.data?.screens ?? [];
  const update = (key: string, patch: Partial<Draft>) => {
    setSaved(false);
    setDrafts((ds) => (ds ?? []).map((d) => (d.key === key ? { ...d, ...patch } : d)));
  };
  const remove = (key: string) => {
    setSaved(false);
    setDrafts((ds) => (ds ?? []).filter((d) => d.key !== key));
  };
  const duplicate = (d: Draft) => {
    setSaved(false);
    setDrafts((ds) => {
      const list = ds ?? [];
      const i = list.findIndex((x) => x.key === d.key);
      const copy = { ...d, id: undefined, key: `k${++seq}`, title: `${d.title} (salinan)` };
      return [...list.slice(0, i + 1), copy, ...list.slice(i + 1)];
    });
  };
  const add = () => {
    setSaved(false);
    const first = screens[0];
    setDrafts((ds) => [
      ...(ds ?? []),
      toDraft({
        title: "",
        page: first?.page_name ?? "",
        type: "positif",
        priority: "Medium",
        precondition: "",
        test_data: "",
        steps: [],
        expected: "",
        start_url: first?.url ?? "",
      }),
    ]);
  };

  const validate = (): string | null => {
    const list = drafts ?? [];
    if (!list.length) return "Minimal satu test case";
    const bad = list.findIndex((d) => !d.title.trim() || !fromDraft(d).steps.length || !d.expected.trim());
    return bad >= 0 ? `Test case ke-${bad + 1}: judul, langkah, dan expected result wajib diisi` : null;
  };

  const save = useMutation({
    mutationFn: async (thenRun: boolean) => {
      const res = await api.savePlan(runId, (drafts ?? []).map(fromDraft));
      if (thenRun) await api.resumeRun(runId);
      return { res, thenRun };
    },
    onSuccess: ({ res, thenRun }) => {
      setError(null);
      qc.setQueryData(["plan", runId], res);
      qc.invalidateQueries({ queryKey: ["run", runId] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      if (thenRun) navigate(`/runs/${runId}`);
      else {
        setDrafts(res.cases.map(toDraft));
        setSaved(true);
      }
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  });
  const submit = (thenRun: boolean) => {
    const problem = validate();
    setError(problem);
    if (!problem) save.mutate(thenRun);
  };

  const r = run.data;
  const editable = plan.data?.editable ?? false;
  const list = drafts ?? [];

  return (
    <main className="flex min-w-0 flex-col gap-6 px-10 py-8">
      <header className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm text-fg-muted">
            <Link to="/runs" className="hover:text-fg">
              Riwayat run
            </Link>
            <CaretRight className="text-fg-dim" />
            <span>{r?.app_name ?? "..."}</span>
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Review test case {r?.module ? `modul ${r.module}` : ""}</h1>
          <p className="mt-1.5 text-sm text-fg-muted">
            Disusun AI dari peta aplikasi. Hapus yang tidak relevan, perbaiki langkah atau test data, lalu jalankan.
            Untuk akun valid tulis <span className="font-mono text-fg">{"{{username}}"}</span> dan{" "}
            <span className="font-mono text-fg">{"{{password}}"}</span> (diisi dari akun test tersimpan).
          </p>
        </div>
        {editable && (
          <div className="flex shrink-0 items-center gap-2">
            <Button size="lg" onClick={() => submit(false)} disabled={save.isPending}>
              Simpan
            </Button>
            <Button variant="primary" size="lg" onClick={() => submit(true)} disabled={save.isPending || !list.length}>
              <Play weight="fill" />
              {save.isPending ? "Menyimpan..." : `Simpan & jalankan ${list.length} test case`}
            </Button>
          </div>
        )}
      </header>

      {plan.data && !editable && (
        <Alert
          tone="info"
          action={
            <Link to={`/runs/${runId}/result`} className="inline-flex h-8 items-center rounded-lg border border-ink-600 px-2.5 text-xs">
              Lihat hasil
            </Link>
          }
        >
          Test case run ini sudah dijalankan atau run sedang berjalan, jadi tidak bisa diubah lagi.
        </Alert>
      )}
      {error && <Alert tone="error">{error}</Alert>}
      {saved && <Alert tone="success">Perubahan disimpan. Klik Simpan & jalankan bila sudah siap.</Alert>}

      {plan.isLoading || drafts === null ? (
        <Skeleton className="h-64" />
      ) : list.length === 0 ? (
        <Card>
          <EmptyState title="Tidak ada test case" description="Tambahkan minimal satu test case untuk dijalankan." />
        </Card>
      ) : (
        <ol className="flex flex-col gap-4">
          {list.map((d, i) => (
            <li key={d.key}>
              <CaseEditor
                index={i}
                draft={d}
                screens={screens}
                disabled={!editable}
                onChange={(patch) => update(d.key, patch)}
                onRemove={() => remove(d.key)}
                onDuplicate={() => duplicate(d)}
              />
            </li>
          ))}
        </ol>
      )}

      {editable && (
        <div>
          <Button onClick={add}>
            <Plus />
            Tambah test case
          </Button>
        </div>
      )}
    </main>
  );
}

function CaseEditor({
  index,
  draft: d,
  screens,
  disabled,
  onChange,
  onRemove,
  onDuplicate,
}: {
  index: number;
  draft: Draft;
  screens: { url: string; page_name: string }[];
  disabled: boolean;
  onChange: (patch: Partial<Draft>) => void;
  onRemove: () => void;
  onDuplicate: () => void;
}) {
  const n = index + 1;
  const id = (f: string) => `tc${n}-${f}`;
  return (
    <Card className={cn("flex flex-col gap-4 p-5", disabled && "opacity-80")}>
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs text-fg-dim">{d.id ?? "Baru"}</span>
        <span className="text-xs text-fg-muted">#{n}</span>
        {!disabled && (
          <div className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" onClick={onDuplicate} aria-label={`Duplikat test case ${n}`}>
              <Copy />
              Duplikat
            </Button>
            <Button size="sm" variant="ghost" className="text-fail!" onClick={onRemove} aria-label={`Hapus test case ${n}`}>
              <Trash />
              Hapus
            </Button>
          </div>
        )}
      </div>
      <Field label="Skenario" htmlFor={id("title")}>
        <Input id={id("title")} value={d.title} disabled={disabled} onChange={(e) => onChange({ title: e.target.value })} />
      </Field>
      <div className="grid grid-cols-[minmax(0,1fr)_150px_130px] gap-4">
        <Field label="Layar awal" htmlFor={id("start")}>
          <Select
            id={id("start")}
            value={d.start_url}
            disabled={disabled}
            onChange={(e) => {
              const s = screens.find((x) => x.url === e.target.value);
              onChange({ start_url: e.target.value, page: s?.page_name ?? d.page });
            }}
          >
            {!screens.some((s) => s.url === d.start_url) && <option value={d.start_url}>{d.page || d.start_url}</option>}
            {screens.map((s) => (
              <option key={s.url} value={s.url}>
                {s.page_name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Tipe" htmlFor={id("type")}>
          <Select id={id("type")} value={d.type} disabled={disabled} onChange={(e) => onChange({ type: e.target.value as PlanCase["type"] })}>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABEL[t]}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Prioritas" htmlFor={id("priority")}>
          <Select
            id={id("priority")}
            value={d.priority}
            disabled={disabled}
            onChange={(e) => onChange({ priority: e.target.value as PlanCase["priority"] })}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Pre-condition" htmlFor={id("pre")}>
          <Input id={id("pre")} value={d.precondition} disabled={disabled} onChange={(e) => onChange({ precondition: e.target.value })} />
        </Field>
        <Field label="Test data" htmlFor={id("data")}>
          <Input id={id("data")} value={d.test_data} disabled={disabled} onChange={(e) => onChange({ test_data: e.target.value })} />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Langkah (satu per baris)" htmlFor={id("steps")}>
          <Textarea id={id("steps")} rows={4} value={d.stepsText} disabled={disabled} onChange={(e) => onChange({ stepsText: e.target.value })} />
        </Field>
        <Field label="Expected result" htmlFor={id("expected")}>
          <Textarea id={id("expected")} rows={4} value={d.expected} disabled={disabled} onChange={(e) => onChange({ expected: e.target.value })} />
        </Field>
      </div>
    </Card>
  );
}
