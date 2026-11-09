import { AndroidLogo, BookmarkSimple, FileArrowUp, Globe, GlobeSimple, MapTrifold, Play, ShieldWarning, Target, X } from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type DragEvent, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AndroidTarget, PhonePreview } from "@/components/AndroidTarget";
import { PlatformIcon } from "@/components/RunBits";
import { Alert, Button, Field, PageHeader, Select, Switch } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { ApkChoice, App, RunInput } from "@/lib/types";
import { timeAgo } from "@/lib/format";

const normalizeUrl = (u: string) => u.trim().replace(/\/+$/, "").toLowerCase();

export function RunNewPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const apps = useQuery({ queryKey: ["apps"], queryFn: api.listApps });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: api.listProfiles });

  const [platform, setPlatform] = useState<"web" | "android">(params.get("platform") === "android" ? "android" : "web");
  const [serial, setSerial] = useState("");
  const [apk, setApk] = useState<ApkChoice | null>(null);
  const [url, setUrl] = useState("");
  const [appId, setAppId] = useState<number | null>(null);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [environment, setEnvironment] = useState<"dev" | "production">("dev");
  const [mode, setMode] = useState<"explore" | "deep">("explore");
  const [module, setModule] = useState("");
  const [confirmEach, setConfirmEach] = useState(false);
  const [reviewFirst, setReviewFirst] = useState(false);
  // Regresi: ?reuse=<run> memakai test case run itu (tanpa AI menyusun ulang)
  const reuseId = Number(params.get("reuse")) || null;
  const [reuse, setReuse] = useState<number | null>(reuseId);
  const reuseRun = useQuery({ queryKey: ["run", reuseId], queryFn: () => api.getRun(reuseId!), enabled: !!reuseId });
  const [prd, setPrd] = useState<{ name: string; text: string } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // aplikasi dari ?app= atau dari URL yang cocok
  useEffect(() => {
    const fromQuery = Number(params.get("app"));
    if (!apps.data || appId !== null || !fromQuery) return;
    const found = apps.data.find((a) => a.id === fromQuery);
    if (found) selectApp(found);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apps.data]);

  const androidPackage = url.startsWith("android://") ? url.slice("android://".length) : "";
  const setAndroidPackage = (pkg: string) => {
    setUrl(pkg ? `android://${pkg}` : "");
    setAppId(null);
    setAccountId(null);
  };
  const switchPlatform = (next: "web" | "android") => {
    if (next === platform) return;
    setPlatform(next);
    setUrl("");
    setAppId(null);
    setAccountId(null);
    setErrors({});
  };

  const matched: App | null = useMemo(() => {
    if (appId !== null) return apps.data?.find((a) => a.id === appId) ?? null;
    return apps.data?.find((a) => normalizeUrl(a.url) === normalizeUrl(url)) ?? null;
  }, [apps.data, appId, url]);

  useEffect(() => {
    if (profileId === null && profiles.data?.length) {
      setProfileId((profiles.data.find((p) => p.is_default) ?? profiles.data[0]).id);
    }
  }, [profiles.data, profileId]);

  const accounts = useQuery({
    queryKey: ["accounts", matched?.id],
    queryFn: () => api.listAccounts(matched!.id),
    enabled: !!matched,
  });
  const modules = useQuery({
    queryKey: ["modules", matched?.id],
    queryFn: () => api.appModules(matched!.id),
    enabled: !!matched,
  });

  useEffect(() => {
    if (accounts.data && accountId === null && accounts.data.length) setAccountId(accounts.data[0].id);
  }, [accounts.data, accountId]);

  const explored = !!modules.data?.explored;
  useEffect(() => {
    if (!explored && mode === "deep") setMode("explore");
  }, [explored, mode]);
  useEffect(() => {
    // modul mengikuti run sumber test case
    if (reuse && reuseRun.data?.module && explored && matched?.id === reuseRun.data.app_id) {
      setMode("deep");
      setModule(reuseRun.data.module);
    }
  }, [reuse, reuseRun.data, explored, matched?.id]);

  function selectApp(a: App) {
    setPlatform(a.platform === "android" ? "android" : "web");
    setAppId(a.id);
    setUrl(a.url);
    setAccountId(null);
    setModule("");
  }

  const ensureApp = async (): Promise<App> => {
    if (matched) return matched;
    const host = platform === "android" ? androidPackage : new URL(url.trim()).host;
    return api.createApp({ name: host, platform, url: url.trim(), allowed_domains: [], login_endpoints: [] });
  };

  const targetError = (): Record<string, string> => {
    const next: Record<string, string> = {};
    if (platform === "web" && !/^https?:\/\/\S+$/.test(url.trim())) next.url = "URL harus diawali http:// atau https://";
    if (platform === "android" && !androidPackage) next.package = "Pilih aplikasi yang akan diuji";
    return next;
  };

  const saveApp = useMutation({
    mutationFn: ensureApp,
    onSuccess: (app) => navigate(`/apps?app=${app.id}`),
    onError: (e) => setErrors({ _: e instanceof Error ? e.message : String(e) }),
  });

  const start = useMutation({
    mutationFn: async () => {
      const app = await ensureApp();
      const body: RunInput = {
        app_id: app.id,
        mode,
        module: mode === "deep" ? module : null,
        prd_text: prd?.text ?? null,
        profile_id: profileId,
        account_id: matched ? accountId : null,
        environment,
        confirm_each_step: confirmEach,
        device_serial: platform === "android" ? serial : null,
        ...(platform === "android" && apk ? { apk_file: apk.file, apk_grant: apk.grant, apk_uninstall: apk.uninstall } : {}),
        ...(mode === "deep" && reviewFirst ? { review_first: true } : {}),
        ...(mode === "deep" && reuse ? { reuse_cases_from: reuse } : {}),
      };
      return api.createRun(body);
    },
    onSuccess: (run) => navigate(`/runs/${run.id}`),
    onError: (e) => {
      if (e instanceof ApiError) setErrors(Object.keys(e.fieldErrors).length ? e.fieldErrors : { _: e.message });
      else setErrors({ _: String(e) });
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next: Record<string, string> = targetError();
    if (platform === "android" && !serial) next._ = "Pilih perangkat Android yang siap dipakai";
    if (mode === "deep" && !module) next.module = "Pilih modul yang akan diuji";
    if (!profiles.data?.length) next._ = "Belum ada profil AI. Tambahkan di Pengaturan > Model AI.";
    setErrors(next);
    if (Object.keys(next).length === 0) start.mutate();
  };

  const readPrd = async (file: File | undefined) => {
    if (!file) return;
    if (!/\.(md|txt)$/i.test(file.name)) {
      setErrors((x) => ({ ...x, prd: "PRD harus berupa file .md atau .txt" }));
      return;
    }
    setErrors((x) => ({ ...x, prd: "" }));
    setPrd({ name: file.name, text: await file.text() });
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    void readPrd(e.dataTransfer.files?.[0]);
  };

  const profileField = (
    <Field label="Profil AI" htmlFor="run-profile">
      <Select id="run-profile" value={profileId ?? ""} onChange={(e) => setProfileId(Number(e.target.value))}>
        {(profiles.data ?? []).map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </Select>
    </Field>
  );
  const accountField = (
    <Field
      label="Akun test"
      htmlFor="run-account"
      hint={
        url && (!matched || accounts.data?.length === 0)
          ? "Aplikasi ini belum punya akun test. Klik Simpan aplikasi lalu isi akunnya bila aplikasi butuh login."
          : undefined
      }
    >
      <Select
        id="run-account"
        value={accountId ?? ""}
        disabled={!matched || !accounts.data?.length}
        onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}
      >
        {!accounts.data?.length && <option value="">Tanpa login</option>}
        {(accounts.data ?? []).map((a) => (
          <option key={a.id} value={a.id}>
            {a.role} · {a.username}
          </option>
        ))}
      </Select>
    </Field>
  );

  return (
    <main className="flex flex-col gap-8 px-10 py-8">
      <PageHeader
        title="Run baru"
        description={platform === "android" ? "Pilih HP atau emulator, lalu uji aplikasi yang sudah terpasang atau upload file APK." : "Pilih target, lalu agent menguji dan menyusun test case beserta evidence."}
        actions={
          <div role="radiogroup" aria-label="Platform" className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-1 text-sm">
            {(
              [
                ["web", "Web", Globe],
                ["android", "Android", AndroidLogo],
              ] as const
            ).map(([value, label, Icon]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={platform === value}
                onClick={() => switchPlatform(value)}
                className={cn(
                  "flex items-center gap-2 rounded-md px-4 py-1.5",
                  platform === value ? "bg-ink-800 text-fg" : "text-fg-muted hover:text-fg",
                )}
              >
                <Icon />
                {label}
              </button>
            ))}
          </div>
        }
      />

      <div className={cn("grid gap-10", platform === "android" ? "grid-cols-[minmax(0,1fr)_300px]" : "grid-cols-[minmax(0,1fr)_340px]")}>
        <form onSubmit={submit} noValidate className="flex flex-col gap-7">
          {platform === "android" ? (
            <AndroidTarget
              serial={serial}
              onSerial={setSerial}
              pkg={androidPackage}
              onPackage={setAndroidPackage}
              error={errors.package}
              onApk={setApk}
            />
          ) : (
          <Field
            label="URL aplikasi"
            htmlFor="run-url"
            error={errors.url}
            hint={matched ? `Aplikasi tersimpan: ${matched.name}. Agent hanya membuka domain yang diizinkan.` : "Agent hanya menjelajah domain ini. Link ke domain lain tidak akan diklik."}
          >
            <div className="relative">
              <GlobeSimple className="absolute left-4 top-1/2 -translate-y-1/2 text-lg text-fg-muted" />
              <input
                id="run-url"
                value={url}
                placeholder="https://hr-dev.kantor.local"
                onChange={(e) => {
                  setUrl(e.target.value);
                  setAppId(null);
                  setAccountId(null);
                }}
                aria-invalid={!!errors.url}
                className="h-12 w-full rounded-lg border border-ink-600 bg-ink-900 pl-11 pr-4 font-mono text-[15px] focus:border-accent-line focus:outline-none focus:ring-4 focus:ring-accent-soft aria-[invalid=true]:border-fail"
              />
            </div>
          </Field>
          )}

          {platform === "android" ? (
            <>
              <div className="grid grid-cols-3 gap-5">
                {profileField}
                <Field
                  label="Yang diuji"
                  htmlFor="run-scope"
                  error={errors.module}
                  hint={
                    !explored
                      ? "Jalankan Seluruh aplikasi dulu untuk menguji satu modul"
                      : `${modules.data?.modules.length ?? 0} modul hasil penjelajahan bisa diuji satu per satu`
                  }
                >
                  <Select
                    id="run-scope"
                    value={mode === "deep" ? `deep:${module}` : "explore"}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === "explore") {
                        setMode("explore");
                        setModule("");
                      } else {
                        setMode("deep");
                        setModule(v.slice("deep:".length));
                      }
                    }}
                  >
                    <option value="explore">Seluruh aplikasi (petakan semua menu)</option>
                    {(modules.data?.modules ?? []).length > 0 && (
                      <optgroup label="Satu modul (uji mendalam)">
                        {(modules.data?.modules ?? []).map((m) => (
                          <option key={m} value={`deep:${m}`}>
                            Satu modul: {m}
                          </option>
                        ))}
                      </optgroup>
                    )}
                  </Select>
                </Field>
                {accountField}
              </div>
            </>
          ) : (
          <>
          <div className="grid grid-cols-3 gap-5">
            {profileField}
            {accountField}
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium" id="env-label">
                Environment
              </span>
              <div role="radiogroup" aria-labelledby="env-label" className="inline-flex h-10 rounded-lg border border-ink-700 bg-ink-900 p-1 text-sm">
                {(
                  [
                    ["dev", "Dev / UAT"],
                    ["production", "Production"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={environment === value}
                    onClick={() => setEnvironment(value)}
                    className={cn(
                      "flex flex-1 items-center justify-center gap-1.5 rounded-md",
                      environment === value ? "bg-ink-800 font-medium" : "text-fg-muted",
                    )}
                  >
                    {value === "production" && <ShieldWarning />}
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          {environment === "production" && (
            <Alert tone="warning">
              Mode production: agent tidak akan menyimpan, menghapus, atau mengirim data. Semua request pengubah data diblok di level jaringan, kecuali login.
            </Alert>
          )}

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium" id="mode-label">
              Yang diuji
            </span>
            <div role="radiogroup" aria-labelledby="mode-label" className="grid grid-cols-2 gap-4">
              <ModeCard
                selected={mode === "explore"}
                onSelect={() => setMode("explore")}
                icon={<MapTrifold className="text-lg text-accent" />}
                title="Seluruh aplikasi"
                text="Petakan semua menu dan halaman. Tidak mengisi atau mengirim form."
              />
              <ModeCard
                selected={mode === "deep"}
                disabled={!explored}
                onSelect={() => setMode("deep")}
                icon={<Target className={cn("text-lg", mode === "deep" ? "text-accent" : "text-fg-muted")} />}
                title="Satu modul"
                text="Uji mendalam: positif, negatif, validasi, batas input."
                hint={
                  !explored
                    ? matched || url.trim()
                      ? `${matched?.name ?? url.trim().replace(/^https?:\/\//, "").replace(/\/$/, "")} belum dipetakan. Jalankan Seluruh aplikasi dulu untuk memetakan modul`
                      : "Jalankan Seluruh aplikasi dulu untuk memetakan modul"
                    : undefined
                }
              />
            </div>
          </div>

          {mode === "deep" && (
            <Field label="Modul" htmlFor="run-module" error={errors.module} className="max-w-md">
              <Select id="run-module" value={module} onChange={(e) => setModule(e.target.value)} aria-invalid={!!errors.module}>
                <option value="">Pilih modul...</option>
                {(modules.data?.modules ?? []).map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          </>
          )}

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">
              PRD <span className="font-normal text-fg-dim">(opsional)</span>
            </span>
            {prd ? (
              <div className="flex h-20 items-center gap-3 rounded-xl border border-ink-600 bg-ink-900 px-4 text-sm">
                <FileArrowUp className="text-xl text-accent" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{prd.name}</div>
                  <div className="text-xs text-fg-muted">
                    {mode === "deep" ? "Dipakai AI untuk menyusun expected result test case." : "Disimpan dan dipakai otomatis saat menguji Satu modul."}
                  </div>
                </div>
                <button type="button" aria-label="Hapus PRD" className="text-fg-muted hover:text-fg" onClick={() => setPrd(null)}>
                  <X />
                </button>
              </div>
            ) : (
              <label
                onDragOver={(e) => e.preventDefault()}
                onDrop={onDrop}
                className="grid h-20 cursor-pointer place-items-center rounded-xl border border-dashed border-ink-600 text-sm text-fg-muted hover:bg-ink-850"
              >
                <span className="flex items-center gap-2">
                  <FileArrowUp className="text-lg" />
                  Tarik file .md atau .txt ke sini, atau klik untuk memilih
                </span>
                <input aria-label="File PRD" type="file" accept=".md,.txt" className="sr-only" onChange={(e) => void readPrd(e.target.files?.[0])} />
              </label>
            )}
            {errors.prd && <p className="text-xs text-fail">{errors.prd}</p>}
          </div>
          {mode === "deep" && reuse && reuseRun.data && (
            <Alert
              tone="info"
              action={
                <Button size="sm" variant="ghost" onClick={() => setReuse(null)}>
                  Susun ulang oleh AI
                </Button>
              }
            >
              Memakai test case yang sama dengan run #{reuseRun.data.id} (modul {reuseRun.data.module}) untuk regresi. AI tidak
              menyusun ulang test case.
            </Alert>
          )}
          {mode === "deep" && (
            <div className="rounded-lg border border-ink-700 bg-ink-900 p-4">
              <Switch
                id="run-review"
                checked={reviewFirst}
                onChange={setReviewFirst}
                label="Review test case dulu sebelum dijalankan"
                description="Run berhenti setelah test case disusun. Kamu bisa edit, hapus, atau tambah test case, lalu jalankan."
              />
            </div>
          )}
          <div className="rounded-lg border border-ink-700 bg-ink-900 p-4">
            <Switch
              id="run-confirm"
              checked={confirmEach}
              onChange={setConfirmEach}
              label="Konfirmasi tiap langkah"
              description="Agent berhenti setelah merencanakan setiap langkah dan menunggu kamu klik Jalankan."
            />
          </div>

          {errors._ && <Alert tone="error">{errors._}</Alert>}

          <div className="flex items-center gap-3 pt-2">
            <Button type="submit" variant="primary" size="lg" disabled={start.isPending || (platform === "android" && !serial)}>
              <Play weight="fill" />
              {start.isPending ? "Menyiapkan..." : "Mulai run"}
            </Button>
            <Button
              size="lg"
              disabled={saveApp.isPending}
              onClick={() => {
                const next = targetError();
                setErrors(next);
                if (Object.keys(next).length === 0) saveApp.mutate();
              }}
            >
              <BookmarkSimple />
              Simpan aplikasi
            </Button>
          </div>
        </form>

        {platform === "android" ? (
          <PhonePreview serial={serial} />
        ) : (
        <aside className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-fg-muted">Aplikasi tersimpan</h2>
          {apps.data && apps.data.length > 0 ? (
            <div className="divide-y divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
              {apps.data.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => selectApp(a)}
                  className={cn("block w-full p-4 text-left hover:bg-ink-850", matched?.id === a.id && "bg-accent-soft")}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2 font-medium">
                      <PlatformIcon platform={a.platform} />
                      <span className="truncate">{a.name}</span>
                    </span>
                    <span className="shrink-0 text-xs text-fg-dim">{a.last_run_at ? timeAgo(a.last_run_at) : "belum pernah"}</span>
                  </div>
                  <div className="mt-0.5 truncate font-mono text-xs text-fg-dim">{a.url.replace(/^(https?|android):\/\//, "")}</div>
                  <div className="mt-2 text-xs text-fg-muted">{a.explored ? "Modul sudah dipetakan" : "Belum dipetakan"}</div>
                </button>
              ))}
            </div>
          ) : (
            <p className="rounded-xl border border-ink-700 bg-ink-900 p-4 text-sm text-fg-muted">
              Belum ada. URL yang kamu jalankan akan tersimpan otomatis.
            </p>
          )}
        </aside>
        )}
      </div>
    </main>
  );
}

function ModeCard({
  selected,
  disabled,
  onSelect,
  icon,
  title,
  text,
  hint,
}: {
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
  icon: React.ReactNode;
  title: string;
  text: string;
  hint?: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        "flex flex-col justify-start rounded-xl border p-4 text-left",
        selected ? "border-accent-line bg-accent-soft" : "border-ink-700 bg-ink-900 hover:bg-ink-850",
        disabled && "opacity-60 hover:bg-ink-900",
      )}
    >
      <div className="flex items-center gap-2 font-medium">
        {icon}
        {title}
      </div>
      <p className="mt-1.5 text-sm text-fg-muted">{text}</p>
      {hint && <p className="mt-2 text-xs text-review">{hint}</p>}
    </button>
  );
}
