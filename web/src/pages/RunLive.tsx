import {
  ArrowLeft,
  Brain,
  CaretRight,
  CheckCircle,
  Circle,
  CircleNotch,
  CursorClick,
  GlobeSimple,
  HandPointing,
  MinusCircle,
  Pause,
  Play,
  Robot,
  Stop,
  User,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Logo } from "@/components/AppShell";
import { InterventionPanel } from "@/components/InterventionPanel";
import { LiveView, type Overlay } from "@/components/LiveView";
import { Alert, Button } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { duration, scopeLabel } from "@/lib/format";
import type { ControlInput, Snapshot, Status, StepEvent } from "@/lib/types";
import { useRunStream } from "@/lib/ws";

function useNow(intervalMs = 1000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

type Pill = { label: string; tone: "accent" | "review" | "pass" | "fail" | "muted" };

export function statusPill(snap: Snapshot | null, runStatus?: string): Pill {
  const status = snap?.status ?? runStatus;
  const control = snap?.control_state;
  if (status === "running" || status === "queued") {
    if (status === "queued") return { label: "Menunggu", tone: "muted" };
    if (control === "paused") return { label: "Dijeda", tone: "review" };
    if (control === "takeover") return { label: "Ambil alih", tone: "accent" };
    if (control === "stopped") return { label: "Menghentikan", tone: "muted" };
    return { label: "Berjalan", tone: "accent" };
  }
  if (status === "paused") return { label: "Dijeda", tone: "review" };
  if (status === "completed") return { label: "Selesai", tone: "pass" };
  if (status === "interrupted") return { label: "Terhenti", tone: "fail" };
  return { label: "Memuat", tone: "muted" };
}

const PILL_STYLE: Record<Pill["tone"], string> = {
  accent: "border-accent-line bg-accent-soft text-accent",
  review: "border-review/40 bg-review/10 text-review",
  pass: "border-pass/40 bg-pass/10 text-pass",
  fail: "border-fail/40 bg-fail/10 text-fail",
  muted: "border-ink-600 bg-ink-850 text-fg-muted",
};

function CaseIcon({ status, current }: { status: Status | null; current: boolean }) {
  if (current) return <CircleNotch className="mt-px animate-spin text-lg text-accent" />;
  if (status === "Pass") return <CheckCircle weight="fill" className="mt-px text-lg text-pass" />;
  if (status === "Fail") return <XCircle weight="fill" className="mt-px text-lg text-fail" />;
  if (status === "Perlu Review") return <WarningCircle weight="fill" className="mt-px text-lg text-review" />;
  if (status === "Blocked" || status === "Skipped") return <MinusCircle weight="fill" className="mt-px text-lg text-fg-dim" />;
  return <Circle className="mt-px text-lg text-fg-dim" />;
}

export function RunLivePage() {
  const runId = Number(useParams().runId);
  const qc = useQueryClient();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.getRun(runId), refetchInterval: 5000 });
  const { snapshot, steps, frame, connected } = useRunStream(Number.isFinite(runId) ? runId : null);
  const [error, setError] = useState<string | null>(null);
  const [confirmedKey, setConfirmedKey] = useState<string | null>(null);
  const now = useNow();

  const status = snapshot?.status ?? run.data?.status;
  const control = snapshot?.control_state ?? null;
  const active = status === "running" || status === "queued";
  const pill = statusPill(snapshot, run.data?.status);
  const cases = snapshot?.cases ?? [];
  const currentTc = snapshot?.current_tc ?? null;
  const currentCase = cases.find((c) => c.tc_id === currentTc) ?? null;
  const currentIndex = currentTc ? cases.findIndex((c) => c.tc_id === currentTc) + 1 : 0;
  const tcSteps = useMemo<StepEvent[]>(
    () => steps.filter((s) => (currentTc ? s.tc_id === currentTc : true)).slice(-12),
    [steps, currentTc],
  );
  const planned = snapshot?.planned ?? null;
  const lastStep = tcSteps[tcSteps.length - 1];
  const overlay: Overlay =
    planned?.element && planned.viewport
      ? { bbox: planned.element.bbox, viewport: planned.viewport, label: planned.element.name || undefined }
      : null;

  useEffect(() => {
    if (status) qc.invalidateQueries({ queryKey: ["run", runId] });
  }, [status, qc, runId]);

  const plannedKey = planned ? `${planned.tc_id}#${planned.step_no}` : null;
  const awaitingConfirm = Boolean(snapshot?.awaiting_confirm) && plannedKey !== null && plannedKey !== confirmedKey;

  const send = async (cmd: ControlInput) => {
    setError(null);
    if (cmd.command === "confirm_step") setConfirmedKey(plannedKey); // cegah klik ganda untuk langkah yang sama
    try {
      await api.control(runId, cmd);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const resume = async () => {
    setError(null);
    try {
      await api.resumeRun(runId);
      qc.invalidateQueries({ queryKey: ["run", runId] });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const r = run.data;
  const progress =
    r?.mode === "explore"
      ? `${snapshot?.screens ?? 0} layar dipetakan`
      : cases.length
        ? `Test case ${currentIndex || cases.filter((c) => c.status).length} dari ${cases.length}`
        : "Menyusun test case...";

  return (
    <div className="grid h-[100dvh] grid-rows-[64px_auto_1fr] overflow-hidden bg-ink-950">
      <header className="flex items-center gap-5 border-b border-ink-700 bg-ink-900 px-5">
        <Link to="/" aria-label="Kembali ke dashboard" className="flex items-center gap-2 text-fg-muted hover:text-fg">
          <ArrowLeft />
          <Logo />
        </Link>
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <span className="truncate text-fg-muted">{r?.app_name ?? "..."}</span>
          <CaretRight className="text-fg-dim" />
          <span className="truncate font-medium">{r ? (r.mode === "explore" ? "Jelajahi seluruh aplikasi" : `Uji modul ${r.module}`) : ""}</span>
        </div>
        <span className={cn("inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs font-medium", PILL_STYLE[pill.tone])}>
          <span className={cn("h-1.5 w-1.5 rounded-full bg-current", pill.tone === "accent" && "animate-pulse")} />
          {pill.label}
        </span>
        <div className="flex items-center gap-4 text-sm text-fg-muted">
          {r && <span className="font-mono">{duration(r.started_at, active ? null : r.finished_at, now)}</span>}
          <span>{progress}</span>
          {!connected && <span className="text-xs text-review">Menyambung ulang...</span>}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {control === "paused" ? (
            <Button disabled={!active} onClick={() => send({ command: "resume" })}>
              <Play />
              Lanjutkan
            </Button>
          ) : (
            <Button disabled={!active || control === "takeover" || control === "stopped"} onClick={() => send({ command: "pause" })}>
              <Pause />
              Jeda
            </Button>
          )}
          {control === "takeover" ? (
            <Button variant="primary" disabled={!active} onClick={() => send({ command: "release" })}>
              <Robot />
              Kembalikan ke AI
            </Button>
          ) : (
            <Button variant="primary" disabled={!active || control === "stopped"} onClick={() => send({ command: "takeover" })}>
              <HandPointing />
              Ambil alih
            </Button>
          )}
          <Button variant="danger" disabled={!active || control === "stopped"} onClick={() => send({ command: "stop" })}>
            <Stop />
            Hentikan
          </Button>
        </div>
      </header>

      <div className="flex flex-col gap-2 px-5 [&:not(:empty)]:pt-3">
        {error && <Alert tone="error">{error}</Alert>}
        {status === "paused" && (
          <Alert
            tone="warning"
            action={
              <Button size="sm" variant="primary" onClick={resume}>
                Coba lagi
              </Button>
            }
          >
            <span className="font-medium">Run dijeda otomatis.</span> {snapshot?.note || r?.note}
            {(snapshot?.note || r?.note || "").includes("Login") && (
              <>
                {" "}
                <Link to="/apps" className="text-accent underline">
                  Buka pengaturan akun
                </Link>
              </>
            )}
          </Alert>
        )}
        {status === "interrupted" && (
          <Alert
            tone="error"
            action={
              <div className="flex gap-2">
                <Button size="sm" onClick={resume}>
                  Lanjutkan run
                </Button>
                <Link to={`/runs/${runId}/result`} className="inline-flex h-8 items-center rounded-lg border border-ink-600 px-2.5 text-xs">
                  Lihat hasil parsial
                </Link>
              </div>
            }
          >
            <span className="font-medium">Run terhenti.</span> {snapshot?.note || r?.note}
          </Alert>
        )}
        {status === "completed" && (
          <Alert
            tone="success"
            action={
              <Link to={`/runs/${runId}/result`} className="inline-flex h-8 items-center rounded-lg bg-accent px-3 text-xs font-semibold text-white">
                Lihat hasil
              </Link>
            }
          >
            <span className="font-medium">Run selesai.</span> Dokumen test case dan evidence siap direview.
          </Alert>
        )}
      </div>

      <div className="grid min-h-0 grid-cols-[260px_minmax(0,1fr)_380px]">
        <aside className="flex min-h-0 flex-col overflow-hidden border-r border-ink-700 bg-ink-900">
          <div className="flex items-center justify-between border-b border-ink-700 px-4 py-3 text-xs text-fg-muted">
            <span>{r?.mode === "explore" ? "Penjelajahan" : "Test case"}</span>
            <span className="font-mono">
              {(["Pass", "Fail", "Perlu Review"] as const)
                .map((s) => [s, cases.filter((c) => c.status === s).length] as const)
                .filter(([, n]) => n > 0)
                .map(([s, n]) => `${n} ${s === "Perlu Review" ? "Review" : s}`)
                .join(", ")}
            </span>
          </div>
          <ol className="flex flex-col gap-1 overflow-y-auto p-2 text-sm">
            {cases.length === 0 && (
              <li className="px-3 py-4 text-sm text-fg-muted">
                {r?.mode === "explore" ? "Agent memetakan menu dan halaman. Test case disusun saat menguji satu modul." : "Menunggu test case disusun AI..."}
              </li>
            )}
            {cases.map((c) => {
              const current = c.tc_id === currentTc;
              return (
                <li
                  key={c.tc_id}
                  className={cn(
                    "flex items-start gap-3 rounded-lg px-3 py-2.5",
                    current && "border border-ink-600 bg-ink-800",
                    !current && !c.status && "text-fg-muted",
                  )}
                >
                  <CaseIcon status={c.status} current={current} />
                  <div className="min-w-0">
                    <div className="font-mono text-xs text-fg-dim">{c.tc_id}</div>
                    <div className={cn(current && "font-medium")}>{c.title}</div>
                  </div>
                </li>
              );
            })}
          </ol>
        </aside>

        <section className="flex min-h-0 flex-col gap-3 overflow-y-auto p-5">
          <div className="flex flex-col overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
            <div className="flex h-10 items-center gap-3 border-b border-ink-700 bg-ink-850 px-3">
              <GlobeSimple className="text-fg-dim" />
              <div className="flex h-6 flex-1 items-center truncate rounded-md border border-ink-700 bg-ink-950 px-3 font-mono text-xs text-fg-muted">
                {r?.url.replace(/^https?:\/\//, "") ?? ""}
              </div>
              {active && <span className="rounded-md bg-fail/15 px-2 py-0.5 text-xs font-medium text-fail">LIVE</span>}
            </div>
            <LiveView frame={frame} overlay={overlay} takeover={control === "takeover"} onInput={(event) => send({ command: "input", event })} />
          </div>
          <div className="flex items-center justify-between gap-4 text-sm">
            <div className="flex min-w-0 items-center gap-2">
              {planned ? (
                <>
                  <span className="font-mono text-fg-dim">Langkah {planned.step_no}</span>
                  <span className="truncate">{planned.description}</span>
                </>
              ) : lastStep ? (
                <>
                  <span className="font-mono text-fg-dim">Langkah {lastStep.step_no}</span>
                  <span className="truncate text-fg-muted">{lastStep.description}</span>
                </>
              ) : (
                <span className="text-fg-muted">Belum ada langkah</span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-1.5 text-xs text-fg-muted">
              <CursorClick />
              {control === "takeover" ? "Klik langsung di layar untuk mengendalikan browser" : "Ambil alih untuk mengklik langsung di layar ini"}
            </div>
          </div>

          {tcSteps.some((s) => s.screenshot) && (
            <div className="mt-2 flex flex-col gap-2">
              <div className="text-xs text-fg-muted">Langkah sebelumnya{currentTc ? " di test case ini" : ""}</div>
              <div className="grid grid-cols-4 gap-3">
                {tcSteps
                  .filter((s) => s.screenshot)
                  .slice(-4)
                  .map((s, i, arr) => (
                    <figure key={`${s.tc_id}-${s.step_no}`} className={cn("overflow-hidden rounded-lg border bg-ink-900", i === arr.length - 1 ? "border-accent-line" : "border-ink-700")}>
                      <div className="aspect-[16/9] overflow-hidden bg-white">
                        <img src={api.fileUrl(runId, s.screenshot!)} alt={`Langkah ${s.step_no}`} className="h-full w-full object-cover object-top" loading="lazy" />
                      </div>
                      <figcaption className="truncate px-2.5 py-2 text-xs">
                        <span className={cn("font-mono", i === arr.length - 1 ? "text-accent" : "text-fg-dim")}>{s.step_no}</span>{" "}
                        <span className="text-fg-muted">{s.description}</span>
                      </figcaption>
                    </figure>
                  ))}
              </div>
            </div>
          )}
        </section>

        <aside className="flex min-h-0 flex-col border-l border-ink-700 bg-ink-900">
          <div className="border-b border-ink-700 px-5 pb-3 pt-4">
            {currentCase ? (
              <>
                <div className="font-mono text-xs text-fg-dim">{currentCase.tc_id}</div>
                <div className="mt-0.5 font-medium">{currentCase.title}</div>
              </>
            ) : (
              <div className="font-medium">{r ? scopeLabel(r) : ""}</div>
            )}
          </div>
          <ol className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-4 text-sm">
            {tcSteps.map((s) => (
              <li key={`${s.tc_id}-${s.step_no}`} className="flex gap-3">
                {s.actor === "manual" ? (
                  <User className="mt-0.5 shrink-0 text-accent" />
                ) : s.result.startsWith("error") ? (
                  <XCircle weight="fill" className="mt-0.5 shrink-0 text-fail" />
                ) : s.result === "skipped" ? (
                  <MinusCircle weight="fill" className="mt-0.5 shrink-0 text-review" />
                ) : (
                  <CheckCircle weight="fill" className="mt-0.5 shrink-0 text-pass" />
                )}
                <span className="text-fg-muted">{s.description}</span>
              </li>
            ))}
            {planned && (
              <li className="flex gap-3">
                <CircleNotch className="mt-0.5 shrink-0 animate-spin text-accent" />
                <div className="min-w-0">
                  <div className="font-medium">{planned.description}</div>
                  {planned.thought && (
                    <div className="mt-2 rounded-lg border border-ink-700 bg-ink-850 p-3 text-[13px] leading-relaxed text-fg-muted">
                      <div className="mb-1 flex items-center gap-1.5 text-xs text-fg-dim">
                        <Brain />
                        Pertimbangan AI
                      </div>
                      {planned.thought}
                    </div>
                  )}
                </div>
              </li>
            )}
            {!planned && tcSteps.length === 0 && <li className="text-fg-muted">Langkah akan muncul di sini saat agent bekerja.</li>}
          </ol>
          <InterventionPanel
            controlState={control}
            awaitingConfirm={awaitingConfirm}
            confirmEachStep={Boolean(snapshot?.confirm_each_step ?? r?.confirm_each_step)}
            active={active}
            onCommand={send}
          />
        </aside>
      </div>
    </div>
  );
}
