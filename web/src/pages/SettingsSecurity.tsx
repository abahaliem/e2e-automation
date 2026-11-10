import { Key, LockSimple, ShieldCheck, Trash, UserPlus } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Alert, Button, Card, Field, Input, Select, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { ROLE_LABEL, useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import type { Role, UserRow } from "@/lib/types";

const ROLE_HELP: Record<Role, string> = {
  admin: "Semua, termasuk Pengaturan dan kelola pengguna",
  qa: "Aplikasi, akun test, run, intervensi, review",
  viewer: "Hanya melihat dan mengunduh dokumen",
};

function errorText(e: unknown): string {
  if (e instanceof ApiError) return Object.values(e.fieldErrors)[0] ?? e.message;
  return String(e);
}

export function SecurityTab() {
  const { status } = useAuth();
  if (!status.auth_required) return <LocalModeInfo />;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_340px] gap-10">
      <div className="flex flex-col gap-6">{status.user?.role === "admin" ? <UsersPanel /> : <ServerModeInfo />}</div>
      <aside className="flex flex-col gap-6">
        <ChangePassword />
      </aside>
    </div>
  );
}

function LocalModeInfo() {
  return (
    <Card className="flex max-w-3xl flex-col gap-4 p-6">
      <div className="flex items-center gap-3">
        <ShieldCheck weight="fill" className="text-2xl text-pass" />
        <div>
          <h2 className="font-semibold">Mode lokal</h2>
          <p className="text-sm text-fg-muted">Tanpa login. Dashboard hanya bisa dibuka dari laptop ini (127.0.0.1).</p>
        </div>
      </div>
      <ul className="list-disc space-y-1.5 pl-5 text-sm text-fg-muted">
        <li>API key AI dan password akun test disimpan di Windows Credential Manager, tidak pernah masuk ke laporan, log, atau Git.</li>
        <li>Password akun test tidak pernah dikirim ke AI; agent hanya melihat penanda {"{{password}}"}.</li>
        <li>
          Untuk dipakai bersama tim, pasang QA Agent di server dengan login & peran (Admin, QA, Viewer):{" "}
          <span className="font-mono text-xs text-fg">qa-agent serve --host 0.0.0.0 --auth</span> atau Docker. Panduan lengkap ada di{" "}
          <span className="font-mono text-xs text-fg">docs/deploy.md</span>.
        </li>
      </ul>
    </Card>
  );
}

function ServerModeInfo() {
  const { status } = useAuth();
  const role = status.user?.role ?? "viewer";
  return (
    <Card className="flex flex-col gap-3 p-6">
      <h2 className="font-semibold">Akun saya</h2>
      <p className="text-sm text-fg-muted">
        Masuk sebagai <span className="font-medium text-fg">{status.user?.username}</span> dengan peran{" "}
        <span className="font-medium text-fg">{ROLE_LABEL[role]}</span>: {ROLE_HELP[role].toLowerCase()}.
      </p>
      <p className="text-sm text-fg-muted">Pengguna dan peran dikelola oleh Admin.</p>
    </Card>
  );
}

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const change = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setConfirm("");
      setError(null);
    },
    onError: (e) => setError(errorText(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    change.reset();
    if (next.length < 8) return setError("Password baru minimal 8 karakter");
    if (next !== confirm) return setError("Konfirmasi password tidak sama");
    setError(null);
    change.mutate();
  };
  return (
    <Card className="p-5">
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <h2 className="flex items-center gap-2 font-semibold">
          <Key />
          Ganti password saya
        </h2>
        <Field label="Password saat ini" htmlFor="pw-current">
          <Input id="pw-current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Field>
        <Field label="Password baru" htmlFor="pw-new" hint="Minimal 8 karakter">
          <Input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Field label="Ulangi password baru" htmlFor="pw-confirm">
          <Input id="pw-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        {error && <Alert tone="error">{error}</Alert>}
        {change.isSuccess && <Alert tone="success">Password diganti</Alert>}
        <Button type="submit" variant="primary" disabled={change.isPending || !current || !next}>
          Simpan password
        </Button>
      </form>
    </Card>
  );
}

function UsersPanel() {
  const users = useQuery({ queryKey: ["users"], queryFn: api.listUsers });
  const { status } = useAuth();
  return (
    <>
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-4">
          <div>
            <h2 className="font-semibold">Pengguna</h2>
            <p className="text-sm text-fg-muted">Siapa saja yang bisa masuk ke dashboard ini dan apa yang boleh dilakukan.</p>
          </div>
        </div>
        {users.isLoading ? (
          <Skeleton className="m-5 h-32" />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-850 text-left text-xs text-fg-muted">
              <tr>
                <th className="px-5 py-2 font-medium">Username</th>
                <th className="px-3 py-2 font-medium">Peran</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Terakhir masuk</th>
                <th className="px-5 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-700">
              {(users.data ?? []).map((u) => (
                <UserRowItem key={u.id} user={u} self={u.id === status.user?.id} />
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <AddUser />
      <div className="grid grid-cols-3 gap-3 text-xs text-fg-muted">
        {(Object.keys(ROLE_HELP) as Role[]).map((r) => (
          <div key={r} className="rounded-lg border border-ink-700 p-3">
            <div className="mb-1 font-medium text-fg">{ROLE_LABEL[r]}</div>
            {ROLE_HELP[r]}
          </div>
        ))}
      </div>
    </>
  );
}

function UserRowItem({ user, self }: { user: UserRow; self: boolean }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [password, setPassword] = useState("");
  const done = () => {
    setError(null);
    qc.invalidateQueries({ queryKey: ["users"] });
  };
  const update = useMutation({
    mutationFn: (body: { role?: Role; active?: boolean; password?: string }) => api.patchUser(user.id, body),
    onSuccess: () => {
      setResetting(false);
      setPassword("");
      done();
    },
    onError: (e) => setError(errorText(e)),
  });
  const remove = useMutation({ mutationFn: () => api.deleteUser(user.id), onSuccess: done, onError: (e) => setError(errorText(e)) });
  return (
    <tr className={cn(!user.active && "text-fg-dim")}>
      <td className="px-5 py-3">
        <div className="font-medium">
          {user.username}
          {self && <span className="ml-2 rounded bg-accent-soft px-1.5 py-0.5 text-[11px] text-accent">Anda</span>}
        </div>
        {error && (
          <div role="alert" className="mt-1 text-xs text-fail">
            {error}
          </div>
        )}
        {resetting && (
          <form
            className="mt-2 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              update.mutate({ password });
            }}
          >
            <Input
              type="password"
              aria-label={`Password baru ${user.username}`}
              placeholder="Password baru (min. 8)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-8"
            />
            <Button type="submit" size="sm" variant="primary" disabled={password.length < 8}>
              Simpan
            </Button>
          </form>
        )}
      </td>
      <td className="px-3 py-3">
        <Select
          aria-label={`Peran ${user.username}`}
          value={user.role}
          onChange={(e) => update.mutate({ role: e.target.value as Role })}
          className="h-8 w-28"
        >
          {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
            <option key={r} value={r}>
              {ROLE_LABEL[r]}
            </option>
          ))}
        </Select>
      </td>
      <td className="px-3 py-3">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={user.active}
            aria-label={`Aktif ${user.username}`}
            onChange={(e) => update.mutate({ active: e.target.checked })}
            className="h-4 w-4 accent-[var(--color-accent)]"
          />
          {user.active ? "Aktif" : "Nonaktif"}
        </label>
      </td>
      <td className="px-3 py-3 text-xs text-fg-muted">{user.last_login ? new Date(user.last_login).toLocaleString("id-ID") : "Belum pernah"}</td>
      <td className="px-5 py-3">
        <div className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" onClick={() => setResetting((v) => !v)}>
            <LockSimple />
            Atur ulang password
          </Button>
          {!self && (
            <Button size="sm" variant="ghost" aria-label={`Hapus ${user.username}`} className="text-fail!" onClick={() => remove.mutate()}>
              <Trash />
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}

function AddUser() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("qa");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const add = useMutation({
    mutationFn: () => api.createUser({ username: username.trim(), password, role }),
    onSuccess: () => {
      setUsername("");
      setPassword("");
      setErrors({});
      qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => setErrors(e instanceof ApiError && Object.keys(e.fieldErrors).length ? e.fieldErrors : { _: errorText(e) }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!username.trim()) next.username = "Wajib diisi";
    if (password.length < 8) next.password = "Password minimal 8 karakter";
    setErrors(next);
    if (!Object.keys(next).length) add.mutate();
  };
  return (
    <Card className="p-5">
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <h2 className="flex items-center gap-2 font-semibold">
          <UserPlus />
          Tambah pengguna
        </h2>
        <div className="grid grid-cols-[1fr_1fr_160px] gap-4">
          <Field label="Username" htmlFor="nu-name" error={errors.username}>
            <Input id="nu-name" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />
          </Field>
          <Field label="Password awal" htmlFor="nu-pass" error={errors.password}>
            <Input id="nu-pass" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <Field label="Peran" htmlFor="nu-role">
            <Select id="nu-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {errors._ && <Alert tone="error">{errors._}</Alert>}
        <div>
          <Button type="submit" variant="primary" disabled={add.isPending}>
            <UserPlus />
            Tambah
          </Button>
        </div>
      </form>
    </Card>
  );
}
