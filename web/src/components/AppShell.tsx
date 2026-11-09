import {
  ClockCounterClockwise,
  DeviceMobile,
  Gauge,
  GearSix,
  PlayCircle,
  Scan,
  SignOut,
  SquaresFour,
  type Icon,
} from "@phosphor-icons/react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { ROLE_LABEL, useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";

export type ShellProfile = { name: string; model: string; ok: boolean | null } | null;

type Item = { to: string; label: string; icon: Icon; match: (path: string) => boolean; soon?: boolean };

const ITEMS: Item[] = [
  { to: "/", label: "Dashboard", icon: Gauge, match: (p) => p === "/" },
  { to: "/runs/new", label: "Run baru", icon: PlayCircle, match: (p) => p === "/runs/new" },
  {
    to: "/runs",
    label: "Riwayat run",
    icon: ClockCounterClockwise,
    match: (p) => p.startsWith("/runs") && p !== "/runs/new",
  },
  { to: "/apps", label: "Aplikasi", icon: SquaresFour, match: (p) => p.startsWith("/apps") },
  { to: "/devices", label: "Perangkat", icon: DeviceMobile, match: (p) => p.startsWith("/devices") },
  { to: "/settings", label: "Pengaturan", icon: GearSix, match: (p) => p.startsWith("/settings") },
];

export function Logo() {
  return (
    <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent">
      <Scan weight="bold" className="text-lg text-white" />
    </div>
  );
}

/** Mode server: nama pengguna, peran, dan tombol Keluar. Mode lokal: tidak tampil. */
function UserBox() {
  const { status, logout } = useAuth();
  const user = status.user;
  if (!status.auth_required || !user) return <div className="mt-auto" />;
  return (
    <div className="mx-3 mt-auto flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent-soft font-medium text-accent">
        {user.username.slice(0, 1).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{user.username}</div>
        <div className="text-xs text-fg-muted">{ROLE_LABEL[user.role]}</div>
      </div>
      <button type="button" onClick={logout} title="Keluar" aria-label="Keluar" className="rounded-md p-1.5 text-fg-muted hover:bg-ink-850 hover:text-fg">
        <SignOut className="text-lg" />
      </button>
    </div>
  );
}

export function AppShell({ profile }: { profile: ShellProfile }) {
  const { pathname } = useLocation();
  return (
    <div className="grid min-h-[100dvh] grid-cols-[232px_minmax(0,1fr)]">
      <aside className="sticky top-0 flex h-[100dvh] flex-col border-r border-ink-700 bg-ink-900">
        <div className="flex h-16 items-center gap-2.5 border-b border-ink-700 px-5">
          <Logo />
          <span className="font-semibold tracking-tight">QA Agent</span>
        </div>
        <nav className="flex flex-col gap-1 p-3 text-sm" aria-label="Menu utama">
          {ITEMS.map((item) => {
            const active = item.match(pathname);
            const Icon = item.icon;
            if (item.soon) {
              return (
                <div
                  key={item.to}
                  aria-disabled="true"
                  title="Tersedia di sub-proyek Android"
                  className="flex items-center gap-3 rounded-lg px-3 py-2 text-fg-dim"
                >
                  <Icon className="text-lg" />
                  <span>{item.label}</span>
                  <span className="ml-auto rounded bg-ink-800 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide">
                    segera
                  </span>
                </div>
              );
            }
            return (
              <Link
                key={item.to}
                to={item.to}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 transition-colors",
                  active ? "bg-ink-800 text-fg" : "text-fg-muted hover:bg-ink-850 hover:text-fg",
                )}
              >
                <Icon className={cn("text-lg", active && "text-accent")} weight={active ? "fill" : "regular"} />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <UserBox />
        <div className="m-3 mt-2 rounded-lg border border-ink-700 p-3 text-xs">
          {profile ? (
            <>
              <div className="flex items-center gap-2 text-fg">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full",
                    profile.ok === false ? "bg-fail" : profile.ok ? "bg-pass" : "bg-ink-500",
                  )}
                />
                <span className="truncate">{profile.name}</span>
              </div>
              <div className="mt-1 truncate font-mono text-fg-dim">{profile.model}</div>
            </>
          ) : (
            <Link to="/settings" className="flex items-center gap-2 text-review">
              <span className="h-2 w-2 rounded-full bg-review" />
              Profil AI belum diatur
            </Link>
          )}
        </div>
      </aside>
      <div className="min-w-0">
        <Outlet />
      </div>
    </div>
  );
}
