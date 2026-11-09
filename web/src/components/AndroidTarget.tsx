import {
  ArrowsClockwise,
  Circle,
  DesktopTower,
  DeviceMobile,
  DeviceMobileCamera,
  FileArrowUp,
  MagnifyingGlass,
  RadioButton,
  Screencast,
  UploadSimple,
} from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Alert } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { ApkChoice, Device } from "@/lib/types";
import { UsbDebuggingSteps, useDevices } from "@/pages/Devices";

const BADGE: Record<string, { text: string; tone: string }> = {
  device: { text: "Siap", tone: "text-pass" },
  unauthorized: { text: "Butuh izin", tone: "text-review" },
  offline: { text: "Offline", tone: "text-fail" },
};

function formatMb(bytes: number): string {
  return `${(bytes / 1024 / 1024).toLocaleString("id-ID", { maximumFractionDigits: 1 })} MB`;
}

function deviceTitle(d: Device) {
  return d.model || d.serial;
}

function DeviceCard({ device, selected, onSelect }: { device: Device; selected: boolean; onSelect: () => void }) {
  const ready = device.state === "device";
  const badge = BADGE[device.state] ?? { text: device.state, tone: "text-fg-muted" };
  const Icon = device.emulator ? DesktopTower : ready ? DeviceMobileCamera : DeviceMobile;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={!ready}
      onClick={onSelect}
      className={cn(
        "flex flex-col rounded-xl border p-4 text-left transition-colors",
        selected ? "border-accent-line bg-accent-soft" : "border-ink-700 bg-ink-900 hover:bg-ink-850",
        !ready && "cursor-not-allowed hover:bg-ink-900",
      )}
    >
      <div className="flex items-start justify-between">
        <Icon className={cn("text-2xl", selected ? "text-accent" : "text-fg-muted")} />
        <span className={cn("rounded-md border border-ink-700 px-2 py-0.5 text-xs", selected ? "bg-ink-900" : "bg-ink-850", badge.tone)}>
          {badge.text}
        </span>
      </div>
      <div className="mt-3 truncate font-medium">{deviceTitle(device)}</div>
      <div className="text-sm text-fg-muted">
        {ready
          ? `Android ${device.android_version ?? "-"}${device.emulator ? " · Emulator" : ""}`
          : device.state === "unauthorized"
            ? 'Ketuk "Izinkan USB debugging" di HP'
            : "Cabut lalu sambungkan ulang kabel"}
      </div>
      <div className="mt-2 truncate font-mono text-xs text-fg-dim">{device.serial}</div>
    </button>
  );
}

/** Pilihan target Android di Run baru (mockup 02/02b): kartu perangkat + aplikasi terpasang atau upload APK. */
export function AndroidTarget({
  serial,
  onSerial,
  pkg,
  onPackage,
  error,
  onApk,
}: {
  serial: string;
  onSerial: (serial: string) => void;
  pkg: string;
  onPackage: (pkg: string) => void;
  error?: string;
  /** APK hasil unggah yang dipasang saat run dimulai (mockup 02b), atau null bila memakai aplikasi terpasang. */
  onApk?: (choice: ApkChoice | null) => void;
}) {
  const devices = useDevices();
  const list = devices.data?.devices ?? [];
  const ready = useMemo(() => list.filter((d) => d.state === "device"), [list]);
  const [source, setSource] = useState<"installed" | "apk">("installed");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if ((!serial || !ready.some((d) => d.serial === serial)) && ready.length) onSerial(ready[0].serial);
  }, [ready, serial, onSerial]);

  const packages = useQuery({
    queryKey: ["device-packages", serial],
    queryFn: () => api.devicePackages(serial),
    enabled: !!serial,
  });
  const [uploadedName, setUploadedName] = useState<string | null>(null);
  const [grant, setGrant] = useState(true);
  const [uninstall, setUninstall] = useState(false);
  const upload = useMutation({
    mutationFn: (file: File) => api.uploadApk(serial, file),
    onSuccess: (r) => onPackage(r.package),
  });
  const deviceName = (() => {
    const d = list.find((x) => x.serial === serial);
    return d ? deviceTitle(d) : "HP";
  })();

  useEffect(() => {
    onApk?.(source === "apk" && upload.data ? { file: upload.data.file, grant, uninstall } : null);
  }, [source, upload.data, grant, uninstall, onApk]);

  const missing = devices.error instanceof ApiError && devices.error.status === 503;
  const apps = packages.data?.apps ?? (packages.data?.packages ?? []).map((p) => ({ package: p, version: null }));
  const shown = apps.filter((a) => a.package.toLowerCase().includes(filter.trim().toLowerCase()));

  return (
    <div className="flex flex-col gap-7">
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium" id="device-label">
            Perangkat tersambung
          </span>
          <button type="button" onClick={() => devices.refetch()} className="flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg">
            <ArrowsClockwise className={cn(devices.isFetching && "animate-spin")} />
            Pindai ulang
          </button>
        </div>
        {devices.isLoading ? (
          <div className="grid grid-cols-3 gap-4">
            <div className="skeleton h-32" />
            <div className="skeleton h-32" />
          </div>
        ) : devices.error ? (
          <Alert tone={missing ? "warning" : "error"}>
            <div className="font-medium">{missing ? "adb belum terpasang" : "Perangkat tidak bisa dibaca"}</div>
            <div className="mt-1">{(devices.error as Error).message}</div>
          </Alert>
        ) : list.length === 0 ? (
          <div className="flex flex-col gap-3 rounded-xl border border-ink-700 bg-ink-900 p-5">
            <div className="font-medium">Belum ada HP yang tersambung</div>
            <UsbDebuggingSteps />
          </div>
        ) : (
          <div role="radiogroup" aria-labelledby="device-label" className="grid grid-cols-3 gap-4">
            {list.map((d) => (
              <DeviceCard key={d.serial} device={d} selected={d.serial === serial} onSelect={() => onSerial(d.serial)} />
            ))}
            {!list.some((d) => d.emulator) && (
              <div className="flex flex-col rounded-xl border border-dashed border-ink-600 bg-ink-900 p-4">
                <div className="flex items-start justify-between">
                  <DesktopTower className="text-2xl text-fg-dim" />
                  <span className="rounded-md border border-ink-700 bg-ink-850 px-2 py-0.5 text-xs text-fg-muted">Opsional</span>
                </div>
                <div className="mt-3 font-medium">Emulator Android</div>
                <div className="text-sm text-fg-muted">Emulator yang sedang berjalan otomatis muncul di sini. Disarankan RAM 16 GB.</div>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Aplikasi yang diuji</span>
          <div role="radiogroup" aria-label="Sumber aplikasi" className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-1 text-sm">
            {(
              [
                ["installed", "Terpasang di HP", null],
                ["apk", "Upload APK", UploadSimple],
              ] as const
            ).map(([value, label, Icon]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={source === value}
                onClick={() => setSource(value)}
                className={cn("flex items-center gap-1.5 rounded-md px-3 py-1", source === value ? "bg-ink-800 font-medium" : "text-fg-muted hover:text-fg")}
              >
                {Icon && <Icon />}
                {label}
              </button>
            ))}
          </div>
        </div>

        {source === "installed" ? (
          <>
            <div className="relative">
              <MagnifyingGlass className="absolute left-4 top-1/2 -translate-y-1/2 text-fg-muted" />
              <input
                aria-label="Cari aplikasi"
                value={filter}
                placeholder="Cari nama aplikasi atau package"
                onChange={(e) => setFilter(e.target.value)}
                className="h-11 w-full rounded-lg border border-ink-700 bg-ink-900 pl-10 pr-4 text-sm placeholder:text-fg-muted focus:border-accent focus:outline-none"
              />
            </div>
            <div
              role="radiogroup"
              aria-label="Aplikasi di HP"
              aria-invalid={!!error}
              className={cn("max-h-80 divide-y divide-ink-700 overflow-y-auto rounded-xl border bg-ink-900", error ? "border-fail" : "border-ink-700")}
            >
              {!serial ? (
                <div className="px-4 py-6 text-center text-sm text-fg-muted">Pilih perangkat yang siap dipakai dulu.</div>
              ) : packages.isLoading ? (
                <div className="flex flex-col gap-2 p-4">
                  <div className="skeleton h-9" />
                  <div className="skeleton h-9" />
                </div>
              ) : shown.length === 0 ? (
                <div className="px-4 py-6 text-center text-sm text-fg-muted">
                  {apps.length ? "Tidak ada aplikasi yang cocok." : "Belum ada aplikasi pihak ketiga di HP ini. Coba Upload APK."}
                </div>
              ) : (
                shown.map((a) => {
                  const checked = a.package === pkg;
                  return (
                    <button
                      key={a.package}
                      type="button"
                      role="radio"
                      aria-checked={checked}
                      onClick={() => onPackage(a.package)}
                      className={cn("flex w-full items-center gap-4 px-4 py-3 text-left", checked ? "bg-accent-soft" : "hover:bg-ink-850")}
                    >
                      {checked ? <RadioButton weight="fill" className="text-lg text-accent" /> : <Circle className="text-lg text-fg-dim" />}
                      <span className="min-w-0 flex-1 truncate font-mono text-sm">{a.package}</span>
                      {a.version && <span className="shrink-0 text-xs text-fg-muted">versi {a.version}</span>}
                    </button>
                  );
                })
              )}
            </div>
            {error && <p className="text-xs text-fail">{error}</p>}
          </>
        ) : (
          <div className="flex flex-col gap-3">
            {upload.data && uploadedName ? (
              <div className="flex items-center gap-4 rounded-xl border border-accent-line bg-accent-soft px-4 py-3">
                <FileArrowUp className="shrink-0 text-2xl text-accent" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{uploadedName}</div>
                  <div className="truncate text-xs text-fg-muted">
                    <span className="font-mono">{upload.data.package}</span>
                    {`, versi ${upload.data.version ?? "-"}, ${formatMb(upload.data.size_bytes)}`}
                  </div>
                </div>
                <span className="shrink-0 rounded-md border border-ink-700 bg-ink-900 px-2 py-0.5 text-xs text-pass">Siap di-install</span>
                <label htmlFor="apk-file" className="shrink-0 cursor-pointer text-sm text-accent">
                  Ganti file
                </label>
              </div>
            ) : (
              <label
                htmlFor="apk-file"
                className="flex h-32 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-ink-600 bg-ink-900 text-sm text-fg-muted hover:bg-ink-850"
              >
                <FileArrowUp className="text-2xl" />
                <span className="font-medium text-fg">{upload.isPending ? "Membaca file APK..." : "Pilih atau tarik file .apk ke sini"}</span>
                <span className="text-xs">Maks 300 MB. Dipasang ke HP saat run dimulai.</span>
              </label>
            )}
            <input
              id="apk-file"
              aria-label="File APK"
              type="file"
              accept=".apk"
              className="sr-only"
              disabled={!serial || upload.isPending}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  setUploadedName(file.name);
                  upload.mutate(file);
                }
                e.target.value = "";
              }}
            />
            {upload.data && (
              <p className="text-sm text-fg-muted">
                {upload.data.installed_version
                  ? `${deviceName} sudah punya ${upload.data.package} versi ${upload.data.installed_version}. Versi ${upload.data.version ?? "baru"} akan di-install di atasnya, data login tetap ada.`
                  : `${upload.data.package} belum ada di ${deviceName}. Aplikasi di-install saat run dimulai.`}
              </p>
            )}
            {upload.data && (
              <div className="flex flex-col gap-2 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={grant}
                    onChange={(e) => setGrant(e.target.checked)}
                    className="h-4 w-4 accent-[var(--color-accent)]"
                  />
                  Beri semua izin aplikasi otomatis
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={uninstall}
                    onChange={(e) => setUninstall(e.target.checked)}
                    className="h-4 w-4 accent-[var(--color-accent)]"
                  />
                  Hapus aplikasi setelah run selesai
                </label>
              </div>
            )}
            {upload.error && <Alert tone="error">{(upload.error as Error).message}</Alert>}
            {error && !upload.data && <p className="text-xs text-fail">{error}</p>}
          </div>
        )}
      </section>
    </div>
  );
}

/** Panel kanan "Layar HP": pratinjau layar perangkat terpilih (screenshot berkala). */
export function PhonePreview({ serial }: { serial: string }) {
  const devices = useDevices();
  const device = devices.data?.devices.find((d) => d.serial === serial);
  const [tick, setTick] = useState(() => Date.now());
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
    if (!serial) return;
    const t = setInterval(() => setTick(Date.now()), 2500);
    return () => clearInterval(t);
  }, [serial]);

  const name = device ? deviceTitle(device) : "HP";
  return (
    <aside className="flex flex-col gap-3">
      <h2 className="text-sm font-medium text-fg-muted">Layar HP</h2>
      <div className="mx-auto aspect-[9/19] w-full max-w-[300px] rounded-[28px] border border-ink-600 bg-ink-900 p-2">
        {serial && device?.state === "device" && !failed ? (
          <img
            src={api.deviceScreenUrl(serial, tick)}
            alt={`Layar ${name}`}
            onError={() => setFailed(true)}
            className="h-full w-full rounded-[22px] border border-ink-700 bg-ink-850 object-contain"
          />
        ) : (
          <div className="grid h-full place-items-center rounded-[22px] border border-ink-700 bg-ink-850 px-6 text-center">
            <div>
              <Screencast className="mx-auto text-3xl text-fg-dim" />
              <p className="mt-3 text-sm text-fg-muted">
                {serial ? `Layar ${name} belum bisa ditampilkan. Pastikan layar HP tidak terkunci.` : "Pilih perangkat untuk melihat layarnya di sini."}
              </p>
            </div>
          </div>
        )}
      </div>
      <p className="text-center text-xs text-fg-dim">
        {serial && device?.state === "device" ? `Pratinjau langsung ${name}, diperbarui tiap beberapa detik` : "Layar live tampil penuh saat run dimulai"}
      </p>
    </aside>
  );
}
