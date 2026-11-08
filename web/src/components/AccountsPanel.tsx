import { Key, Trash, UserPlus } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, api } from "@/lib/api";
import { Alert, Button, EmptyState, Field, Input, Skeleton } from "./ui";

export function AccountsPanel({ appId }: { appId: number }) {
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["accounts", appId], queryFn: () => api.listAccounts(appId) });
  const [role, setRole] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["accounts", appId] });
    qc.invalidateQueries({ queryKey: ["apps"] });
  };

  const create = useMutation({
    mutationFn: () => api.createAccount(appId, { role: role.trim(), username: username.trim(), password }),
    onSuccess: () => {
      setRole("");
      setUsername("");
      setPassword("");
      setErrors({});
      setMessage("Akun disimpan. Password tersimpan di Windows Credential Manager.");
      refresh();
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors({ ...e.fieldErrors, _: e.fieldErrors && Object.keys(e.fieldErrors).length ? "" : e.message });
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => api.deleteAccount(id), onSuccess: refresh });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!role.trim()) next.role = "Wajib diisi";
    if (!username.trim()) next.username = "Wajib diisi";
    if (!password) next.password = "Wajib diisi";
    setErrors(next);
    setMessage(null);
    if (Object.keys(next).length === 0) create.mutate();
  };

  return (
    <div className="flex flex-col gap-4">
      {accounts.isLoading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : accounts.data && accounts.data.length > 0 ? (
        <ul className="divide-y divide-ink-700 rounded-lg border border-ink-700">
          {accounts.data.map((acc) => (
            <li key={acc.id} className="flex items-center gap-3 px-4 py-3 text-sm">
              <Key className="text-fg-muted" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{acc.username}</div>
                <div className="text-xs text-fg-muted">
                  Peran {acc.role} ·{" "}
                  <span className={acc.has_password ? "text-pass" : "text-review"}>
                    {acc.has_password ? "Password tersimpan" : "Password belum ada"}
                  </span>
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Hapus akun ${acc.username}`}
                onClick={() => remove.mutate(acc.id)}
              >
                <Trash />
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState title="Belum ada akun test" description="Tambahkan akun yang dipakai agent untuk login ke aplikasi." />
      )}

      <form onSubmit={submit} className="grid grid-cols-1 gap-3 rounded-lg border border-ink-700 bg-ink-850 p-4 md:grid-cols-3" noValidate>
        <Field label="Peran" htmlFor={`acc-role-${appId}`} error={errors.role}>
          <Input id={`acc-role-${appId}`} value={role} placeholder="admin" onChange={(e) => setRole(e.target.value)} aria-invalid={!!errors.role} />
        </Field>
        <Field label="Username / email" htmlFor={`acc-user-${appId}`} error={errors.username}>
          <Input id={`acc-user-${appId}`} value={username} autoComplete="off" onChange={(e) => setUsername(e.target.value)} aria-invalid={!!errors.username} />
        </Field>
        <Field label="Password" htmlFor={`acc-pass-${appId}`} error={errors.password}>
          <Input
            id={`acc-pass-${appId}`}
            type="password"
            value={password}
            autoComplete="new-password"
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!errors.password}
          />
        </Field>
        <div className="flex items-center gap-3 md:col-span-3">
          <Button type="submit" variant="primary" disabled={create.isPending}>
            <UserPlus />
            Tambah akun
          </Button>
          <span className="text-xs text-fg-muted">Password disimpan di Windows Credential Manager, tidak pernah dikirim ke AI atau laporan.</span>
        </div>
        {errors._ && (
          <div className="md:col-span-3">
            <Alert tone="error">{errors._}</Alert>
          </div>
        )}
        {message && (
          <div className="md:col-span-3">
            <Alert tone="success">{message}</Alert>
          </div>
        )}
      </form>
    </div>
  );
}
