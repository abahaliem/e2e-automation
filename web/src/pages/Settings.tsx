import {
  ArrowsClockwise,
  CheckCircle,
  FloppyDisk,
  Key,
  LinkSimple,
  LockSimple,
  Plus,
  PlugsConnected,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { AccountsPanel } from "@/components/AccountsPanel";
import { Alert, Button, Card, EmptyState, Field, Input, PageHeader, Select, Skeleton, Switch } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Profile, ProfileInput } from "@/lib/types";

type Tab = "ai" | "skill" | "accounts";
const BASE_URL_REQUIRED = "Base URL wajib diisi untuk endpoint OpenAI-compatible";

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>("ai");
  const tabs: { id: Tab; label: string; disabled?: boolean }[] = [
    { id: "ai", label: "Model AI" },
    { id: "skill", label: "Skill QA", disabled: true },
    { id: "accounts", label: "Akun test" },
  ];
  return (
    <main className="flex flex-col gap-6 px-10 py-8">
      <PageHeader title="Pengaturan" />
      <div role="tablist" aria-label="Bagian pengaturan" className="-mt-2 flex gap-6 border-b border-ink-700 text-sm">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            disabled={t.disabled}
            onClick={() => setTab(t.id)}
            className={cn(
              "-mb-px flex items-center gap-2 border-b-2 pb-3",
              tab === t.id ? "border-accent font-medium" : "border-transparent text-fg-muted hover:text-fg",
              t.disabled && "text-fg-dim hover:text-fg-dim",
            )}
          >
            {t.label}
            {t.disabled && <span className="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide">segera</span>}
          </button>
        ))}
      </div>
      {tab === "ai" && <ModelAiTab />}
      {tab === "accounts" && <AccountsTab />}
    </main>
  );
}

function ModelAiTab() {
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: api.listProfiles });
  const [selected, setSelected] = useState<number | "new" | null>(null);

  useEffect(() => {
    if (selected !== null || !profiles.data) return;
    const def = profiles.data.find((p) => p.is_default) ?? profiles.data[0];
    setSelected(def ? def.id : "new");
  }, [profiles.data, selected]);

  if (profiles.isLoading) {
    return (
      <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-10">
        <Skeleton className="h-[480px]" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  const list = profiles.data ?? [];
  const current = typeof selected === "number" ? list.find((p) => p.id === selected) ?? null : null;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-10">
      <ProfileForm key={current?.id ?? "new"} profile={current} onSaved={(p) => setSelected(p.id)} onDeleted={() => setSelected(null)} />
      <aside className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-fg-muted">Profil AI</h2>
          <button type="button" onClick={() => setSelected("new")} className="flex items-center gap-1 text-sm text-accent">
            <Plus />
            Tambah
          </button>
        </div>
        {list.length === 0 ? (
          <Card>
            <EmptyState title="Belum ada profil" description="Isi form di samping untuk menambahkan endpoint AI pertama." />
          </Card>
        ) : (
          <div className="divide-y divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
            {list.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setSelected(p.id)}
                className={cn("block w-full p-4 text-left", selected === p.id && "bg-accent-soft")}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{p.name}</span>
                  {p.is_default && <CheckCircle weight="fill" className="text-accent" aria-label="Default" />}
                </div>
                <div className="mt-1 truncate font-mono text-xs text-fg-dim">
                  {p.provider === "anthropic" ? "anthropic" : hostOf(p.base_url)}, {p.model}
                </div>
              </button>
            ))}
          </div>
        )}
        <p className="text-xs text-fg-muted">Profil bisa dipilih per run di layar Run baru.</p>
      </aside>
    </div>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

type TestResult = { text_ok: boolean; vision_ok: boolean; latency_ms: number; message: string };

function ProfileForm({
  profile,
  onSaved,
  onDeleted,
}: {
  profile: Profile | null;
  onSaved: (p: Profile) => void;
  onDeleted: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<ProfileInput>(() => ({
    name: profile?.name ?? "",
    provider: profile?.provider ?? "openai_compatible",
    base_url: profile?.base_url ?? "",
    model: profile?.model ?? "",
    vision: profile?.vision ?? true,
    timeout_seconds: profile?.timeout_seconds ?? 120,
    is_default: profile?.is_default ?? false,
  }));
  const [apiKey, setApiKey] = useState("");
  const [replacingKey, setReplacingKey] = useState(!profile?.has_api_key);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [modelsMessage, setModelsMessage] = useState("");
  const [test, setTest] = useState<TestResult | null>(null);

  const set = <K extends keyof ProfileInput>(key: K, value: ProfileInput[K]) => setForm((f) => ({ ...f, [key]: value }));

  const save = useMutation({
    mutationFn: () => {
      const body: ProfileInput = { ...form, base_url: form.provider === "anthropic" ? "" : form.base_url.trim() };
      if (apiKey.trim()) body.api_key = apiKey.trim();
      return profile ? api.updateProfile(profile.id, body) : api.createProfile(body);
    },
    onSuccess: (p) => {
      setErrors({});
      setApiKey("");
      setReplacingKey(!p.has_api_key);
      setNotice("Profil disimpan");
      qc.invalidateQueries({ queryKey: ["profiles"] });
      onSaved(p);
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors(Object.keys(e.fieldErrors).length ? e.fieldErrors : { _: e.message });
      else setErrors({ _: String(e) });
    },
  });

  const remove = useMutation({
    mutationFn: () => api.deleteProfile(profile!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profiles"] });
      onDeleted();
    },
  });

  const testConn = useMutation({ mutationFn: () => api.testProfile(profile!.id), onSuccess: setTest });
  const fetchModels = useMutation({
    mutationFn: () => api.listModels(profile!.id),
    onSuccess: (r) => {
      setModels(r.models);
      setModelsMessage(r.message);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setNotice(null);
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "Wajib diisi";
    if (!form.model.trim()) next.model = "Wajib diisi";
    if (form.provider === "openai_compatible" && !form.base_url.trim()) next.base_url = BASE_URL_REQUIRED;
    else if (form.provider === "openai_compatible" && !/^https?:\/\//.test(form.base_url.trim()))
      next.base_url = "Base URL harus diawali http:// atau https://";
    setErrors(next);
    if (Object.keys(next).length === 0) save.mutate();
  };

  return (
    <Card className="p-6">
      <form onSubmit={submit} noValidate className="flex flex-col gap-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-semibold">{profile ? profile.name : "Profil AI baru"}</h2>
            <p className="mt-1 text-sm text-fg-muted">Profil yang dipakai agent untuk berpikir dan membaca layar.</p>
          </div>
          {profile?.is_default && (
            <span className="rounded-md border border-accent-line bg-accent-soft px-2 py-1 text-xs font-medium text-accent">Default</span>
          )}
        </div>

        <Field label="Nama profil" htmlFor="pf-name" error={errors.name}>
          <Input id="pf-name" value={form.name} placeholder="AI kantor (GLM)" onChange={(e) => set("name", e.target.value)} aria-invalid={!!errors.name} />
        </Field>

        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium" id="pf-provider-label">
            Jenis API
          </span>
          <div role="radiogroup" aria-labelledby="pf-provider-label" className="inline-flex w-fit rounded-lg border border-ink-700 bg-ink-850 p-1 text-sm">
            {(
              [
                ["openai_compatible", "OpenAI-compatible"],
                ["anthropic", "Anthropic (Claude)"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={form.provider === value}
                onClick={() => set("provider", value)}
                className={cn(
                  "rounded-md px-4 py-1.5",
                  form.provider === value ? "border border-ink-700 bg-ink-900 font-medium shadow-sm" : "text-fg-muted",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-xs text-fg-muted">
            {form.provider === "anthropic"
              ? "Memakai API Anthropic resmi untuk model Claude."
              : "Cocok untuk AI kantor (GLM, DeepSeek, MiniMax), OpenAI GPT, Azure OpenAI, Ollama, atau LM Studio."}
          </p>
        </div>

        {form.provider === "openai_compatible" && (
          <Field
            label="Base URL endpoint"
            htmlFor="pf-base"
            error={errors.base_url}
            hint={
              <>
                Untuk OpenAI GPT isi <span className="font-mono">https://api.openai.com/v1</span>.
              </>
            }
          >
            <div className="relative">
              <LinkSimple className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" />
              <Input
                id="pf-base"
                className="pl-9 font-mono"
                value={form.base_url}
                placeholder="http://192.168.151.121/v1"
                onChange={(e) => set("base_url", e.target.value)}
                aria-invalid={!!errors.base_url}
              />
            </div>
          </Field>
        )}

        <div className="flex flex-col gap-1.5">
          {replacingKey ? (
            <Field label="API key" htmlFor="pf-key" error={errors.api_key}>
              <div className="relative">
                <Key className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" />
                <Input
                  id="pf-key"
                  type="password"
                  autoComplete="off"
                  className="pl-9 font-mono"
                  value={apiKey}
                  placeholder={profile?.has_api_key ? "Kosongkan bila tidak diganti" : "sk-..."}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              </div>
            </Field>
          ) : (
            <>
              <span className="text-sm font-medium">API key</span>
              <div className="flex gap-2">
                <div className="flex h-10 flex-1 items-center gap-3 rounded-lg border border-ink-600 bg-ink-900 px-3">
                  <Key className="text-fg-muted" />
                  <span className="font-mono text-sm tracking-wider">{profile?.api_key_masked}</span>
                </div>
                <Button onClick={() => setReplacingKey(true)}>Ganti</Button>
              </div>
            </>
          )}
          <p className="flex items-center gap-1.5 text-xs text-fg-muted">
            <LockSimple />
            Disimpan di Windows Credential Manager laptop ini. Tidak pernah masuk ke laporan atau Git.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label htmlFor="pf-model" className="text-sm font-medium">
              Model
            </label>
            {profile && form.provider === "openai_compatible" && (
              <button
                type="button"
                onClick={() => fetchModels.mutate()}
                disabled={fetchModels.isPending}
                className="flex items-center gap-1.5 text-sm text-accent"
              >
                <ArrowsClockwise className={cn(fetchModels.isPending && "animate-spin")} />
                Ambil daftar model
              </button>
            )}
          </div>
          <Input id="pf-model" className="font-mono" value={form.model} placeholder="z-ai/glm-5.3-flash" onChange={(e) => set("model", e.target.value)} aria-invalid={!!errors.model} />
          {errors.model && (
            <p role="alert" className="text-xs text-fail">
              {errors.model}
            </p>
          )}
          {models.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {models.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => set("model", m)}
                  className={cn(
                    "flex h-9 items-center gap-2 rounded-lg border px-3.5 font-mono text-sm",
                    form.model === m ? "border-accent-line bg-accent-soft text-accent" : "border-ink-700 text-fg-muted hover:bg-ink-850",
                  )}
                >
                  {form.model === m && <CheckCircle weight="fill" />}
                  {m}
                </button>
              ))}
            </div>
          )}
          {modelsMessage && <p className="text-xs text-fg-muted">{modelsMessage}</p>}
        </div>

        <div className="grid grid-cols-2 gap-5">
          <div className="rounded-lg border border-ink-700 p-4">
            <Switch
              id="pf-vision"
              checked={form.vision}
              onChange={(v) => set("vision", v)}
              label="Bisa membaca gambar"
              description="Screenshot layar ikut dikirim ke AI"
            />
          </div>
          <Field label="Batas waktu jawaban" htmlFor="pf-timeout">
            <Select id="pf-timeout" value={form.timeout_seconds} onChange={(e) => set("timeout_seconds", Number(e.target.value))}>
              {[30, 60, 120, 180, 300].map((s) => (
                <option key={s} value={s}>
                  {s} detik
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.is_default} onChange={(e) => set("is_default", e.target.checked)} className="h-4 w-4 accent-[var(--color-accent)]" />
          Jadikan profil default
        </label>

        {test && (
          <div
            role="status"
            className={cn(
              "flex items-start gap-3 rounded-lg border px-4 py-3 text-sm",
              test.text_ok ? "border-pass/30 bg-pass/5" : "border-fail/30 bg-fail/5",
            )}
          >
            {test.text_ok ? <CheckCircle weight="fill" className="text-lg text-pass" /> : <WarningCircle weight="fill" className="text-lg text-fail" />}
            <div>
              <div className="font-medium">{test.text_ok ? "Terhubung" : "Tidak terhubung"}</div>
              <div className="text-fg-muted">
                {test.text_ok
                  ? `Teks OK${form.vision ? (test.vision_ok ? " dan gambar OK" : ", gambar belum terbaca") : ""}. Waktu respons ${(test.latency_ms / 1000).toLocaleString("id-ID", { maximumFractionDigits: 1 })} detik.`
                  : null}
              </div>
              {(!test.text_ok || (form.vision && !test.vision_ok)) && <div className="text-fg-muted">{test.message}</div>}
            </div>
          </div>
        )}
        {errors._ && <Alert tone="error">{errors._}</Alert>}
        {notice && <Alert tone="success">{notice}</Alert>}

        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" size="lg" disabled={save.isPending}>
            <FloppyDisk />
            Simpan
          </Button>
          {profile && (
            <Button size="lg" onClick={() => testConn.mutate()} disabled={testConn.isPending}>
              <PlugsConnected />
              {testConn.isPending ? "Menguji..." : "Tes koneksi"}
            </Button>
          )}
          {profile && (
            <Button variant="ghost" size="lg" className="ml-auto text-fail" onClick={() => remove.mutate()}>
              <Trash />
              Hapus profil
            </Button>
          )}
        </div>
      </form>
    </Card>
  );
}

function AccountsTab() {
  const apps = useQuery({ queryKey: ["apps"], queryFn: api.listApps });
  const [appId, setAppId] = useState<number | null>(null);
  const current = appId ?? apps.data?.[0]?.id ?? null;
  if (apps.isLoading) return <Skeleton className="h-60" />;
  if (!apps.data?.length)
    return (
      <Card>
        <EmptyState title="Belum ada aplikasi" description="Tambahkan aplikasi di menu Aplikasi, lalu atur akun test di sini." />
      </Card>
    );
  return (
    <Card className="flex flex-col gap-5 p-6">
      <Field label="Aplikasi" htmlFor="acc-app" className="max-w-sm">
        <Select id="acc-app" value={current ?? ""} onChange={(e) => setAppId(Number(e.target.value))}>
          {apps.data.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
      </Field>
      {current && <AccountsPanel appId={current} />}
    </Card>
  );
}
