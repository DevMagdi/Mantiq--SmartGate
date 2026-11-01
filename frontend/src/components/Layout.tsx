import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { Icon, type IconName } from "@/components/Icon";
import { Badge, Button, cn } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { useI18n, type TranslationKey } from "@/i18n";
import type { UserRole } from "@/types/models";
import { initials } from "@/utils/format";

interface NavItem {
  path: string;
  label: TranslationKey;
  residentLabel?: TranslationKey;
  icon: IconName;
  roles: UserRole[];
}

const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "nav.dashboard", icon: "dashboard", roles: ["admin", "security_officer"] },
  { path: "/live", label: "nav.live", icon: "live", roles: ["admin", "security_officer"] },
  { path: "/registry", label: "nav.registry", residentLabel: "nav.registry.resident", icon: "users", roles: ["admin", "security_officer", "resident"] },
  { path: "/visitors", label: "nav.visitors", residentLabel: "nav.visitors.resident", icon: "visitors", roles: ["admin", "security_officer", "resident"] },
  { path: "/logs", label: "nav.logs", residentLabel: "nav.logs.resident", icon: "logs", roles: ["admin", "security_officer", "resident"] },
  { path: "/security", label: "nav.security", icon: "shield", roles: ["admin", "security_officer"] },
  { path: "/settings", label: "nav.settings", icon: "settings", roles: ["admin", "security_officer", "resident"] },
];

function useRoleLabel(): (role: UserRole) => string {
  const { t } = useI18n();
  return (role) => t(`role.${role}`);
}

function LanguageToggle({ compact = false }: { compact?: boolean }): JSX.Element {
  const { t, locale, toggleLocale } = useI18n();
  return (
    <button
      type="button"
      onClick={toggleLocale}
      title={locale === "ar" ? "Switch to English" : "التبديل إلى العربية"}
      aria-label={locale === "ar" ? "Switch to English" : "التبديل إلى العربية"}
      className={cn(
        "focus-ring inline-flex items-center justify-center gap-1.5 rounded-lg border border-ink-200 font-semibold text-ink-600 transition hover:border-ink-300 hover:bg-ink-50 dark:border-ink-700 dark:text-ink-300 dark:hover:bg-ink-800",
        compact ? "h-8 px-2 text-[11px]" : "h-9 px-3 text-xs",
      )}
    >
      <span aria-hidden className="text-[13px] leading-none">ع</span>
      <span className="truncate">{compact ? t("lang.name") : t("lang.switch")}</span>
    </button>
  );
}

function BrandMark({ compact = false }: { compact?: boolean }): JSX.Element {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2.5">
      <span className="relative grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-glow">
        <Icon name="gate" className="h-5 w-5" />
        <span className="absolute -end-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-brand-300 dark:border-ink-900" />
      </span>
      {!compact ? (
        <div>
          <p className="text-sm font-bold tracking-tight text-ink-900 dark:text-white">GateVision</p>
          <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-ink-400">
            {t("shell.tagline")}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }): JSX.Element {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const { t } = useI18n();
  const roleLabel = useRoleLabel();
  const location = useLocation();
  const role = user?.role ?? "resident";
  const items = NAV_ITEMS.filter((item) => item.roles.includes(role));

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center px-5">
        <BrandMark />
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        <p className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-400">
          {t("shell.workspace")}
        </p>
        {items.map((item) => (
          <NavLink
            key={`${item.path}-${item.label}`}
            to={item.path}
            end={item.path === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
                isActive || (item.path === "/" && location.pathname === "")
                  ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300"
                  : "text-ink-600 hover:bg-ink-100 hover:text-ink-900 dark:text-ink-400 dark:hover:bg-ink-800/70 dark:hover:text-white",
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon
                  name={item.icon}
                  className={cn(
                    "h-4 w-4 transition",
                    isActive ? "text-brand-600 dark:text-brand-400" : "text-ink-400 group-hover:text-ink-600 dark:group-hover:text-ink-200",
                  )}
                />
                <span className="flex-1 truncate">
                  {t(role === "resident" && item.residentLabel ? item.residentLabel : item.label)}
                </span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-ink-100 p-3 dark:border-ink-800">
        <div className="flex items-center gap-3 rounded-xl px-2 py-2">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-ink-900 text-xs font-bold text-white dark:bg-ink-100 dark:text-ink-900">
            {initials(user?.full_name)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-semibold text-ink-900 dark:text-ink-100">
              {user?.full_name}
            </p>
            <p className="truncate text-[10px] text-ink-400">
              {user ? roleLabel(user.role) : ""}
            </p>
          </div>
        </div>
        <div className="mt-1 flex gap-2">
          <Button variant="outline" size="sm" className="flex-1" onClick={toggle} icon={theme === "dark" ? "sun" : "moon"}>
            {theme === "dark" ? t("shell.light") : t("shell.dark")}
          </Button>
          <LanguageToggle compact />
          <Button variant="ghost" size="sm" onClick={() => void logout()} aria-label={t("shell.signout")}>
            <Icon name="logout" className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

export function Layout(): JSX.Element {
  const { user } = useAuth();
  const { t, intlLocale } = useI18n();
  const roleLabel = useRoleLabel();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  const current = [...NAV_ITEMS]
    .filter((item) => (item.roles.includes(user?.role ?? "resident")))
    .sort((a, b) => b.path.length - a.path.length)
    .find((item) => (item.path === "/" ? location.pathname === "/" : location.pathname.startsWith(item.path)));

  return (
    <div className="min-h-screen bg-ink-50 dark:bg-ink-950">
      <aside className="fixed inset-y-0 start-0 z-40 hidden w-64 border-e border-ink-100 bg-white/90 backdrop-blur dark:border-ink-800 dark:bg-ink-900/80 lg:block">
        <SidebarContent />
      </aside>

      {menuOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-ink-950/50 backdrop-blur-sm" onClick={() => setMenuOpen(false)} />
          <aside className="relative h-full w-72 max-w-[85%] border-e border-ink-100 bg-white shadow-2xl dark:border-ink-800 dark:bg-ink-900">
            <SidebarContent onNavigate={() => setMenuOpen(false)} />
          </aside>
        </div>
      ) : null}

      <div className="lg:ps-64">
        <header className="sticky top-0 z-30 border-b border-ink-100/80 bg-white/85 backdrop-blur dark:border-ink-800 dark:bg-ink-950/80">
          <div className="flex h-16 items-center gap-3 px-4 sm:px-6 lg:px-8">
            <button
              type="button"
              onClick={() => setMenuOpen(true)}
              className="rounded-lg p-2 text-ink-500 hover:bg-ink-100 dark:hover:bg-ink-800 lg:hidden"
              aria-label={t("shell.open_nav")}
            >
              <Icon name="menu" className="h-5 w-5" />
            </button>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-ink-900 dark:text-ink-100">
                {current ? t(current.label) : "GateVision"}
              </p>
              <p className="truncate text-[11px] text-ink-400">
                {new Intl.DateTimeFormat(intlLocale, { dateStyle: "full" }).format(new Date())}
              </p>
            </div>
            <Badge tone={user?.is_active ? "success" : "neutral"} dot className="hidden sm:inline-flex">
              {user ? roleLabel(user.role) : t("shell.guest")}
            </Badge>
            <div className="hidden sm:block">
              <LanguageToggle compact />
            </div>
            <a
              href="https://github.com/DevMagdi/Mantiq--SmartGate"
              target="_blank"
              rel="noreferrer"
              className="hidden rounded-lg p-2 text-ink-400 transition hover:bg-ink-100 hover:text-ink-700 sm:block dark:hover:bg-ink-800"
              aria-label={t("shell.repository")}
            >
              <Icon name="sparkles" className="h-4 w-4" />
            </a>
          </div>
        </header>
        <main className="px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-[1600px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
