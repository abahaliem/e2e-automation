import { ArrowClockwise, CaretRight, Copy, FileHtml, FileText, FileXls, FloppyDisk, MagnifyingGlass } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AppMapView } from "@/components/AppMapView";
import { StatusBadge } from "@/components/StatusBadge";
import { Alert, Button, Card, EmptyState, Select, Skeleton, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { duration, formatDateTime } from "@/lib/format";
import type { CaseDetailResponse, Run, Severity, Status, TestCase } from "@/lib/types";

const STATUSES: Status[] = ["Pass", "Fail", "Perlu Review", "Blocked", "Skipped"];
const SEVERITIES: Severity[] = ["Critical", "Major", "Minor"];
const TYPE_LABEL: Record<string, string> = {
  positif: "Positif",
  negatif: "Negatif",
  validasi: "Validasi",
  boundary: "Boundary",
  navigasi: "Navigasi",
};
const isFinding = (c: TestCase) => c.effective_status === "Fail" || c.effective_status === "Perlu Review";
const NON_REPRO = new Set(["done", "blocked", "invalid", "hint"]);

export function bugReportText(tc: CaseDetailResponse, run?: Pick<Run, "app_name" | "url" | "environment">): string {
  const status = tc.effective_status ?? "Belum dijalankan";
  const repro = tc.log.filter((s) => !NON_REPRO.has(s.action)).map((s) => s.text);
  const steps = repro.length ? repro : tc.steps;
  const lines = [
    `[${tc.id}] ${tc.title}`,
    `Status: ${status}${tc.severity ? ` (${tc.severity})` : ""}`,
    run ? `Aplikasi: ${run.app_name} (${run.url}), environment ${run.environment === "production" ? "Production" : "Dev / UAT"}` : null,
    tc.precondition ? `Pre-condition: ${tc.precondition}` : null,
    tc.test_data ? `Test data: ${tc.test_data}` : null,
    "",
    "Langkah reproduksi:",
    ...steps.map((s, i) => `${i + 1}. ${s}`),
    "",
    `Expected: ${tc.expected}`,
    `Actual: ${tc.actual || "-"}`,
    tc.technical.length ? `Bukti teknis: ${tc.technical.join("; ")}` : null,
    tc.reviewer_note ? `Catatan reviewer: ${tc.reviewer_note}` : null,
  ];
  return lines.filter((l) => l !== null).join("\n");
}

type Filter = "all" | "findings" | "unreviewed";

export function RunResultPage() {
  const runId = Number(useParams().runId);
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.getRun(runId) });
  const cases = useQuery({ queryKey: ["cases", runId], queryFn: () => api.listCases(runId) });
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  const list = cases.data ?? [];
  const findings = list.filter(isFinding);
  const unreviewed = findings.filter((c) => !c.status_final);

  useEffect(() => {
    if (selected === null && list.length) setSelected((findings[0] ?? list[0]).id);
  }, [list, findings, selected]);

  const shown = useMemo(() => {
    const base = filter === "findings" ? findings : filter === "unreviewed" ? unreviewed : list;
    const q = query.trim().toLowerCase();
    return q ? base.filter((c) => c.id.toLowerCase().includes(q) || c.title.toLowerCase().includes(q)) : base;
  }, [filter, findings, unreviewed, list, query]);

  const counts = STATUSES.map((s) => [s, list.filter((c) => c.effective_status === s).length] as const);
  const total = list.length;
  const r = run.data;

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
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            {r ? (r.mode === "explore" ? "Hasil penjelajahan aplikasi" : `Hasil uji modul ${r.module}`) : <Skeleton className="h-8 w-80" />}
          </h1>
          {r && (
            <div className="mt-1.5 flex flex-wrap items-center gap-4 text-sm text-fg-muted">
              <span className="font-mono">{r.url.replace(/^https?:\/\//, "")}</span>
              <span>{r.environment === "production" ? "Production" : "Dev / UAT"}</span>
              <span>{formatDateTime(r.started_at)}</span>
              {r.finished_at && <span>Durasi {duration(r.started_at, r.finished_at)}</span>}
              <span className="font-mono">{r.model}</span>
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {r && (
            <Link to={`/runs/new?app=${r.app_id}`} className="inline-flex h-10 items-center gap-2 rounded-lg border border-ink-600 bg-ink-900 px-4 text-sm hover:bg-ink-850">
              <ArrowClockwise />
              Jalankan ulang
            </Link>
          )}
          {r?.mode === "deep" && total > 0 && (
            <Link
              to={`/runs/new?app=${r.app_id}&reuse=${r.id}${r.platform === "android" ? "&platform=android" : ""}`}
              title="Regresi: jalankan lagi test case yang sama tanpa AI menyusun ulang"
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-ink-600 bg-ink-900 px-4 text-sm hover:bg-ink-850"
            >
              <ArrowClockwise />
              Ulang dengan test case sama
            </Link>
          )}
          <a href={api.downloadUrl(runId, "xlsx")} download className="inline-flex h-10 items-center gap-2 rounded-lg border border-ink-600 bg-ink-900 px-4 text-sm hover:bg-ink-850">
            <FileXls className="text-pass" />
            Excel
          </a>
          <a href={api.downloadUrl(runId, "html")} download className="inline-flex h-10 items-center gap-2 rounded-lg border border-ink-600 bg-ink-900 px-4 text-sm hover:bg-ink-850">
            <FileHtml className="text-accent" />
            HTML
          </a>
          <a href={api.downloadUrl(runId, "pdf")} download className="inline-flex h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-white hover:bg-accent-hover">
            <FileText />
            Laporan PDF
          </a>
        </div>
      </header>

      {r?.note && r.status !== "completed" && <Alert tone="warning">{r.note}</Alert>}

      {r?.mode === "explore" ? (
        <AppMapView run={r} />
      ) : cases.isLoading ? (
        <Skeleton className="h-24" />
      ) : total === 0 ? (
        <Card>
          <EmptyState title="Belum ada test case" description="Test case belum disusun atau run berhenti sebelum menyusunnya." />
        </Card>
      ) : (
        <>
          <Card className="flex items-center gap-10 p-5">
            <div>
              <div className="text-sm text-fg-muted">Test case</div>
              <div className="mt-1 text-3xl font-semibold tracking-tight">{total}</div>
            </div>
            <div className="flex-1">
              <div className="flex h-2.5 overflow-hidden rounded-full bg-ink-800">
                {counts.map(([s, n]) =>
                  n ? (
                    <div
                      key={s}
                      className={cn(s === "Pass" ? "bg-pass" : s === "Fail" ? "bg-fail" : s === "Perlu Review" ? "bg-review" : "bg-ink-600")}
                      style={{ width: `${(n / total) * 100}%` }}
                    />
                  ) : null,
                )}
              </div>
              <div className="mt-3 flex flex-wrap gap-6 text-sm">
                {counts
                  .filter(([, n]) => n > 0)
                  .map(([s, n]) => (
                    <span key={s} className="flex items-center gap-2">
                      <span className={cn("h-2.5 w-2.5 rounded-sm", s === "Pass" ? "bg-pass" : s === "Fail" ? "bg-fail" : s === "Perlu Review" ? "bg-review" : "bg-ink-600")} />
                      {n} {s}
                    </span>
                  ))}
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm text-fg-muted">Sudah direview</div>
              <div className="mt-1 text-3xl font-semibold tracking-tight">
                {findings.length - unreviewed.length} <span className="text-xl text-fg-dim">/ {findings.length}</span>
              </div>
            </div>
          </Card>

          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_480px] gap-6">
            <Card className="self-start overflow-hidden">
              <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-3 text-sm">
                {(
                  [
                    ["all", "Semua", null],
                    ["findings", "Temuan", findings.length],
                    ["unreviewed", "Belum direview", unreviewed.length],
                  ] as const
                ).map(([id, label, n]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setFilter(id)}
                    aria-pressed={filter === id}
                    className={cn("h-8 rounded-md px-3", filter === id ? "bg-ink-800 font-medium" : "text-fg-muted hover:text-fg")}
                  >
                    {label}
                    {n !== null ? ` ${n}` : ""}
                  </button>
                ))}
                <div className="relative ml-auto w-52">
                  <MagnifyingGlass className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
                  <input
                    aria-label="Cari test case"
                    placeholder="Cari test case"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    className="h-8 w-full rounded-md border border-ink-700 bg-ink-900 pl-8 pr-2 text-sm focus:border-accent focus:outline-none"
                  />
                </div>
              </div>
              <table className="w-full text-sm">
                <thead className="border-b border-ink-700 bg-ink-850 text-left text-xs text-fg-muted">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">ID</th>
                    <th className="px-4 py-2.5 font-medium">Skenario</th>
                    <th className="px-4 py-2.5 font-medium">Tipe</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-700">
                  {shown.map((c) => (
                    <tr
                      key={c.id}
                      onClick={() => setSelected(c.id)}
                      aria-selected={selected === c.id}
                      className={cn("cursor-pointer hover:bg-ink-850", selected === c.id && "bg-accent-soft shadow-[inset_3px_0_0_var(--color-accent)]")}
                    >
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-fg-dim">{c.id}</td>
                      <td className={cn("px-4 py-3", selected === c.id && "font-medium")}>{c.title}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-fg-muted">{TYPE_LABEL[c.type] ?? c.type}</td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <StatusBadge status={c.effective_status} />
                        {c.status_final && <span className="ml-1.5 text-xs text-fg-dim">direview</span>}
                      </td>
                    </tr>
                  ))}
                  {shown.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-4 py-8 text-center text-sm text-fg-muted">
                        Tidak ada test case untuk filter ini.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              <div className="border-t border-ink-700 px-4 py-3 text-xs text-fg-muted">
                Menampilkan {shown.length} dari {total}
              </div>
            </Card>

            {selected ? <CaseDetailPanel key={selected} runId={runId} tcId={selected} run={r} /> : <Card className="p-5 text-sm text-fg-muted">Pilih test case untuk melihat detail.</Card>}
          </div>
        </>
      )}
    </main>
  );
}

function CaseDetailPanel({ runId, tcId, run }: { runId: number; tcId: string; run?: Run }) {
  const qc = useQueryClient();
  const detail = useQuery({ queryKey: ["case", runId, tcId], queryFn: () => api.caseDetail(runId, tcId) });
  const [statusFinal, setStatusFinal] = useState<string>("");
  const [severity, setSeverity] = useState<string>("");
  const [note, setNote] = useState("");
  const [warning, setWarning] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!detail.data) return;
    setStatusFinal(detail.data.status_final ?? "");
    setSeverity(detail.data.severity ?? "");
    setNote(detail.data.reviewer_note ?? "");
  }, [detail.data]);

  const save = useMutation({
    mutationFn: () =>
      api.patchCase(runId, tcId, {
        status_final: (statusFinal || null) as Status | null,
        severity: (severity || null) as Severity | null,
        reviewer_note: note,
      }),
    onSuccess: (res) => {
      setWarning(res.warning);
      setSaved(true);
      qc.invalidateQueries({ queryKey: ["cases", runId] });
      qc.invalidateQueries({ queryKey: ["case", runId, tcId] });
      qc.invalidateQueries({ queryKey: ["run", runId] });
    },
  });

  const copy = async () => {
    if (!detail.data) return;
    await navigator.clipboard.writeText(bugReportText({ ...detail.data, reviewer_note: note }, run));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const d = detail.data;
  const evidence = (d?.log ?? []).filter((s) => s.screenshot_url).slice(-3);

  return (
    <section aria-label="Detail test case" className="flex flex-col self-start rounded-xl border border-ink-700 bg-ink-900">
      {!d ? (
        <div className="flex flex-col gap-3 p-5">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-6 w-64" />
          <Skeleton className="h-24" />
        </div>
      ) : (
        <>
          <div className="border-b border-ink-700 p-5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs text-fg-dim">{d.id}</span>
              <StatusBadge status={d.effective_status} severity={d.severity} />
            </div>
            <h2 className="mt-1 font-semibold">{d.title}</h2>
            <dl className="mt-4 grid grid-cols-[100px_1fr] gap-y-2 text-sm">
              <dt className="text-fg-muted">Expected</dt>
              <dd>{d.expected}</dd>
              <dt className="text-fg-muted">Actual</dt>
              <dd>{d.actual || "-"}</dd>
              {d.ai_note && (
                <>
                  <dt className="text-fg-muted">Catatan AI</dt>
                  <dd className="text-fg-muted">{d.ai_note}</dd>
                </>
              )}
              {d.technical.length > 0 && (
                <>
                  <dt className="text-fg-muted">Bukti teknis</dt>
                  <dd className="flex flex-col gap-0.5 pt-0.5 font-mono text-xs text-fail">
                    {d.technical.map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </dd>
                </>
              )}
            </dl>
          </div>
          {evidence.length > 0 && (
            <div className="border-b border-ink-700 p-5">
              <div className="mb-3 text-sm font-medium">Evidence</div>
              <div className="grid grid-cols-3 gap-2.5">
                {evidence.map((s, i) => (
                  <figure key={s.step_no}>
                    <a href={s.screenshot_url!} target="_blank" rel="noreferrer" className={cn("block aspect-[4/3] overflow-hidden rounded-md border bg-white", i === evidence.length - 1 && d.effective_status === "Fail" ? "border-fail/50" : "border-ink-700")}>
                      <img src={s.screenshot_url!} alt={`Langkah ${s.step_no}`} className="h-full w-full object-cover object-top" loading="lazy" />
                    </a>
                    <figcaption className="mt-1 line-clamp-2 text-xs text-fg-muted">
                      {s.step_no}. {s.text}
                    </figcaption>
                  </figure>
                ))}
              </div>
            </div>
          )}
          <div className="flex flex-col gap-3 p-5">
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="rv-status" className="text-xs font-medium text-fg-muted">
                  Status final
                </label>
                <Select id="rv-status" value={statusFinal} onChange={(e) => setStatusFinal(e.target.value)}>
                  <option value="">Ikuti AI ({d.status_ai ?? "-"})</option>
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="rv-severity" className="text-xs font-medium text-fg-muted">
                  Severity
                </label>
                <Select id="rv-severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                  <option value="">-</option>
                  {SEVERITIES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="rv-note" className="text-xs font-medium text-fg-muted">
                Catatan reviewer
              </label>
              <Textarea id="rv-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            {warning && <Alert tone="warning">{warning}</Alert>}
            {saved && !warning && <Alert tone="success">Review disimpan dan laporan diperbarui.</Alert>}
            <div className="flex flex-col gap-2">
              <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>
                <FloppyDisk />
                Simpan review
              </Button>
              <Button onClick={copy}>
                <Copy />
                {copied ? "Disalin" : "Salin sebagai laporan bug (Jira)"}
              </Button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
