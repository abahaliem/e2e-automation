import { ArrowRight, FileHtml, FileText, FileXls, FloppyDisk, Trash, UploadSimple } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Alert, Button, Card, Field, Input, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { ReportSettings } from "@/lib/types";

export function ReportTab() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["report-settings"], queryFn: api.reportSettings });
  const [company, setCompany] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (settings.data) setCompany(settings.data.company_name);
  }, [settings.data]);
  const setData = (d: ReportSettings) => qc.setQueryData(["report-settings"], d);

  const save = useMutation({
    mutationFn: () => api.patchReportSettings({ company_name: company }),
    onSuccess: (d) => {
      setData(d);
      setSaved(true);
    },
  });
  const upload = useMutation({ mutationFn: (file: File) => api.uploadTemplate(file), onSuccess: setData });
  const remove = useMutation({
    mutationFn: api.deleteTemplate,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["report-settings"] }),
  });

  if (settings.isLoading || !settings.data) return <Skeleton className="h-80" />;
  const tpl = settings.data.excel_template;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-10">
      <div className="flex min-w-0 flex-col gap-6">
        <Card className="flex flex-col gap-4 p-6">
          <div>
            <h2 className="font-semibold">Identitas dokumen</h2>
            <p className="mt-1 text-sm text-fg-muted">Tampil di kepala laporan PDF di samping logo QA Agent.</p>
          </div>
          <Field label="Nama perusahaan / instansi" htmlFor="rp-company">
            <Input id="rp-company" value={company} placeholder="PT Biznet Gio Nusantara" onChange={(e) => setCompany(e.target.value)} />
          </Field>
          {saved && <Alert tone="success">Disimpan. Berlaku untuk laporan yang dibuat berikutnya.</Alert>}
          <div>
            <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>
              <FloppyDisk />
              Simpan
            </Button>
          </div>
        </Card>

        <Card className="flex flex-col gap-4 p-6">
          <div>
            <h2 className="font-semibold">Template Excel kantor</h2>
            <p className="mt-1 text-sm text-fg-muted">
              {tpl
                ? "Sheet Test Cases mengikuti urutan dan gaya kolom template ini."
                : "Belum ada template. Excel memakai format standar QA Agent (12 kolom, header biru)."}
            </p>
          </div>
          {tpl ? (
            <>
              <div className="flex items-center gap-3 rounded-lg border border-accent-line bg-accent-soft px-4 py-3">
                <FileXls className="text-2xl text-pass" />
                <span className="flex-1 truncate text-sm font-medium">{tpl.name}</span>
                <label htmlFor="rp-template" className="cursor-pointer text-sm text-accent">
                  Ganti file
                </label>
                <Button size="sm" variant="ghost" className="text-fail! hover:bg-fail/5" onClick={() => remove.mutate()}>
                  <Trash />
                  Hapus
                </Button>
              </div>
              <table className="w-full text-sm">
                <thead className="border-b border-ink-700 text-left text-xs text-fg-muted">
                  <tr>
                    <th className="py-2 font-medium">Kolom di template</th>
                    <th />
                    <th className="py-2 font-medium">Diisi dari</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-700">
                  {tpl.columns.map((c) => (
                    <tr key={c.header}>
                      <td className="py-2">{c.header}</td>
                      <td className="text-fg-dim">
                        <ArrowRight />
                      </td>
                      <td className="py-2">{c.maps_to ? <span className="font-medium">{c.maps_to}</span> : <span className="text-fg-dim">Tidak dikenali, dibiarkan kosong</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <label htmlFor="rp-template" className="grid h-24 cursor-pointer place-items-center rounded-xl border border-dashed border-ink-600 text-sm text-fg-muted hover:bg-ink-850">
              <span className="flex items-center gap-2">
                <UploadSimple className="text-lg" />
                {upload.isPending ? "Membaca template..." : "Pilih file .xlsx berisi baris judul kolom kantor"}
              </span>
            </label>
          )}
          <input
            id="rp-template"
            aria-label="File template Excel"
            type="file"
            accept=".xlsx"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload.mutate(file);
              e.target.value = "";
            }}
          />
          {upload.error && <Alert tone="error">{(upload.error as Error).message}</Alert>}
        </Card>
      </div>

      <aside className="flex flex-col gap-5">
        <Card className="p-5">
          <h2 className="text-sm font-semibold">Dokumen yang dihasilkan</h2>
          <ul className="mt-4 flex flex-col gap-4 text-sm">
            <li className="flex gap-3">
              <FileXls className="shrink-0 text-lg text-pass" />
              <div>
                <div className="font-medium">Excel</div>
                <div className="text-fg-muted">Ringkasan, Test Cases, Temuan, Inventaris Fitur. Status Final dan Catatan Reviewer bisa diisi langsung.</div>
              </div>
            </li>
            <li className="flex gap-3">
              <FileText className="shrink-0 text-lg text-accent" />
              <div>
                <div className="font-medium">PDF</div>
                <div className="text-fg-muted">Laporan hasil pengujian: ringkasan, temuan dengan evidence, daftar test case.</div>
              </div>
            </li>
            <li className="flex gap-3">
              <FileHtml className="shrink-0 text-lg text-accent" />
              <div>
                <div className="font-medium">HTML</div>
                <div className="text-fg-muted">Laporan interaktif lengkap dengan semua langkah dan screenshot.</div>
              </div>
            </li>
          </ul>
        </Card>
      </aside>
    </div>
  );
}
