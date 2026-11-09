import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { UNAUTHORIZED_EVENT, api } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import type { AuthStatus } from "@/lib/types";
import { AppsPage } from "@/pages/Apps";
import { DashboardPage } from "@/pages/Dashboard";
import { DevicesPage } from "@/pages/Devices";
import { HistoryPage } from "@/pages/History";
import { LoginPage } from "@/pages/Login";
import { NotFoundPage } from "@/pages/NotFound";
import { RunLivePage } from "@/pages/RunLive";
import { RunNewPage } from "@/pages/RunNew";
import { RunResultPage } from "@/pages/RunResult";
import { SettingsPage } from "@/pages/Settings";

const LOCAL: AuthStatus = { auth_required: false, user: null };

export function App() {
  const qc = useQueryClient();
  const auth = useQuery({ queryKey: ["auth"], queryFn: api.authStatus, staleTime: 60_000, retry: false });
  useEffect(() => {
    const onUnauthorized = () => qc.invalidateQueries({ queryKey: ["auth"] });
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [qc]);

  if (auth.isLoading) return <div className="min-h-[100dvh] bg-ink-850" aria-busy="true" />;
  const status = auth.data ?? LOCAL;
  if (status.auth_required && !status.user) {
    // Setelah login: muat ulang semua data dengan sesi baru
    return <LoginPage onLoggedIn={() => qc.resetQueries()} />;
  }
  const logout = async () => {
    try {
      await api.logout();
    } finally {
      qc.clear();
      qc.invalidateQueries({ queryKey: ["auth"] });
    }
  };
  return (
    <AuthProvider value={{ status, logout }}>
      <Shell />
    </AuthProvider>
  );
}

function Shell() {
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: api.listProfiles });
  const current = profiles.data?.find((p) => p.is_default) ?? profiles.data?.[0];
  const shellProfile = current ? { name: current.name, model: current.model, ok: current.has_api_key || current.provider === "anthropic" ? true : null } : null;
  return (
    <Routes>
      <Route element={<AppShell profile={profiles.isLoading ? { name: "Memuat...", model: "", ok: null } : shellProfile} />}>
        <Route index element={<DashboardPage />} />
        <Route path="runs" element={<HistoryPage />} />
        <Route path="runs/new" element={<RunNewPage />} />
        <Route path="runs/:runId/result" element={<RunResultPage />} />
        <Route path="apps" element={<AppsPage />} />
        <Route path="devices" element={<DevicesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      <Route path="runs/:runId" element={<RunLivePage />} />
    </Routes>
  );
}
