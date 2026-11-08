import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

export function renderWithProviders(ui: ReactElement, { path = "/", route = "*" }: { path?: string; route?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={ui} />
          <Route path="*" element={<div data-testid="navigated" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const profile = {
  id: 1,
  name: "AI kantor (GLM)",
  provider: "openai_compatible" as const,
  base_url: "http://192.168.151.121/v1",
  model: "z-ai/glm-5.3-flash",
  vision: true,
  timeout_seconds: 120,
  is_default: true,
  api_key_masked: "sk-••••3f9a",
  has_api_key: true,
};

export const app = {
  id: 3,
  name: "Web HR",
  platform: "web" as const,
  url: "http://hr-dev.kantor.local",
  allowed_domains: ["hr-dev.kantor.local"],
  login_endpoints: [],
  default_profile_id: null,
  explored: true,
  last_run_at: null,
  accounts: 1,
};
