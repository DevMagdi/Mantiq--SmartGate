/**
 * Lightweight i18n provider with right-to-left support.
 *
 * - The locale is persisted in ``localStorage`` and mirrored on
 *   ``<html lang dir>`` so every Tailwind logical utility (ps/pe/start/end)
 *   and the browser's own bidi handling follow it.
 * - ``useI18n`` degrades gracefully: components rendered outside the provider
 *   (unit tests, storybook) get English strings instead of throwing.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  AR_REASON_LABELS,
  LOCALE_META,
  TRANSLATIONS,
  type Locale,
  type TranslationKey,
} from "./translations";

const STORAGE_KEY = "gatevision.locale";

type Interpolations = Record<string, string | number>;

interface I18nValue {
  locale: Locale;
  dir: "ltr" | "rtl";
  isRtl: boolean;
  intlLocale: string;
  setLocale: (locale: Locale) => void;
  toggleLocale: () => void;
  t: (key: TranslationKey | string, vars?: Interpolations) => string;
  /** Translate a decision reason code with an English fallback. */
  reason: (code: string | null | undefined, fallback?: string) => string;
  formatDateTime: (value: string | Date | null | undefined) => string;
  formatNumber: (value: number | null | undefined) => string;
}

const DEFAULT_VALUE: I18nValue = {
  locale: "en",
  dir: "ltr",
  isRtl: false,
  intlLocale: LOCALE_META.en.intl,
  setLocale: () => undefined,
  toggleLocale: () => undefined,
  t: (key) => String(TRANSLATIONS.en[key as TranslationKey] ?? key),
  reason: (code, fallback) => fallback ?? code ?? "—",
  formatDateTime: (value) => (value ? new Date(value).toLocaleString("en-GB") : "—"),
  formatNumber: (value) =>
    value === null || value === undefined ? "—" : new Intl.NumberFormat("en-GB").format(value),
};

const I18nContext = createContext<I18nValue>(DEFAULT_VALUE);

function readStoredLocale(): Locale {
  if (typeof window === "undefined") return "en";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "ar" || stored === "en") return stored;
  } catch {
    // Storage can be blocked (private mode / embedded webviews): default to en.
  }
  return "en";
}

export function I18nProvider({ children }: { children: ReactNode }): JSX.Element {
  const [locale, setLocaleState] = useState<Locale>(readStoredLocale);

  useEffect(() => {
    const meta = LOCALE_META[locale];
    document.documentElement.lang = locale;
    document.documentElement.dir = meta.dir;
    document.documentElement.dataset.locale = locale;
    try {
      window.localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      // Ignore storage failures; the in-memory locale still applies.
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => setLocaleState(next), []);
  const toggleLocale = useCallback(
    () => setLocaleState((current) => (current === "ar" ? "en" : "ar")),
    [],
  );

  const value = useMemo<I18nValue>(() => {
    const dictionary = TRANSLATIONS[locale];
    const meta = LOCALE_META[locale];
    const t = (key: TranslationKey | string, vars?: Interpolations): string => {
      const template =
        dictionary[key as TranslationKey] ??
        TRANSLATIONS.en[key as TranslationKey] ??
        String(key);
      if (!vars) return template;
      return template.replace(/\{(\w+)\}/g, (match, name: string) =>
        name in vars ? String(vars[name]) : match,
      );
    };
    const reasonLabel = (code: string | null | undefined, fallback?: string): string => {
      if (!code) return fallback ?? "—";
      if (locale === "ar") {
        return AR_REASON_LABELS[code] ?? fallback ?? code.replace(/_/g, " ");
      }
      return fallback ?? code.replace(/_/g, " ");
    };
    return {
      locale,
      dir: meta.dir,
      isRtl: meta.dir === "rtl",
      intlLocale: meta.intl,
      setLocale,
      toggleLocale,
      t,
      reason: reasonLabel,
      formatDateTime: (input) => {
        if (!input) return "—";
        const date = input instanceof Date ? input : new Date(input);
        if (Number.isNaN(date.getTime())) return "—";
        return new Intl.DateTimeFormat(meta.intl, {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).format(date);
      },
      formatNumber: (input) =>
        input === null || input === undefined
          ? "—"
          : new Intl.NumberFormat(meta.intl).format(input),
    };
  }, [locale, setLocale, toggleLocale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  return useContext(I18nContext);
}

export { LOCALE_META, TRANSLATIONS };
export type { I18nValue, Locale, TranslationKey };
