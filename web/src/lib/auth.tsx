import { createContext, useContext, type ReactNode } from "react";
import type { AuthStatus, Role } from "./types";

type AuthValue = { status: AuthStatus; logout: () => void };

const LOCAL: AuthValue = { status: { auth_required: false, user: null }, logout: () => {} };
const AuthContext = createContext<AuthValue>(LOCAL);

export function AuthProvider({ value, children }: { value: AuthValue; children: ReactNode }) {
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  return useContext(AuthContext);
}

export const ROLE_LABEL: Record<Role, string> = { admin: "Admin", qa: "QA", viewer: "Viewer" };

/** Mode lokal: semua boleh. Mode server: Admin semua, QA tanpa pengaturan, Viewer hanya melihat. */
export function useCan() {
  const { status } = useAuth();
  const role = status.auth_required ? status.user?.role ?? "viewer" : "admin";
  return { role, write: role !== "viewer", admin: role === "admin", server: status.auth_required };
}
