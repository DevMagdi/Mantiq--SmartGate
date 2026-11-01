import { Link } from "react-router-dom";

import { Icon } from "@/components/Icon";

export function NotFoundPage(): JSX.Element {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center text-center">
      <span className="grid h-16 w-16 place-items-center rounded-3xl bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300">
        <Icon name="gate" className="h-7 w-7" />
      </span>
      <p className="mt-5 text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-400">404</p>
      <h1 className="mt-1 text-2xl font-bold tracking-tight">This checkpoint does not exist</h1>
      <p className="mt-2 max-w-sm text-sm text-ink-500 dark:text-ink-400">
        The page you are looking for may have moved. Head back to the dashboard to continue.
      </p>
      <Link
        to="/"
        className="focus-ring mt-6 inline-flex h-10 items-center gap-2 rounded-xl bg-brand-600 px-4 text-sm font-semibold text-white transition hover:bg-brand-500"
      >
        <Icon name="dashboard" className="h-4 w-4" />
        Back to dashboard
      </Link>
    </div>
  );
}
