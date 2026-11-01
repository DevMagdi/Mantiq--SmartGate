/** Small formatting helpers shared by every page. */

const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const TIME_ONLY = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const DATE_ONLY = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | Date | null | undefined): string {
  const date = toDate(value);
  return date ? DATE_TIME.format(date) : "—";
}

export function formatTime(value: string | Date | null | undefined): string {
  const date = toDate(value);
  return date ? TIME_ONLY.format(date) : "—";
}

export function formatDate(value: string | Date | null | undefined): string {
  const date = toDate(value);
  return date ? DATE_ONLY.format(date) : "—";
}

export function relativeTime(value: string | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return "—";
  const diff = Math.round((date.getTime() - Date.now()) / 1000);
  const absolute = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (absolute < 60) return rtf.format(diff, "second");
  if (absolute < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (absolute < 86_400) return rtf.format(Math.round(diff / 3600), "hour");
  return rtf.format(Math.round(diff / 86_400), "day");
}

export function toDateTimeLocal(value: Date = new Date()): string {
  const offset = value.getTimezoneOffset();
  return new Date(value.getTime() - offset * 60_000).toISOString().slice(0, 16);
}

export function plusHours(hours: number, from: Date = new Date()): string {
  return toDateTimeLocal(new Date(from.getTime() + hours * 3_600_000));
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function initials(name: string | null | undefined): string {
  if (!name) return "??";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-GB").format(value);
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "—";
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
