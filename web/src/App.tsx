import { useQuery } from "@tanstack/react-query";
import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";
import { AppsPage } from "@/pages/Apps";
import { DashboardPage } from "@/pages/Dashboard";
import { DevicesPage } from "@/pages/Devices";
import { HistoryPage } from "@/pages/History";
import { NotFoundPage } from "@/pages/NotFound";
import { RunLivePage } from "@/pages/RunLive";
import { RunNewPage } from "@/pages/RunNew";
import { RunResultPage } from "@/pages/RunResult";
import { SettingsPage } from "@/pages/Settings";

export function App() {
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
