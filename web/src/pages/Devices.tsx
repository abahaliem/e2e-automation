import { AndroidLogo, ArrowsClockwise, DeviceMobile, DeviceMobileCamera, PlugsConnected, Warning, WifiHigh } from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, Field, Input, PageHeader, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Device } from "@/lib/types";

export const STATE_LABEL: Record<string, { text: string; tone: string }> = {
  device: { text: "Siap dipakai", tone: "text-pass" },
  unauthorized: { text: "Izinkan USB debugging di HP (ketuk Izinkan pada dialog di layar HP)", tone: "text-review" },
  offline: { text: "Offline, cabut lalu sambungkan ulang kabel USB", tone: "text-fail" },
};

export function UsbDebuggingSteps() {
  return (
    <ol className="list-decimal space-y-1 pl-5 text-sm text-fg-muted">
      <li>Di HP buka Setelan, Tentang ponsel, lalu ketuk Nomor bentukan (Build number) 7 kali.</li>
      <li>Buka Setelan, Sistem, Opsi pengembang, lalu aktifkan Debugging USB.</li>
      <li>Sambungkan HP ke laptop dengan kabel data, lalu ketuk Izinkan pada dialog di HP.</li>
      <li>Emulator Android yang sedang berjalan juga otomatis muncul di sini.</li>
    </ol>
  );
}

export function useDevices() {
  return useQuery({ queryKey: ["devices"], queryFn: api.listDevices, refetchInterval: 5000, retry: false });
}

export function DevicesPage() {
  const devices = useDevices();
  const missing = devices.error instanceof ApiError && devices.error.status === 503;
  return (
    <main className="flex flex-col gap-8 px-10 py-8">
      <PageHeader
        title="Perangkat"
        description="HP Android atau emulator yang tersambung ke laptop ini lewat adb."
        actions={
          <Button onClick={() => devices.refetch()} disabled={devices.isFetching}>
            <ArrowsClockwise className={cn(devices.isFetching && "animate-spin")} />
            Muat ulang
          </Button>
        }
      />
      {devices.isLoading ? (
        <div className="grid grid-cols-3 gap-4">
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
      ) : devices.error ? (
        <Alert tone={missing ? "warning" : "error"}>
          <div className="font-medium">{missing ? "adb belum terpasang" : "Perangkat tidak bisa dibaca"}</div>
          <div className="mt-1">{(devices.error as Error).message}</div>
        </Alert>
      ) : devices.data && devices.data.devices.length > 0 ? (
        <div className="grid grid-cols-3 gap-4">
          {devices.data.devices.map((d) => (
            <DeviceCard key={d.serial} device={d} />
          ))}
        </div>
      ) : (
        <Card className="flex flex-col gap-4 p-6">
          <div className="flex items-center gap-3">
            <DeviceMobileCamera className="text-3xl text-fg-muted" />
            <div>
              <div className="font-medium">Belum ada HP yang tersambung</div>
              <div className="text-sm text-fg-muted">Ikuti langkah berikut, daftar ini diperbarui otomatis.</div>
            </div>
          </div>
          <UsbDebuggingSteps />
        </Card>
      )}
      {!missing && <ConnectNetwork onConnected={() => devices.refetch()} />}
    </main>
  );
}

/** HP lewat Wireless debugging (Android 11+) atau HP di jaringan server: `adb pair` (opsional) lalu `adb connect`. */
export function ConnectNetwork({ onConnected }: { onConnected: () => void }) {
  const [address, setAddress] = useState("");
  const [pairing, setPairing] = useState(false);
  const [pairAddress, setPairAddress] = useState("");
  const [pairCode, setPairCode] = useState("");
  const connect = useMutation({
    mutationFn: () =>
      api.connectDevice({
        address: address.trim(),
        ...(pairing && pairAddress.trim() && pairCode.trim() ? { pair_address: pairAddress.trim(), pair_code: pairCode.trim() } : {}),
      }),
    onSuccess: () => {
      setPairCode("");
      onConnected();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (address.trim()) connect.mutate();
  };
  return (
    <Card className="max-w-3xl p-6">
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <WifiHigh className="text-2xl text-accent" />
          <div>
            <h2 className="font-semibold">Sambungkan lewat jaringan</h2>
            <p className="text-sm text-fg-muted">
              Tanpa kabel: aktifkan Wireless debugging di HP, lalu isi IP:port yang tampil di layarnya. HP dan komputer ini
              harus satu jaringan.
            </p>
          </div>
        </div>
        <Field label="Alamat HP (IP:port)" htmlFor="net-address">
          <Input id="net-address" className="font-mono" placeholder="192.168.1.20:5555" value={address} onChange={(e) => setAddress(e.target.value)} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={pairing} onChange={(e) => setPairing(e.target.checked)} className="h-4 w-4 accent-[var(--color-accent)]" />
          Pertama kali? Pasangkan dulu dengan kode pairing (Android 11+)
        </label>
        {pairing && (
          <div className="grid grid-cols-2 gap-4">
            <Field label="Alamat pairing (IP:port)" htmlFor="net-pair-address" hint="Dari menu Pasangkan perangkat dengan kode">
              <Input id="net-pair-address" className="font-mono" placeholder="192.168.1.20:37001" value={pairAddress} onChange={(e) => setPairAddress(e.target.value)} />
            </Field>
            <Field label="Kode pairing" htmlFor="net-pair-code">
              <Input id="net-pair-code" inputMode="numeric" className="font-mono" placeholder="123456" value={pairCode} onChange={(e) => setPairCode(e.target.value)} />
            </Field>
          </div>
        )}
        {connect.error && <Alert tone="error">{(connect.error as Error).message}</Alert>}
        {connect.data && <Alert tone="success">Tersambung: {connect.data.message}</Alert>}
        <div>
          <Button type="submit" variant="primary" disabled={connect.isPending || !address.trim()}>
            <PlugsConnected />
            {connect.isPending ? "Menyambungkan..." : "Sambungkan"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function DeviceCard({ device }: { device: Device }) {
  const state = STATE_LABEL[device.state] ?? { text: device.state, tone: "text-fg-muted" };
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-ink-850">
          {device.emulator ? <DeviceMobile className="text-xl text-accent" /> : <AndroidLogo className="text-xl text-pass" />}
        </div>
        <div className="min-w-0">
          <div className="truncate font-medium">{device.model || device.serial}</div>
          <div className="truncate font-mono text-xs text-fg-dim">{device.serial}</div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        {device.emulator && <span className="rounded bg-accent-soft px-1.5 py-0.5 text-accent">Emulator</span>}
        {device.android_version && <span className="rounded bg-ink-800 px-1.5 py-0.5">Android {device.android_version}</span>}
      </div>
      <div className={cn("flex items-start gap-1.5 text-sm", state.tone)}>
        {device.state !== "device" && <Warning className="mt-0.5 shrink-0" />}
        {state.text}
      </div>
      {device.state === "device" && (
        <Link to="/runs/new?platform=android" className="text-sm text-accent">
          Uji aplikasi di perangkat ini
        </Link>
      )}
    </Card>
  );
}
