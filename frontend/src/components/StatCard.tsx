import { Icon, type IconName } from "@/components/Icon";
import { Skeleton } from "@/components/ui";
import { cn } from "@/components/ui";
import type { Tone } from "@/utils/constants";

const TONE_STYLES: Record<Tone, string> = {
  success: "bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300",
  danger: "bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300",
  warning: "bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300",
  info: "bg-sky-50 text-sky-600 dark:bg-sky-500/10 dark:text-sky-300",
  neutral: "bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-300",
  brand: "bg-brand-600 text-white",
};

export function StatCard({
  label,
  value,
  hint,
  icon,
  tone = "brand",
  trend,
  loading = false,
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon: IconName;
  tone?: Tone;
  trend?: number | null;
  loading?: boolean;
}): JSX.Element {
  if (loading) {
    return (
      <div className="surface p-4">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-7 w-16" />
        <Skeleton className="mt-3 h-3 w-32" />
      </div>
    );
  }

  return (
    <div className="surface group p-4 transition hover:-translate-y-0.5 hover:border-brand-200 dark:hover:border-brand-900">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
          {label}
        </p>
        <span className={cn("grid h-9 w-9 place-items-center rounded-xl", TONE_STYLES[tone])}>
          <Icon name={icon} className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-2 flex items-end gap-2">
        <p className="text-2xl font-bold tracking-tight text-ink-900 dark:text-white">{value}</p>
        {trend !== undefined && trend !== null ? (
          <span
            className={cn(
              "mb-1 inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold",
              trend >= 0
                ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300"
                : "bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-300",
            )}
          >
            {trend >= 0 ? "↑" : "↓"} {Math.abs(trend).toFixed(0)}%
          </span>
        ) : null}
      </div>
      {hint ? (
        <p className="mt-2 truncate text-[11px] text-ink-400 dark:text-ink-500">{hint}</p>
      ) : null}
    </div>
  );
}
