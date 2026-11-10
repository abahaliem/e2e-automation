import { ArrowRight, CheckCircle, Circle, Info } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Card, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

type Step = {
  title: string;
  done?: boolean;
  optional?: string;
  link?: { to: string; label: string };
  body: ReactNode;
};

const STATUS_HELP: [string, string, string][] = [
  ["Pass", "text-pass", "Hasil di layar sesuai expected result."],
  ["Fail", "text-fail", "Tidak sesuai expected result dari PRD, atau ada error server/aplikasi. Ini temuan bug."],
  ["Perlu Review", "text-review", "Tidak sesuai expected hasil tebakan AI (tanpa PRD), atau ada pesan error saat login otomatis. Cek dan putuskan sendiri."],
  ["Blocked", "text-fg-muted", "Tidak bisa dijalankan sampai selesai (layar tidak bisa dicapai, langkah buntu). Baca alasannya, beri arahan, lalu ulangi."],
  ["Skipped", "text-fg-muted", "Dilewati, misalnya aksi diblok mode Production."],
];

/** Panduan langkah demi langkah memakai QA Agent; tanda centang mengikuti data yang sudah ada. */
export function GuidePage() {
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: api.listProfiles });
  const apps = useQuery({ queryKey: ["apps"], queryFn: api.listApps });
  const runs = useQuery({ queryKey: ["runs", "guide"], queryFn: () => api.listRuns({ limit: 200 }) });

  const hasProfile = !!profiles.data?.length;
  const hasApp = !!apps.data?.length;
  const explored = !!apps.data?.some((a) => a.explored);
  const deepRuns = (runs.data ?? []).filter((r) => r.mode === "deep");
  const reviewed = deepRuns.some((r) => r.status === "completed");

  const steps: Step[] = [
    {
      title: "Atur Model AI",
      done: hasProfile,
      link: { to: "/settings", label: "Buka Pengaturan, Model AI" },
      body: (
        <>
          Isi nama profil, Base URL endpoint AI kantor (mis. <Code>http://…/v1</Code>), API key, dan model, lalu klik{" "}
          <b>Tes koneksi</b>. API key disimpan aman dan tidak pernah masuk ke laporan.
        </>
      ),
    },
    {
      title: "Tambah aplikasi dan akun test",
      done: hasApp,
      link: { to: "/apps", label: "Buka Aplikasi" },
      body: (
        <>
          Web: isi URL aplikasi. Android: pilih paket aplikasi di HP. Lalu tambahkan <b>akun test</b> (username dan password) bila
          aplikasi butuh login. Agent memakai akun ini untuk login; password tidak pernah dikirim ke AI. Di halaman yang sama
          (opsional):
          <ul className="mt-1.5 list-disc space-y-1 pl-5">
            <li>
              <b>Data uji</b>: data yang harus sudah ada di aplikasi, mis. nomor work order. Tulis <Code>{"{{data:wo_id}}"}</Code> di
              langkah test case; tiap test case memakai nilai yang belum terpakai.
            </li>
            <li>
              <b>Persiapan otomatis (HTTP)</b>: panggil endpoint internal sebelum run/test case, mis. membuat WO uji baru, dan simpan
              ID-nya ke Data uji.
            </li>
            <li>
              Aplikasi yang tidak dipakai lagi bisa <b>dihapus</b> beserta riwayat run-nya (ada konfirmasi).
            </li>
          </ul>
        </>
      ),
    },
    {
      title: "Sambungkan HP (khusus Android)",
      optional: "Lewati bila menguji aplikasi web",
      link: { to: "/devices", label: "Buka Perangkat" },
      body: (
        <>
          Aktifkan <b>Opsi pengembang</b> dan <b>Debugging USB</b> di HP, colokkan kabel, lalu ketuk <b>Izinkan</b> di HP. Tanpa kabel:
          pakai <b>Sambungkan lewat jaringan</b> (Wireless debugging).
        </>
      ),
    },
    {
      title: "Petakan aplikasi (Seluruh aplikasi)",
      done: explored,
      link: { to: "/runs/new", label: "Buka Run baru" },
      body: (
        <>
          Di <b>Run baru</b> pilih aplikasi, lalu pada <b>Yang diuji</b> pilih <b>Seluruh aplikasi</b> dan klik <b>Mulai run</b>. Agent
          login, membuka semua menu dan halaman, lalu mengelompokkannya menjadi <b>modul</b>. Langkah ini tidak mengisi atau
          mengirim form. Wajib dilakukan sekali untuk setiap aplikasi baru (URL/domain berbeda dianggap aplikasi baru), dan ulangi
          bila aplikasi berubah banyak.
        </>
      ),
    },
    {
      title: "Uji satu modul",
      done: deepRuns.length > 0,
      link: { to: "/runs/new", label: "Buka Run baru" },
      body: (
        <>
          Setelah dipetakan, pilih <b>Satu modul</b> dan modulnya (mis. Autentikasi). Unggah <b>PRD</b> (.md/.txt) bila ada supaya
          expected result mengikuti PRD. Aktifkan <b>Review test case dulu</b> supaya kamu bisa menghapus, mengedit, atau
          menambah test case sebelum dijalankan. Untuk proses yang melintasi beberapa menu (mis. buka work order sampai closed),
          buat <b>Alur bisnis</b> di halaman <b>Aplikasi</b>; alur itu muncul sebagai pilihan modul.
        </>
      ),
    },
    {
      title: "Pantau dan arahkan agent",
      link: { to: "/runs", label: "Buka Riwayat run" },
      body: (
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <b>Jeda</b> / <b>Lanjutkan</b>: hentikan sementara di antara langkah.
          </li>
          <li>
            <b>Arahkan agent</b>: tulis petunjuk, mis. "tombol logout ada di menu samping", lalu <b>Kirim</b>. Dipakai pada
            langkah berikutnya.
          </li>
          <li>
            <b>Ambil alih</b>: klik dan ketik langsung di layar live, lalu <b>Kembalikan ke AI</b>, atau akhiri test case dengan <b>Akhiri: Pass</b> / <b>Akhiri: Fail</b>.
          </li>
          <li>
            <b>Lewati</b> test case yang tidak relevan, atau <b>Hentikan</b> run.
          </li>
        </ul>
      ),
    },
    {
      title: "Review hasil dan unduh dokumen",
      done: reviewed,
      link: { to: "/runs", label: "Buka Riwayat run" },
      body: (
        <>
          Di halaman <b>Hasil</b>, cek setiap temuan: atur <b>Status final</b>, <b>Severity</b>, dan <b>Catatan reviewer</b>. Unduh
          dokumen <b>Excel</b> (test case) dan <b>Laporan PDF</b> (evidence). Temuan bisa disalin sebagai laporan bug (Jira).
          Supaya dokumen sesuai format kantor, atur sekali di <b>Pengaturan → Laporan</b>:
          <ul className="mt-1.5 list-disc space-y-1 pl-5">
            <li>
              <b>Logo dan nama perusahaan</b> tampil di kepala Laporan PDF.
            </li>
            <li>
              <b>Template Excel kantor</b> (mis. form UAT): judul kolom boleh di baris mana pun, isian kepala dokumen (Project, UAT
              Date, QA/Tester, dll.) diisi, status ditulis dengan kosakata template (Passed/Failed, ✓/!/X), dan tabel diperpanjang
              otomatis dengan rekap ikut bergeser. Review yang diisi di Excel tetap terbaca kembali.
            </li>
          </ul>
        </>
      ),
    },
    {
      title: "Regresi: ulangi dengan test case yang sama",
      body: (
        <>
          Setelah developer memperbaiki bug, buka hasil run lalu klik <b>Ulang dengan test case sama</b>. Test case tidak disusun
          ulang oleh AI, jadi hasilnya bisa dibandingkan. Test case yang <b>Pass</b> direkam sebagai skrip, dan saat regresi
          <b> diputar ulang tanpa AI</b> (pilihan <b>Putar ulang skrip rekaman tanpa AI</b>): lebih cepat, hemat, dan konsisten. Bila
          tombol berubah atau layar akhir berbeda, AI memperbaiki skripnya otomatis (<b>Perbaiki dengan AI bila skrip gagal</b>).
          Langkah dari skrip ditandai <b>Skrip</b> di layar live. Run lama yang tidak dipakai bisa dihapus di <b>Riwayat run</b>.
        </>
      ),
    },
  ];
  const loading = profiles.isLoading || apps.isLoading || runs.isLoading;
  const next = loading ? -1 : steps.findIndex((s) => s.done === false);

  return (
    <main className="flex max-w-5xl flex-col gap-8 px-10 py-8">
      <PageHeader
        title="Panduan"
        description="Cara memakai QA Agent dari awal sampai dokumen test case siap. Tanda centang muncul otomatis saat langkah sudah kamu lakukan."
      />
      <ol className="flex flex-col gap-3">
        {steps.map((s, i) => (
          <li key={s.title}>
            <Card className={cn("flex gap-4 p-5", i === next && "border-accent-line ring-4 ring-accent-soft")}>
              <div className="flex flex-col items-center gap-1">
                <span className="grid h-8 w-8 place-items-center rounded-full bg-ink-850 text-sm font-semibold">{i + 1}</span>
                {s.done ? (
                  <CheckCircle weight="fill" aria-label="Sudah" className="text-lg text-pass" />
                ) : s.done === false ? (
                  <Circle aria-label="Belum" className="text-lg text-fg-dim" />
                ) : null}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-semibold">{s.title}</h2>
                  {i === next && <span className="rounded bg-accent-soft px-1.5 py-0.5 text-xs text-accent">Langkah berikutnya</span>}
                  {s.optional && <span className="rounded bg-ink-800 px-1.5 py-0.5 text-xs text-fg-muted">{s.optional}</span>}
                </div>
                <div className="mt-1.5 text-sm leading-relaxed text-fg-muted">{s.body}</div>
                {s.link && (
                  <Link to={s.link.to} className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-accent">
                    {s.link.label}
                    <ArrowRight />
                  </Link>
                )}
              </div>
            </Card>
          </li>
        ))}
      </ol>

      <section className="flex flex-col gap-3">
        <h2 className="font-semibold">Arti status test case</h2>
        <Card className="divide-y divide-ink-700">
          {STATUS_HELP.map(([label, tone, text]) => (
            <div key={label} className="flex gap-4 px-5 py-3 text-sm">
              <span className={cn("w-28 shrink-0 font-medium", tone)}>{label}</span>
              <span className="text-fg-muted">{text}</span>
            </div>
          ))}
        </Card>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="font-semibold">Pertanyaan umum</h2>
        <Card className="divide-y divide-ink-700 text-sm">
          <Faq q="Pilihan Satu modul tidak bisa dipilih">
            Aplikasi itu belum dipetakan. Jalankan <b>Seluruh aplikasi</b> dulu (langkah 4). URL dengan domain berbeda, mis.
            dev-cmc dan cmc-tools, dianggap aplikasi yang berbeda.
          </Faq>
          <Faq q="Modul yang muncul sedikit, menu lain tidak terpetakan">
            Saat agent bertanya di akhir penjelajahan, pilih <b>Lanjutkan memetakan</b> supaya tombol yang belum dicoba ikut
            dibuka. Bila ada menu tersembunyi, klik <b>Ambil alih</b>, buka menunya di layar live, lalu <b>Lanjutkan memetakan</b>.
          </Faq>
          <Faq q="Test case Blocked: Data uji habis">
            Semua nilai pada kumpulan data itu sudah terpakai. Tambahkan nilai baru di <b>Aplikasi → Data uji</b>, atau klik ikon
            <b> pakai lagi</b> pada nilai yang datanya sudah dikembalikan ke kondisi awal. Bisa juga dibuat otomatis lewat
            <b> Persiapan otomatis</b>.
          </Faq>
          <Faq q="Excel kantor: sheet atau status tidak sesuai">
            Di <b>Pengaturan → Laporan</b>, pilih sheet yang benar pada <b>Sheet yang dipakai</b> (sheet contoh yang sudah berisi
            data tidak dipilih otomatis), cek pemetaan status, lalu isi kepala dokumen dan klik <b>Simpan isian</b>.
          </Faq>
          <Faq q="Fitur baru tidak muncul / muncul 'Endpoint tidak ditemukan'">
            Server masih menjalankan versi lama. Hentikan server (Ctrl+C) lalu jalankan lagi <Code>qa-agent serve</Code>, kemudian
            tekan <b>Ctrl+F5</b> di browser.
          </Faq>
          <Faq q="Login otomatis gagal">
            Periksa akun test di halaman <b>Aplikasi</b> dan pastikan run memakai akun yang benar di <b>Run baru</b>, pilihan Akun test.
          </Faq>
          <Faq q="Test case Blocked karena layar tidak bisa dicapai">
            Layar itu mungkin hanya muncul pada kondisi tertentu. Beri <b>Arahkan agent</b> cara menuju layar itu, atau hapus test
            case tersebut saat review.
          </Faq>
        </Card>
      </section>
    </main>
  );
}

function Code({ children }: { children: ReactNode }) {
  return <span className="font-mono text-xs text-fg">{children}</span>;
}

function Faq({ q, children }: { q: string; children: ReactNode }) {
  return (
    <details className="group px-5 py-3">
      <summary className="flex cursor-pointer list-none items-center gap-2 font-medium">
        <Info className="text-accent" />
        {q}
      </summary>
      <p className="mt-2 pl-6 text-fg-muted">{children}</p>
    </details>
  );
}
