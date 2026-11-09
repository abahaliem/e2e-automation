import { LockSimple, SignIn } from "@phosphor-icons/react";
import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Logo } from "@/components/AppShell";
import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";

export function LoginPage({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({ mutationFn: () => api.login(username.trim(), password), onSuccess: onLoggedIn });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (username.trim() && password) login.mutate();
  };
  return (
    <main className="grid min-h-[100dvh] place-items-center bg-ink-850 px-4">
      <Card className="w-full max-w-sm p-8">
        <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
          <div className="flex items-center gap-2.5">
            <Logo />
            <span className="font-semibold tracking-tight">QA Agent</span>
          </div>
          <div>
            <h1 className="text-lg font-semibold">Masuk</h1>
            <p className="mt-1 text-sm text-fg-muted">Dashboard ini dipakai bersama tim. Masuk dengan akun dari Admin.</p>
          </div>
          <Field label="Username" htmlFor="login-user">
            <Input id="login-user" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} />
          </Field>
          <Field label="Password" htmlFor="login-pass">
            <Input id="login-pass" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          {login.error && <Alert tone="error">{(login.error as Error).message}</Alert>}
          <Button type="submit" variant="primary" size="lg" disabled={login.isPending || !username.trim() || !password}>
            <SignIn />
            {login.isPending ? "Memeriksa..." : "Masuk"}
          </Button>
          <p className="flex items-center gap-1.5 text-xs text-fg-muted">
            <LockSimple />
            Lupa password? Minta Admin mengatur ulang di Pengaturan, Keamanan.
          </p>
        </form>
      </Card>
    </main>
  );
}
