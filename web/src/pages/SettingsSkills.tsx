import {
  BookOpenText,
  Check,
  CursorClick,
  DotsThreeVertical,
  FileDoc,
  FilePdf,
  FileText,
  Flask,
  GraduationCap,
  ListChecks,
  Scales,
  Trash,
  UploadSimple,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type DragEvent } from "react";
import { Alert, Button, Card, Field, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Skill, SkillStage, TestCase } from "@/lib/types";

const STAGE_ORDER: SkillStage[] = ["plan", "execute", "judge", "report"];
const WHEN = [
  { icon: ListChecks, title: "Menyusun test case", text: "Teknik desain test dan aturan bisnis menentukan skenario." },
  { icon: CursorClick, title: "Menjalankan test", text: "Checklist dan kebiasaan pengecekan di tiap layar." },
  { icon: Scales, title: "Menilai hasil", text: "Expected result dicocokkan dengan aturan bisnis." },
  { icon: FileText, title: "Menulis laporan", text: "Format test case dan bug mengikuti standar kantor." },
];

function FileIcon({ name, active }: { name: string; active: boolean }) {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pdf")) return <FilePdf className={cn("mt-0.5 text-2xl", active ? "text-fail" : "text-fg-muted")} />;
  if (lower.endsWith(".docx")) return <FileDoc className={cn("mt-0.5 text-2xl", active ? "text-accent" : "text-fg-muted")} />;
  return <FileText className="mt-0.5 text-2xl text-fg-muted" />;
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      className={cn("relative mt-1 h-5 w-9 shrink-0 rounded-full p-0 transition-colors", checked ? "bg-accent" : "bg-ink-600")}
    >
      <span className={cn("absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white transition-transform", checked ? "translate-x-[18px]" : "translate-x-0.5")} />
    </button>
  );
}

export function SkillsTab() {
  const qc = useQueryClient();
  const skills = useQuery({ queryKey: ["skills"], queryFn: api.listSkills });
  const apps = useQuery({ queryKey: ["apps"], queryFn: api.listApps });
  const [showBuiltin, setShowBuiltin] = useState(false);
  const [preview, setPreview] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["skills"] });

  const upload = useMutation({ mutationFn: (file: File) => api.uploadSkill(file), onSuccess: refresh });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Parameters<typeof api.patchSkill>[1] }) => api.patchSkill(id, body),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: (id: number) => api.deleteSkill(id), onSuccess: refresh });

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) upload.mutate(file);
  };

  if (skills.isLoading || !skills.data) {
    return (
      <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-10">
        <Skeleton className="h-96" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  const data = skills.data;
  const activeCount = data.skills.filter((s) => s.active).length;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-10">
      <div className="flex min-w-0 flex-col gap-6">
        <Card className="p-6">
          <div className="flex items-start justify-between gap-6">
            <div className="flex gap-4">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-accent-line bg-accent-soft">
                <GraduationCap className="text-xl text-accent" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="font-semibold">{data.builtin.name}</h2>
                  <span className="rounded-md border border-ink-700 bg-ink-800 px-2 py-0.5 text-xs text-fg-muted">Bawaan, selalu aktif</span>
                </div>
                <p className="mt-1 text-sm text-fg-muted">{data.builtin.description}</p>
              </div>
            </div>
            <Button className="shrink-0" onClick={() => setShowBuiltin((v) => !v)}>
              <BookOpenText />
              {showBuiltin ? "Tutup isi" : "Lihat isi"}
            </Button>
          </div>
          <div className="mt-5 grid grid-cols-2 gap-x-8 gap-y-2.5 text-sm">
            {data.builtin.topics.map((t) => (
              <div key={t} className="flex gap-2.5">
                <Check className="mt-0.5 shrink-0 text-pass" />
                {t}
              </div>
            ))}
          </div>
          {showBuiltin && (
            <pre className="mt-5 whitespace-pre-wrap rounded-lg border border-ink-700 bg-ink-850 p-4 font-sans text-sm leading-relaxed text-fg-muted">
              {data.builtin.content}
            </pre>
          )}
        </Card>

        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Skill tambahan</h2>
            <span className="text-sm text-fg-muted">
              {data.skills.length} file, {activeCount} aktif
            </span>
          </div>
          <label
            htmlFor="skill-file"
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            className="grid h-24 cursor-pointer place-items-center rounded-xl border border-dashed border-accent-line bg-accent-soft text-center"
          >
            <div>
              <div className="flex items-center justify-center gap-2 text-sm font-medium text-accent">
                <UploadSimple className="text-lg" />
                {upload.isPending ? "Membaca isi file..." : "Tarik file skill ke sini, atau pilih file"}
              </div>
              <div className="mt-1 text-xs text-fg-muted">.md, .txt, .docx, atau .pdf. Contoh: standar test case kantor, aturan bisnis, glosarium, checklist regresi.</div>
            </div>
          </label>
          <input
            id="skill-file"
            aria-label="File skill"
            type="file"
            accept=".md,.txt,.docx,.pdf"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload.mutate(file);
              e.target.value = "";
            }}
          />
          {upload.error && <Alert tone="error">{(upload.error as Error).message}</Alert>}
          {data.skills.length > 0 && (
            <ul className="divide-y divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
              {data.skills.map((s) => (
                <SkillRow
                  key={s.id}
                  skill={s}
                  apps={apps.data ?? []}
                  stages={data.stages}
                  onPatch={(body) => update.mutate({ id: s.id, body })}
                  onDelete={() => remove.mutate(s.id)}
                />
              ))}
            </ul>
          )}
        </section>
      </div>

      <aside className="flex flex-col gap-5">
        <Card className="p-5">
          <h2 className="text-sm font-semibold">Kapan skill dipakai</h2>
          <ol className="mt-4 flex flex-col gap-4 text-sm">
            {WHEN.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3">
                <Icon className="shrink-0 text-lg text-accent" />
                <div>
                  <div className="font-medium">{title}</div>
                  <div className="text-fg-muted">{text}</div>
                </div>
              </li>
            ))}
          </ol>
        </Card>
        <Card className="p-5">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">Kapasitas model terpakai</span>
            <span className="text-fg-muted">{data.capacity_percent}%</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-800">
            <div className={cn("h-full", data.capacity_percent > 60 ? "bg-review" : "bg-accent")} style={{ width: `${data.capacity_percent}%` }} />
          </div>
          <p className="mt-2 text-xs text-fg-muted">Skill aktif ikut dibaca AI di setiap langkah. Makin besar, makin lambat dan mahal.</p>
          <Button className="mt-4 w-full" onClick={() => setPreview((v) => !v)}>
            <Flask />
            Coba pada modul contoh
          </Button>
        </Card>
        {preview && <PreviewPanel />}
      </aside>
    </div>
  );
}

function SkillRow({
  skill,
  apps,
  stages,
  onPatch,
  onDelete,
}: {
  skill: Skill;
  apps: { id: number; name: string }[];
  stages: Record<SkillStage, string>;
  onPatch: (body: { name?: string; stages?: SkillStage[]; app_ids?: number[]; active?: boolean }) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(skill.name);
  const [chosen, setChosen] = useState<SkillStage[]>(skill.stages);
  const [appIds, setAppIds] = useState<number[]>(skill.app_ids);
  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <li className={cn("flex flex-col gap-3 p-4", !skill.active && "opacity-70")}>
      <div className="flex items-start gap-4">
        <FileIcon name={skill.filename} active={skill.active} />
        <div className="min-w-0 flex-1">
          <div className="font-medium">{skill.name}</div>
          <div className="mt-0.5 text-xs text-fg-dim">
            <span className="font-mono">{skill.filename}</span>, {skill.pages} halaman
          </div>
          <div className="mt-2.5 flex flex-wrap gap-2 text-xs">
            <span className="rounded-md border border-ink-700 bg-ink-850 px-2 py-1">
              {skill.app_names.length ? skill.app_names.join(", ") : "Semua aplikasi"}
            </span>
            {skill.stage_labels.map((label) => (
              <span
                key={label}
                className={cn(
                  "rounded-md border px-2 py-1",
                  skill.active ? "border-accent-line bg-accent-soft text-accent" : "border-ink-700 bg-ink-850 text-fg-muted",
                )}
              >
                {label}
              </span>
            ))}
          </div>
        </div>
        <Toggle checked={skill.active} label={`Aktifkan ${skill.name}`} onChange={() => onPatch({ active: !skill.active })} />
        <button type="button" aria-label={`Atur skill ${skill.name}`} className="text-fg-muted hover:text-fg" onClick={() => setEditing((v) => !v)}>
          <DotsThreeVertical className="text-lg" />
        </button>
      </div>
      {editing && (
        <div className="ml-10 flex flex-col gap-3 rounded-lg border border-ink-700 bg-ink-850 p-4 text-sm">
          <Field label="Nama skill" htmlFor={`skill-name-${skill.id}`}>
            <input
              id={`skill-name-${skill.id}`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-9 rounded-lg border border-ink-600 bg-ink-900 px-3 focus:border-accent focus:outline-none"
            />
          </Field>
          <div>
            <div className="mb-1.5 font-medium">Dipakai saat</div>
            <div className="flex flex-wrap gap-4">
              {STAGE_ORDER.map((st) => (
                <label key={st} className="flex items-center gap-2">
                  <input type="checkbox" checked={chosen.includes(st)} onChange={() => setChosen((c) => toggle(c, st))} className="h-4 w-4 accent-[var(--color-accent)]" />
                  {stages[st]}
                </label>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-1.5 font-medium">Berlaku untuk</div>
            <div className="flex flex-wrap gap-4">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={appIds.length === 0} onChange={() => setAppIds([])} className="h-4 w-4 accent-[var(--color-accent)]" />
                Semua aplikasi
              </label>
              {apps.map((a) => (
                <label key={a.id} className="flex items-center gap-2">
                  <input type="checkbox" checked={appIds.includes(a.id)} onChange={() => setAppIds((ids) => toggle(ids, a.id))} className="h-4 w-4 accent-[var(--color-accent)]" />
                  {a.name}
                </label>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={!chosen.length || !name.trim()}
              onClick={() => {
                onPatch({ name: name.trim(), stages: STAGE_ORDER.filter((s) => chosen.includes(s)), app_ids: appIds });
                setEditing(false);
              }}
            >
              Simpan
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Batal
            </Button>
            <Button size="sm" variant="ghost" className="ml-auto text-fail! hover:bg-fail/5" onClick={onDelete}>
              <Trash />
              Hapus skill
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

function PreviewPanel() {
  const apps = useQuery({ queryKey: ["apps"], queryFn: api.listApps });
  const explored = (apps.data ?? []).filter((a) => a.explored);
  const [appId, setAppId] = useState<number | null>(null);
  const current = appId ?? explored[0]?.id ?? null;
  const modules = useQuery({ queryKey: ["modules", current], queryFn: () => api.appModules(current!), enabled: !!current });
  const [module, setModule] = useState("");
  const run = useMutation({ mutationFn: () => api.previewSkills({ app_id: current!, module }) });

  if (apps.isLoading) return <Skeleton className="h-32" />;
  if (!explored.length)
    return <Alert tone="info">Jalankan Seluruh aplikasi pada salah satu aplikasi dulu, lalu coba skill pada modulnya.</Alert>;
  return (
    <Card className="flex flex-col gap-3 p-5">
      <Field label="Aplikasi contoh" htmlFor="pv-app">
        <Select id="pv-app" value={current ?? ""} onChange={(e) => setAppId(Number(e.target.value))}>
          {explored.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Modul contoh" htmlFor="pv-module">
        <Select id="pv-module" value={module} onChange={(e) => setModule(e.target.value)}>
          <option value="">Pilih modul...</option>
          {(modules.data?.modules ?? []).map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </Select>
      </Field>
      <Button variant="primary" disabled={!module || run.isPending} onClick={() => run.mutate()}>
        <Flask />
        {run.isPending ? "AI sedang menyusun..." : "Susun test case"}
      </Button>
      {run.error && <Alert tone="error">{(run.error as Error).message}</Alert>}
      {run.data && (
        <ol className="flex flex-col gap-2 text-sm">
          {run.data.cases.map((c: TestCase) => (
            <li key={c.id} className="rounded-lg border border-ink-700 p-3">
              <div className="font-mono text-xs text-fg-dim">{c.id}</div>
              <div className="font-medium">{c.title}</div>
              <div className="mt-1 text-xs text-fg-muted">Expected: {c.expected}</div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
