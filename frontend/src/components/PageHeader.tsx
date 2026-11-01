import type { ReactNode } from "react";

export function PageHeader({
  title,
  subtitle,
  actions,
  eyebrow,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  eyebrow?: string;
}): JSX.Element {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        {eyebrow ? (
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-brand-600 dark:text-brand-400">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="mt-1 text-xl font-bold tracking-tight text-ink-900 sm:text-2xl dark:text-white">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-500 dark:text-ink-400">
            {subtitle}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
