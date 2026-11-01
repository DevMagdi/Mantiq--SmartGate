import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { Badge, Button, Input, cn } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { useToast } from "@/hooks/useToast";
import { useI18n } from "@/i18n";
import { apiErrorMessage } from "@/services/api";
import { DEMO_ACCOUNTS } from "@/utils/constants";

const HIGHLIGHTS = [
  { icon: "camera" as const, title: "ANPR plate recognition", detail: "YOLO detector + swappable OCR" },
  { icon: "shield" as const, title: "InsightFace recognition", detail: "Resident gallery with 512-d embeddings" },
  { icon: "live" as const, title: "Realtime gate events", detail: "WebSocket feed and live decisions" },
  { icon: "logs" as const, title: "Audited access control", detail: "Every decision stored with snapshots" },
];

export function LoginPage(): JSX.Element {
  const { login, status } = useAuth();
  const { theme, toggle } = useTheme();
  const { t, locale, toggleLocale } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [email, setEmail] = useState("admin@gatevision.app");
  const [password, setPassword] = useState("Admin@12345");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    document.title = `${t("login.submit")} · GateVision`;
  }, [t]);

  if (status === "authenticated") {
    return <Navigate to={from} replace />;
  }

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const user = await login(email, password);
      toast.success(`Welcome back, ${user.full_name.split(" ")[0]}`);
      navigate(from, { replace: true });
    } catch (caught) {
      const message = apiErrorMessage(caught);
      setError(message);
      toast.error("Sign in failed", message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="relative min-h-screen bg-ink-50 dark:bg-ink-950">
      <div className="absolute end-4 top-4 z-20 flex items-center gap-2">
        <button
          type="button"
          onClick={toggleLocale}
          className="rounded-lg border border-ink-200 bg-white/80 px-2.5 py-2 text-[11px] font-semibold text-ink-500 backdrop-blur transition hover:text-ink-800 dark:border-ink-700 dark:bg-ink-900/80 dark:text-ink-300"
          aria-label={locale === "ar" ? "Switch to English" : "التبديل إلى العربية"}
        >
          {t("lang.switch")}
        </button>
        <button
          type="button"
          onClick={toggle}
          className="rounded-lg border border-ink-200 bg-white/80 p-2 text-ink-500 backdrop-blur transition hover:text-ink-800 dark:border-ink-700 dark:bg-ink-900/80 dark:text-ink-300"
          aria-label="Toggle dark mode"
        >
          <Icon name={theme === "dark" ? "sun" : "moon"} className="h-4 w-4" />
        </button>
      </div>

      <div className="grid min-h-screen lg:grid-cols-2">
        <section className="relative hidden overflow-hidden bg-ink-950 p-10 text-white lg:flex lg:flex-col lg:justify-between">
          <div className="absolute inset-0 opacity-70">
            <div className="absolute -left-24 -top-24 h-96 w-96 rounded-full bg-brand-500/25 blur-3xl" />
            <div className="absolute -bottom-32 -right-20 h-[28rem] w-[28rem] rounded-full bg-emerald-400/10 blur-3xl" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(16,185,129,0.18),transparent_45%)]" />
          </div>

          <div className="relative">
            <div className="flex items-center gap-2.5">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 text-white shadow-glow">
                <Icon name="gate" className="h-5 w-5" />
              </span>
              <div>
                <p className="text-base font-bold tracking-tight">GateVision</p>
                <p className="text-[10px] font-medium uppercase tracking-[0.2em] text-brand-200/80">
                  Smart gate management
                </p>
              </div>
            </div>

            <div className="mt-16 max-w-xl">
              <Badge tone="success" className="bg-brand-500/15 text-brand-200 ring-brand-400/20">
                <span className="h-1.5 w-1.5 rounded-full bg-brand-300 animate-pulse" />
                AI gate control · live
              </Badge>
              <h1 className="mt-5 text-4xl font-bold leading-[1.1] tracking-tight">
                Every vehicle.
                <br />
                Every face.
                <span className="text-brand-300"> One decision.</span>
              </h1>
              <p className="mt-4 max-w-md text-sm leading-relaxed text-ink-300">
                Plate recognition, resident face matching and permit validation fused into a
                single access decision — with a complete audit trail for every barrier movement.
              </p>
            </div>

            <div className="mt-10 grid max-w-lg grid-cols-2 gap-3">
              {HIGHLIGHTS.map((item) => (
                <div
                  key={item.title}
                  className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 backdrop-blur-sm"
                >
                  <Icon name={item.icon} className="h-4 w-4 text-brand-300" />
                  <p className="mt-2.5 text-xs font-semibold">{item.title}</p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-ink-400">{item.detail}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="relative mt-12 flex items-center gap-6 border-t border-white/10 pt-5 text-[11px] text-ink-400">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-brand-400" />
              Cairo · Africa/Cairo
            </span>
            <span>FastAPI · React 18</span>
            <span>GDPR-aware retention</span>
          </div>
        </section>

        <section className="flex items-center justify-center px-5 py-12 sm:px-10">
          <div className="w-full max-w-md">
            <div className="mb-8 flex items-center gap-2.5 lg:hidden">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white">
                <Icon name="gate" className="h-5 w-5" />
              </span>
              <div>
                <p className="text-base font-bold tracking-tight">GateVision</p>
                <p className="text-[10px] uppercase tracking-[0.2em] text-ink-400">Smart gate management</p>
              </div>
            </div>

            <h2 className="text-2xl font-bold tracking-tight text-ink-900 dark:text-white">
              {t("login.title")}
            </h2>
            <p className="mt-1.5 text-sm text-ink-500 dark:text-ink-400">{t("login.subtitle")}</p>

            <form onSubmit={(event) => void submit(event)} className="mt-7 space-y-4">
              <Input
                label={t("login.email")}
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@company.com"
              />
              <div>
                <div className="relative">
                  <Input
                    label={t("login.password")}
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="••••••••"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((current) => !current)}
                    className="absolute end-2 top-[30px] rounded-md px-2 py-1 text-[11px] font-semibold text-ink-400 hover:text-ink-700 dark:hover:text-ink-200"
                  >
                    {showPassword ? t("login.hide") : t("login.show")}
                  </button>
                </div>
              </div>

              {error ? (
                <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300">
                  <Icon name="alert" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <p>{error}</p>
                </div>
              ) : null}

              <Button type="submit" size="lg" className="w-full" loading={submitting} icon="shield">
                {submitting ? t("login.signing_in") : t("login.submit")}
              </Button>
            </form>

            <div className="mt-8">
              <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-ink-200 dark:bg-ink-800" />
                <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-400">
                  {t("login.demo")}
                </span>
                <div className="h-px flex-1 bg-ink-200 dark:bg-ink-800" />
              </div>
              <div className="mt-3 space-y-1.5">
                {DEMO_ACCOUNTS.map((account) => {
                  const active = account.email === email;
                  return (
                    <button
                      key={account.email}
                      type="button"
                      onClick={() => {
                        setEmail(account.email);
                        setPassword(account.password);
                        setError(null);
                      }}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-start transition",
                        active
                          ? "border-brand-300 bg-brand-50/70 dark:border-brand-700 dark:bg-brand-500/10"
                          : "border-ink-200 bg-white hover:border-ink-300 dark:border-ink-800 dark:bg-ink-900 dark:hover:border-ink-700",
                      )}
                    >
                      <span
                        className={cn(
                          "grid h-8 w-8 place-items-center rounded-lg text-[10px] font-bold",
                          active
                            ? "bg-brand-600 text-white"
                            : "bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-300",
                        )}
                      >
                        {account.role.slice(0, 2).toUpperCase()}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-semibold text-ink-900 dark:text-ink-100">
                          {account.role}
                        </p>
                        <p className="truncate text-[10px] text-ink-400">{account.description}</p>
                      </div>
                      <span className="text-[10px] text-ink-400">{t("login.use")}</span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-3 text-center text-[10px] text-ink-400">
                {t("login.demo_hint")}
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
