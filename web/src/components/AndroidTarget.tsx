import { CheckCircle, FileArrowUp, Package } from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Alert, Field, Input, Select } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { UsbDebuggingSteps, useDevices } from "@/pages/Devices";

/** Pilihan target Android di Run baru: perangkat + aplikasi terpasang atau upload APK. */
export function AndroidTarget({
  serial,
  onSerial,
  pkg,
  onPackage,
  error,
}: {
  serial: string;
  onSerial: (serial: string) => void;
  pkg: string;
  onPackage: (pkg: string) => void;
  error?: string;
}) {
  const devices = useDevices();
  const ready = useMemo(() => (devices.data?.devices ?? []).filter((d) => d.state === "device"), [devices.data]);
  const [source, setSource] = useState<"installed" | "apk">("installed");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!serial && ready.length) onSerial(ready[0].serial);
  }, [ready, serial, onSerial]);

  const packages = useQuery({
    queryKey: ["device-packages", serial],
    queryFn: () => api.devicePackages(serial),
    enabled: !!serial,
  });
  const install = useMutation({
    mutationFn: (file: File) => api.installApk(serial, file),
    onSuccess: (r) => {
      if (r.package) onPackage(r.package);
      packages.refetch();
    },
  });

  const missing = devices.error instanceof ApiError && devices.error.status === 503;
  const shown = (packages.data?.packages ?? []).filter((p) => p.toLowerCase().includes(filter.trim().toLowerCase()));

  if (devices.isLoading) return <div className="skeleton h-24" />;
  if (devices.error)
    return (
      <Alert tone={missing ? "warning" : "error"}>
        <div className="font-medium">{missing ? "adb belum terpasang" : "Perangkat tidak bisa dibaca"}</div>
        <div className="mt-1">{(devices.error as Error).message}</div>
      </Alert>
    );
  if (!devices.data?.devices.length)
    return (
      <div className="flex flex-col gap-3 rounded-xl border border-ink-700 bg-ink-900 p-5">
        <div className="font-medium">Belum ada HP yang tersambung</div>
        <UsbDebuggingSteps />
      </div>
    );

  return (
    <div className="flex flex-col gap-5">
      <Field
        label="Perangkat"
        htmlFor="run-device"
        hint={ready.length ? undefined : "HP terdeteksi tetapi belum siap. Ketuk Izinkan pada dialog USB debugging di HP."}
      >
        <Select id="run-device" value={serial} onChange={(e) => onSerial(e.target.value)}>
          {!ready.length && <option value="">Belum ada perangkat siap</option>}
          {devices.data.devices.map((d) => (
            <option key={d.serial} value={d.serial} disabled={d.state !== "device"}>
              {d.model || d.serial}
              {d.android_version ? ` · Android ${d.android_version}` : ""}
              {d.emulator ? " · Emulator" : ""}
              {d.state === "unauthorized" ? ` (${d.serial}, belum diizinkan)` : d.state !== "device" ? ` (${d.serial}, ${d.state})` : ""}
            </option>
          ))}
        </Select>
      </Field>

      <div className="flex flex-col gap-2">
        <span id="apk-source" className="text-sm font-medium">
          Aplikasi
        </span>
        <div role="radiogroup" aria-labelledby="apk-source" className="grid grid-cols-2 gap-3">
          {(
            [
              ["installed", "Aplikasi terpasang", "Pilih aplikasi yang sudah ada di HP", Package],
              ["apk", "Upload APK", "Pasang otomatis ke HP, lalu diuji", FileArrowUp],
            ] as const
          ).map(([value, title, text, Icon]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={source === value}
              onClick={() => setSource(value)}
              className={cn(
                "flex flex-col rounded-xl border p-4 text-left",
                source === value ? "border-accent-line bg-accent-soft" : "border-ink-700 bg-ink-900 hover:bg-ink-850",
              )}
            >
              <span className="flex items-center gap-2 font-medium">
                <Icon className={source === value ? "text-accent" : "text-fg-muted"} />
                {title}
              </span>
              <span className="mt-1 text-sm text-fg-muted">{text}</span>
            </button>
          ))}
        </div>
      </div>

      {source === "installed" ? (
        <div className="grid grid-cols-[1fr_1.4fr] gap-3">
          <Field label="Cari paket" htmlFor="pkg-filter">
            <Input id="pkg-filter" value={filter} placeholder="com.perusahaan" onChange={(e) => setFilter(e.target.value)} />
          </Field>
          <Field label="Aplikasi di HP" htmlFor="run-package" error={error}>
            <Select id="run-package" className="font-mono" value={pkg} onChange={(e) => onPackage(e.target.value)} aria-invalid={!!error}>
              <option value="">{packages.isLoading ? "Memuat daftar aplikasi..." : "Pilih aplikasi..."}</option>
              {shown.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <label htmlFor="apk-file" className="flex h-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-ink-600 text-sm text-fg-muted hover:bg-ink-850">
            <span className="flex items-center gap-2">
              <FileArrowUp className="text-lg" />
              {install.isPending ? "Memasang APK ke HP..." : "Pilih file .apk (maks 300 MB)"}
            </span>
          </label>
          <input
            id="apk-file"
            aria-label="File APK"
            type="file"
            accept=".apk"
            className="sr-only"
            disabled={!serial || install.isPending}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) install.mutate(file);
            }}
          />
          {install.data?.package && (
            <p className="flex items-center gap-1.5 text-sm text-pass">
              <CheckCircle weight="fill" />
              {install.data.package} terpasang dan dipilih
            </p>
          )}
          {install.data && !install.data.package && (
            <Field label="Aplikasi di HP" htmlFor="run-package" error={error} hint={install.data.message}>
              <Select id="run-package" className="font-mono" value={pkg} onChange={(e) => onPackage(e.target.value)}>
                <option value="">Pilih aplikasi...</option>
                {install.data.packages.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          {install.error && <Alert tone="error">{(install.error as Error).message}</Alert>}
          {error && !install.data && <p className="text-xs text-fail">{error}</p>}
        </div>
      )}
    </div>
  );
}
