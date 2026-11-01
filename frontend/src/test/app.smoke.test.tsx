import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "@/App";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/hooks/useAuth";
import { ThemeProvider } from "@/hooks/useTheme";
import { ToastProvider } from "@/hooks/useToast";
import { loginRequest } from "@/services/auth";
import { saveSession } from "@/services/tokenStore";
import type { UserRole } from "@/types/models";

const ACCOUNTS: Record<UserRole, { email: string; password: string }> = {
  admin: { email: "admin@gatevision.app", password: "Admin@12345" },
  security_officer: { email: "officer@gatevision.app", password: "Officer@12345" },
  resident: { email: "ahmed@gatevision.app", password: "Resident@12345" },
};

async function signIn(role: UserRole): Promise<void> {
  const pair = await loginRequest(ACCOUNTS[role].email, ACCOUNTS[role].password);
  saveSession(pair);
}

function Providers({ children }: { children: ReactNode }): JSX.Element {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  return (
    <ThemeProvider>
      <I18nProvider>
        <QueryClientProvider client={client}>
          <AuthProvider>
            <ToastProvider>{children}</ToastProvider>
          </AuthProvider>
        </QueryClientProvider>
      </I18nProvider>
    </ThemeProvider>
  );
}

function renderAt(route: string): void {
  render(
    <Providers>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </Providers>,
  );
}

describe("GateVision dashboard", () => {
  it("signs in through the real API and lands on the analytics dashboard", async () => {
    renderAt("/login");

    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeTruthy();
    const email = screen.getByLabelText(/email address/i) as HTMLInputElement;
    const password = screen.getByLabelText(/^password/i) as HTMLInputElement;
    expect(email.value).toBe("admin@gatevision.app");
    expect(password.value).toBe("Admin@12345");

    screen.getByRole("button", { name: /^sign in$/i }).click();

    expect(
      await screen.findByRole("heading", { name: /compound overview/i }, { timeout: 20_000 }),
    ).toBeTruthy();
    expect(await screen.findByText(/entries today/i)).toBeTruthy();
    expect(await screen.findByText(/gate performance/i)).toBeTruthy();
  });

  it("renders the live gate monitor with the detection stream and barrier controls", async () => {
    await signIn("security_officer");
    renderAt("/live");

    expect(
      await screen.findByRole("heading", { name: /live gate monitor/i }, { timeout: 20_000 }),
    ).toBeTruthy();
    expect(await screen.findByText(/detection stream/i)).toBeTruthy();
    expect(await screen.findByText(/barrier control/i)).toBeTruthy();
    expect(await screen.findByText(/manual review queue/i)).toBeTruthy();
    expect(screen.getByText(/analyse an image/i)).toBeTruthy();
  });

  it("lists the seeded residents for an administrator", async () => {
    await signIn("admin");
    renderAt("/registry");

    expect(
      await screen.findByRole("heading", { name: /residents & vehicles/i }, { timeout: 20_000 }),
    ).toBeTruthy();
    expect(await screen.findByText("Yasmine Saad", {}, { timeout: 20_000 })).toBeTruthy();
    expect(screen.getByText("Ahmed Hassan")).toBeTruthy();
    expect(screen.getByRole("tab", { name: /vehicles/i })).toBeTruthy();
  });

  it("shows visitors and temporary permits", async () => {
    await signIn("admin");
    renderAt("/visitors");

    expect(
      await screen.findByRole("heading", { name: /visitors & permits/i }, { timeout: 20_000 }),
    ).toBeTruthy();
    expect(await screen.findByText("Youssef Adel", {}, { timeout: 20_000 })).toBeTruthy();

    screen.getByRole("tab", { name: /permits/i }).click();
    expect((await screen.findAllByText(/PMT-/, {}, { timeout: 20_000 })).length).toBeGreaterThan(0);
  });

  it("renders the access log audit trail with rows from the API", async () => {
    await signIn("admin");
    const { container } = render(
      <Providers>
        <MemoryRouter initialEntries={["/logs"]}>
          <App />
        </MemoryRouter>
      </Providers>,
    );

    expect(
      await screen.findByRole("heading", { name: /access logs/i }, { timeout: 20_000 }),
    ).toBeTruthy();
    await waitFor(
      () => {
        expect(container.querySelectorAll("tbody tr").length).toBeGreaterThan(0);
      },
      { timeout: 20_000 },
    );
    expect(screen.getByRole("button", { name: /^csv$/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^excel$/i })).toBeTruthy();
  });

  it("renders the blacklist and biometric gallery", async () => {
    await signIn("admin");
    renderAt("/security");

    expect(
      await screen.findByRole("heading", { name: /blacklist & face recognition/i }, {
        timeout: 20_000,
      }),
    ).toBeTruthy();
    expect(await screen.findByText("Zaki Mahmoud", {}, { timeout: 20_000 })).toBeTruthy();
    expect(screen.getByText(/face embeddings/i)).toBeTruthy();

    screen.getByRole("tab", { name: /face gallery/i }).click();
    expect(await screen.findByText("Yasmine Saad", {}, { timeout: 20_000 })).toBeTruthy();
  });

  it("lets an administrator manage gates, cameras and staff", async () => {
    await signIn("admin");
    renderAt("/settings");

    expect(
      await screen.findByRole("heading", { name: /^settings$/i }, { timeout: 20_000 }),
    ).toBeTruthy();
    expect(await screen.findByText("GATE-IN", {}, { timeout: 20_000 })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /users/i })).toBeTruthy();
  });

  it("hides the staff directory from security officers", async () => {
    await signIn("security_officer");
    renderAt("/settings");

    expect(
      await screen.findByRole("heading", { name: /^settings$/i }, { timeout: 20_000 }),
    ).toBeTruthy();
    expect(await screen.findByRole("tab", { name: /gates/i })).toBeTruthy();
    expect(screen.queryByRole("tab", { name: /users/i })).toBeNull();
  });

  it("scopes the resident experience to their household", async () => {
    await signIn("resident");
    renderAt("/registry");

    const nav = await screen.findByRole("navigation");
    expect(within(nav).getByText(/my household/i)).toBeTruthy();
    expect(within(nav).queryByText(/live gate monitor/i)).toBeNull();
    expect(
      await screen.findByRole("heading", { name: /my household/i }, { timeout: 20_000 }),
    ).toBeTruthy();
    expect(await screen.findByText(/my vehicles/i, {}, { timeout: 20_000 })).toBeTruthy();
  });
});
