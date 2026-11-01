import clsx from "clsx";
import {
  forwardRef,
  useEffect,
  useId,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { Icon, type IconName } from "@/components/Icon";
import type { Tone } from "@/utils/constants";

export function cn(...values: Array<string | false | null | undefined>): string {
  return clsx(values);
}

/* ------------------------------------------------------------------ button */

type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger" | "subtle";
type ButtonSize = "sm" | "md" | "lg" | "icon";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-brand-600 text-white shadow-sm hover:bg-brand-500 active:bg-brand-700 disabled:bg-brand-600/50",
  secondary:
    "bg-ink-900 text-white hover:bg-ink-800 dark:bg-ink-100 dark:text-ink-900 dark:hover:bg-white",
  outline:
    "border border-ink-200 bg-white text-ink-700 hover:border-ink-300 hover:bg-ink-50 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-200 dark:hover:bg-ink-800",
  ghost:
    "text-ink-600 hover:bg-ink-100 hover:text-ink-900 dark:text-ink-300 dark:hover:bg-ink-800 dark:hover:text-white",
  danger: "bg-rose-600 text-white shadow-sm hover:bg-rose-500 active:bg-rose-700",
  subtle:
    "bg-brand-50 text-brand-700 hover:bg-brand-100 dark:bg-brand-500/10 dark:text-brand-300 dark:hover:bg-brand-500/20",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-lg px-2.5 text-xs",
  md: "h-10 gap-2 rounded-xl px-4 text-sm",
  lg: "h-11 gap-2 rounded-xl px-5 text-sm",
  icon: "h-9 w-9 rounded-lg",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: IconName;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  ...props
}: ButtonProps): JSX.Element {
  return (
    <button
      type={props.type ?? "button"}
      disabled={disabled || loading}
      className={cn(
        "focus-ring inline-flex items-center justify-center font-semibold transition disabled:cursor-not-allowed disabled:opacity-70",
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...props}
    >
      {loading ? <Spinner className="h-4 w-4" /> : icon ? <Icon name={icon} className="h-4 w-4" /> : null}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------- badge */

const TONE_STYLES: Record<Tone, string> = {
  success: "bg-brand-50 text-brand-700 ring-brand-600/15 dark:bg-brand-500/10 dark:text-brand-300",
  danger: "bg-rose-50 text-rose-700 ring-rose-600/15 dark:bg-rose-500/10 dark:text-rose-300",
  warning: "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-300",
  info: "bg-sky-50 text-sky-700 ring-sky-600/15 dark:bg-sky-500/10 dark:text-sky-300",
  brand: "bg-brand-600 text-white ring-brand-600/20",
  neutral: "bg-ink-100 text-ink-600 ring-ink-500/15 dark:bg-ink-800 dark:text-ink-300",
};

const TONE_DOTS: Record<Tone, string> = {
  success: "bg-brand-500",
  danger: "bg-rose-500",
  warning: "bg-amber-500",
  info: "bg-sky-500",
  brand: "bg-white",
  neutral: "bg-ink-400",
};

export function Badge({
  tone = "neutral",
  children,
  dot = false,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  dot?: boolean;
  className?: string;
}): JSX.Element {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset",
        TONE_STYLES[tone],
        className,
      )}
    >
      {dot ? <span className={cn("h-1.5 w-1.5 rounded-full", TONE_DOTS[tone])} /> : null}
      {children}
    </span>
  );
}

/* -------------------------------------------------------------------- card */

export function Card({
  children,
  className,
  muted = false,
}: {
  children: ReactNode;
  className?: string;
  muted?: boolean;
}): JSX.Element {
  return <div className={cn(muted ? "surface-muted" : "surface", className)}>{children}</div>;
}

export function CardHeader({
  title,
  subtitle,
  actions,
  icon,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  icon?: IconName;
}): JSX.Element {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-ink-100 px-5 py-4 dark:border-ink-800">
      <div className="flex min-w-0 items-start gap-3">
        {icon ? (
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300">
            <Icon name={icon} className="h-4 w-4" />
          </span>
        ) : null}
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-ink-900 dark:text-ink-100">{title}</h2>
          {subtitle ? (
            <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ fields */

const FIELD_BASE =
  "focus-ring w-full rounded-xl border border-ink-200 bg-white px-3 text-sm text-ink-900 placeholder:text-ink-400 transition hover:border-ink-300 dark:border-ink-700 dark:bg-ink-950 dark:text-ink-100 dark:placeholder:text-ink-500 dark:hover:border-ink-600";

export interface FieldProps {
  label?: string;
  hint?: string;
  error?: string;
  required?: boolean;
  className?: string;
  htmlFor?: string;
}

export function Field({
  label,
  hint,
  error,
  required,
  children,
  className,
  htmlFor,
}: FieldProps & { children: ReactNode }): JSX.Element {
  return (
    <div className={className}>
      {label ? (
        <label className="field-label" htmlFor={htmlFor}>
          {label}
          {required ? <span className="ml-1 text-rose-500">*</span> : null}
        </label>
      ) : null}
      {children}
      {error ? <p className="mt-1 text-xs font-medium text-rose-600 dark:text-rose-400">{error}</p> : null}
      {!error && hint ? <p className="mt-1 text-xs text-ink-400">{hint}</p> : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & FieldProps>(
  function Input({ label, hint, error, required, className, id, ...props }, ref) {
    const generatedId = useId();
    const inputId = id ?? generatedId;
    return (
      <Field label={label} hint={hint} error={error} required={required} className={className} htmlFor={inputId}>
        <input
          ref={ref}
          id={inputId}
          required={required}
          aria-invalid={error ? true : undefined}
          className={cn(FIELD_BASE, "h-10", error && "border-rose-400")}
          {...props}
        />
      </Field>
    );
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement> & FieldProps
>(function Textarea({ label, hint, error, required, className, id, ...props }, ref) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  return (
    <Field label={label} hint={hint} error={error} required={required} className={className} htmlFor={fieldId}>
      <textarea
        ref={ref}
        id={fieldId}
        required={required}
        aria-invalid={error ? true : undefined}
        className={cn(FIELD_BASE, "min-h-[88px] py-2.5", error && "border-rose-400")}
        {...props}
      />
    </Field>
  );
});

export function Select({
  label,
  hint,
  error,
  required,
  className,
  children,
  id,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & FieldProps): JSX.Element {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  return (
    <Field label={label} hint={hint} error={error} required={required} className={className} htmlFor={fieldId}>
      <select
        id={fieldId}
        required={required}
        aria-invalid={error ? true : undefined}
        className={cn(FIELD_BASE, "h-10 pr-8", error && "border-rose-400")}
        {...props}
      >
        {children}
      </select>
    </Field>
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}): JSX.Element {
  return (
    <div className={cn("relative", className)}>
      <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={cn(FIELD_BASE, "h-10 pl-9 pr-8")}
        aria-label={placeholder}
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-ink-400 hover:bg-ink-100 dark:hover:bg-ink-800"
          aria-label="Clear search"
        >
          <Icon name="close" className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------- modal */

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}): JSX.Element | null {
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;

  const width = {
    sm: "max-w-md",
    md: "max-w-xl",
    lg: "max-w-3xl",
    xl: "max-w-5xl",
  }[size];

  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center p-4 sm:items-center">
      <div
        className="absolute inset-0 bg-ink-950/55 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cn(
          "relative flex max-h-[90vh] w-full flex-col overflow-hidden rounded-2xl border border-ink-200 bg-white shadow-2xl animate-fade-in dark:border-ink-800 dark:bg-ink-900",
          width,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-ink-100 px-5 py-4 dark:border-ink-800">
          <div>
            <h2 id={titleId} className="text-base font-semibold">
              {title}
            </h2>
            {description ? (
              <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">{description}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-ink-400 transition hover:bg-ink-100 hover:text-ink-600 dark:hover:bg-ink-800"
            aria-label="Close dialog"
          >
            <Icon name="close" className="h-4 w-4" />
          </button>
        </div>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
        {footer ? (
          <div className="flex justify-end gap-2 border-t border-ink-100 bg-ink-50/60 px-5 py-3 dark:border-ink-800 dark:bg-ink-950/40">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm",
  loading = false,
  danger = true,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  loading?: boolean;
  danger?: boolean;
}): JSX.Element {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-sm leading-relaxed text-ink-600 dark:text-ink-300">
        {description ?? "This action cannot be undone."}
      </p>
    </Modal>
  );
}

/* ------------------------------------------------------------------ tables */

export function TableShell({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-sm">{children}</table>
    </div>
  );
}

export function Th({
  children,
  className,
  align = "left",
}: {
  children?: ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
}): JSX.Element {
  return (
    <th
      scope="col"
      className={cn(
        "table-head whitespace-nowrap border-b border-ink-100 px-4 py-2.5 font-semibold dark:border-ink-800",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  className,
  align = "left",
  colSpan,
}: {
  children?: ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
  colSpan?: number;
}): JSX.Element {
  return (
    <td
      colSpan={colSpan}
      className={cn(
        "border-b border-ink-50 px-4 py-3 align-middle text-ink-600 last:border-0 dark:border-ink-800/60 dark:text-ink-300",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function EmptyState({
  icon = "search",
  title,
  description,
  action,
}: {
  icon?: IconName;
  title: string;
  description?: string;
  action?: ReactNode;
}): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <span className="grid h-12 w-12 place-items-center rounded-2xl bg-ink-100 text-ink-400 dark:bg-ink-800 dark:text-ink-500">
        <Icon name={icon} className="h-5 w-5" />
      </span>
      <p className="mt-1 text-sm font-semibold text-ink-800 dark:text-ink-200">{title}</p>
      {description ? (
        <p className="max-w-sm text-xs leading-relaxed text-ink-500 dark:text-ink-400">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function Spinner({ className = "h-5 w-5" }: { className?: string }): JSX.Element {
  return (
    <svg className={cn("animate-spin text-current", className)} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.22" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function LoadingBlock({ label = "Loading…" }: { label?: string }): JSX.Element {
  return (
    <div className="flex items-center justify-center gap-2 py-14 text-sm text-ink-500 dark:text-ink-400">
      <Spinner className="h-4 w-4" />
      {label}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }): JSX.Element {
  return <div className={cn("animate-pulse rounded-lg bg-ink-100 dark:bg-ink-800", className)} />;
}

/* -------------------------------------------------------------- pagination */

export function Pagination({
  page,
  pages,
  total,
  pageSize,
  onPageChange,
  onPageSizeChange,
}: {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
}): JSX.Element {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink-100 px-4 py-3 text-xs text-ink-500 dark:border-ink-800 dark:text-ink-400">
      <div className="flex items-center gap-2">
        <span>
          {total === 0 ? "No results" : `Page ${page} of ${Math.max(pages, 1)}`} · {total} record
          {total === 1 ? "" : "s"}
        </span>
        {onPageSizeChange ? (
          <select
            value={pageSize}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
            className="rounded-md border border-ink-200 bg-transparent px-1.5 py-1 text-xs dark:border-ink-700"
            aria-label="Rows per page"
          >
            {[10, 25, 50, 100].map((size) => (
              <option key={size} value={size}>
                {size} / page
              </option>
            ))}
          </select>
        ) : null}
      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          <Icon name="chevron-left" className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pages}
          aria-label="Next page"
        >
          <Icon name="chevron-right" className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- tabs */

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  className,
}: {
  tabs: { key: T; label: string; count?: number }[];
  value: T;
  onChange: (key: T) => void;
  className?: string;
}): JSX.Element {
  return (
    <div
      role="tablist"
      className={cn("flex flex-wrap gap-1 rounded-xl bg-ink-100/80 p-1 dark:bg-ink-900", className)}
    >
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={value === tab.key}
          onClick={() => onChange(tab.key)}
          className={cn(
            "focus-ring flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold transition",
            value === tab.key
              ? "bg-white text-ink-900 shadow-sm dark:bg-ink-800 dark:text-white"
              : "text-ink-500 hover:text-ink-800 dark:text-ink-400 dark:hover:text-ink-200",
          )}
        >
          {tab.label}
          {tab.count !== undefined ? (
            <span className="rounded-full bg-ink-100 px-1.5 py-0.5 text-[10px] font-bold text-ink-500 dark:bg-ink-700 dark:text-ink-300">
              {tab.count}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------- misc */

export function SectionTitle({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}): JSX.Element {
  return (
    <div className="mb-3 flex items-end justify-between gap-3">
      <div>
        <h2 className="text-sm font-semibold text-ink-900 dark:text-ink-100">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}
