/**
 * End-to-end acceptance scenario for a *brand-new* install.
 *
 * The dashboard must be fully operable from a factory-fresh database
 * (`SEED_DEMO_DATA=false`): compound → gate → unit → resident → vehicle, with
 * no Swagger or curl. Because it mutates the database it is opt-in:
 *
 * ```bash
 * # 1. empty database + bootstrap admin only
 * rm -f /tmp/gv_fresh.db
 * DATABASE_URL="sqlite+aiosqlite:////tmp/gv_fresh.db" AUTO_CREATE_TABLES=true \
 *   SEED_DEMO_DATA=false CV_MODE=mock PYTHONPATH=. \
 *   .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
 * # 2. drive the UI against it
 * cd frontend && FRESH_INSTALL_E2E=1 npx vitest run src/test/fresh-install.flow.test.tsx
 * ```
 */
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "@/App";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/hooks/useAuth";
import { ThemeProvider } from "@/hooks/useTheme";
import { ToastProvider } from "@/hooks/useToast";
import { loginRequest } from "@/services/auth";
import { saveSession } from "@/services/tokenStore";

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

const SUFFIX = String(Date.now()).slice(-5);
const COMPOUND_NAME = `Palm Ridge ${SUFFIX}`;
const COMPOUND_CODE = `PR${SUFFIX}`;
const GATE_NAME = "Main entrance";
const GATE_CODE = `MAIN-${SUFFIX}`;
const UNIT_NUMBER = `30${SUFFIX.slice(-2)}`;
const RESIDENT_NAME = `Mariam Fathy ${SUFFIX}`;
const PLATE_DIGITS = SUFFIX.slice(-4);
const PLATE = `س ط ع ${PLATE_DIGITS}`;
const RESIDENT_EMAIL = `mariam${SUFFIX}@example.com`;

async function signIn(): Promise<void> {
  const pair = await loginRequest("admin@gatevision.app", "Admin@12345");
  saveSession(pair);
}

const ENABLED = process.env.FRESH_INSTALL_E2E === "1";

describe.skipIf(!ENABLED)("fresh install", () => {
  it("guides a brand-new install to Settings instead of dead forms", async () => {
    await signIn();
    renderAt("/registry");

    expect(
      await screen.findByText(/no compound yet/i, {}, { timeout: 20_000 }),
    ).toBeTruthy();
    // No dead forms are offered without a compound.
    expect(screen.queryByRole("tab", { name: /units/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /add unit/i })).toBeNull();

    screen.getByRole("button", { name: /open settings/i }).click();
    expect(await screen.findByRole("heading", { name: /^settings$/i }, { timeout: 20_000 })).toBeTruthy();
  }, 60_000);

  it("creates the compound from Settings → Account", async () => {
    await signIn();
    renderAt("/settings");

    expect(await screen.findByRole("heading", { name: /^settings$/i }, { timeout: 20_000 })).toBeTruthy();
    screen.getByRole("tab", { name: /account & compound/i }).click();

    const name = await screen.findByLabelText(/^compound$/i, {}, { timeout: 20_000 });
    fireEvent.change(name, { target: { value: COMPOUND_NAME } });
    fireEvent.change(screen.getByLabelText(/^code/i), { target: { value: COMPOUND_CODE } });

    screen.getByRole("button", { name: /^create compound$/i }).click();
    await waitFor(
      () => expect(screen.getByText(/compound created/i)).toBeTruthy(),
      { timeout: 20_000 },
    );
    expect(await screen.findByText(COMPOUND_CODE, {}, { timeout: 20_000 })).toBeTruthy();
  }, 60_000);

  it("creates a gate once the compound exists", async () => {
    await signIn();
    renderAt("/settings");

    expect(await screen.findByRole("heading", { name: /^settings$/i }, { timeout: 20_000 })).toBeTruthy();
    screen.getByRole("tab", { name: /^gates/i }).click();

    (await screen.findByRole("button", { name: /add gate/i }, { timeout: 20_000 })).click();
    fireEvent.change(await screen.findByLabelText(/^name/i), { target: { value: GATE_NAME } });
    fireEvent.change(screen.getByLabelText(/^code/i), { target: { value: GATE_CODE } });
    const createGate = (await screen.findByRole("button", {
      name: /create gate/i,
    })) as HTMLButtonElement;
    await waitFor(() => expect(createGate.disabled).toBe(false), { timeout: 20_000 });
    createGate.click();

    await waitFor(() => expect(screen.getByText(/gate created/i)).toBeTruthy(), { timeout: 20_000 });
    expect(await screen.findByText(GATE_CODE, {}, { timeout: 20_000 })).toBeTruthy();
  }, 60_000);

  it("shows the empty-units state and creates a unit from its CTA", async () => {
    await signIn();
    renderAt("/registry");

    (await screen.findByRole("tab", { name: /units/i }, { timeout: 20_000 })).click();

    // Empty database → the tab must offer a call to action, not a dead table.
    expect(await screen.findByText(/no units yet/i, {}, { timeout: 20_000 })).toBeTruthy();

    const addButtons = await screen.findAllByRole("button", { name: /add unit/i });
    addButtons[addButtons.length - 1].click();

    fireEvent.change(await screen.findByLabelText(/^building/i), { target: { value: "A" } });
    fireEvent.change(screen.getByLabelText(/^unit number/i), { target: { value: UNIT_NUMBER } });
    fireEvent.change(screen.getByLabelText(/^bedrooms/i), { target: { value: "3" } });
    const createUnit = (await screen.findByRole("button", {
      name: /create unit/i,
    })) as HTMLButtonElement;
    await waitFor(() => expect(createUnit.disabled).toBe(false), { timeout: 20_000 });
    createUnit.click();

    expect(
      await screen.findByText(`A-${UNIT_NUMBER}`, {}, { timeout: 20_000 }),
    ).toBeTruthy();
  }, 60_000);

  it("registers a resident against the new unit and a vehicle on the unit", async () => {
    await signIn();
    renderAt("/registry");

    await screen.findByRole("heading", { name: /residents & vehicles/i }, { timeout: 20_000 });
    const addResident = await screen.findAllByRole("button", {
      name: /add resident/i,
    });
    addResident[0].click();

    fireEvent.change(await screen.findByLabelText(/^full name/i), {
      target: { value: RESIDENT_NAME },
    });
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: RESIDENT_EMAIL } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "+20 100 111 2222" } });

    // The dropdown must already list the unit created a moment ago.
    const unitSelect = (await screen.findByLabelText(/^unit\b/i, {}, { timeout: 20_000 })) as HTMLSelectElement;
    const option = Array.from(unitSelect.options).find((item) => item.text.includes(UNIT_NUMBER));
    expect(option).toBeTruthy();
    fireEvent.change(unitSelect, { target: { value: option!.value } });

    const registerResident = (await screen.findByRole("button", {
      name: /register resident/i,
    })) as HTMLButtonElement;
    await waitFor(() => expect(registerResident.disabled).toBe(false), { timeout: 20_000 });
    registerResident.click();
    expect(await screen.findByText(RESIDENT_NAME, {}, { timeout: 20_000 })).toBeTruthy();

    // Add a vehicle to the freshly created resident.
    const residentRow = screen.getByText(RESIDENT_NAME).closest("tr") as HTMLElement;
    within(residentRow).getByLabelText(/^add vehicle$/i).click();
    fireEvent.change(await screen.findByLabelText(/^plate number/i), { target: { value: PLATE } });
    screen.getByRole("button", { name: /register vehicle/i }).click();

    (await screen.findByRole("tab", { name: /vehicles/i }, { timeout: 20_000 })).click();
    // The API canonicalises Egyptian plates (letters are joined, digits kept).
    expect(
      await screen.findByText(new RegExp(PLATE_DIGITS), {}, { timeout: 20_000 }),
    ).toBeTruthy();
  }, 90_000);
});
