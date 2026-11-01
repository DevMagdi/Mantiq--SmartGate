import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { I18nProvider, useI18n } from "@/i18n";
import { TRANSLATIONS } from "@/i18n/translations";
import { AuthProvider } from "@/hooks/useAuth";
import { ThemeProvider } from "@/hooks/useTheme";
import { ToastProvider } from "@/hooks/useToast";
import { LoginPage } from "@/pages/Login";

function Providers({ children }: { children: ReactNode }): JSX.Element {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return (
    <ThemeProvider>
      <I18nProvider>
        <QueryClientProvider client={client}>
          <AuthProvider>
            <ToastProvider>
              <MemoryRouter initialEntries={["/login"]}>{children}</MemoryRouter>
            </ToastProvider>
          </AuthProvider>
        </QueryClientProvider>
      </I18nProvider>
    </ThemeProvider>
  );
}

function Probe(): JSX.Element {
  const { locale, dir, t } = useI18n();
  return (
    <p data-testid="probe">
      {locale}|{dir}|{t("nav.live")}
    </p>
  );
}

describe("Arabic / RTL support", () => {
  it("keeps the English and Arabic catalogues in sync", () => {
    const english = Object.keys(TRANSLATIONS.en).sort();
    const arabic = Object.keys(TRANSLATIONS.ar).sort();
    expect(arabic).toEqual(english);
    for (const [key, value] of Object.entries(TRANSLATIONS.ar)) {
      expect(value.trim(), `empty Arabic translation for ${key}`).not.toBe("");
    }
  });

  it("switches the document direction and translates the login page", async () => {
    render(
      <Providers>
        <LoginPage />
      </Providers>,
    );

    expect(await screen.findByRole("heading", { name: /sign in to your workspace/i })).toBeTruthy();
    expect(document.documentElement.dir).toBe("ltr");

    fireEvent.click(screen.getByRole("button", { name: /التبديل إلى العربية/i }));

    await waitFor(() => expect(document.documentElement.dir).toBe("rtl"));
    expect(document.documentElement.lang).toBe("ar");
    expect(
      await screen.findByRole("heading", { name: /تسجيل الدخول إلى مساحة العمل/i }),
    ).toBeTruthy();
    expect(screen.getByLabelText(/البريد الإلكتروني/i)).toBeTruthy();
    expect(localStorage.getItem("gatevision.locale")).toBe("ar");
  });

  it("falls back to English and exposes translations outside the provider", () => {
    render(<Probe />);
    expect(screen.getByTestId("probe").textContent).toBe("en|ltr|Live gate monitor");
  });
});
