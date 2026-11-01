import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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

  it("creates, edits and deletes a unit from the registry", async () => {
    await signIn("admin");
    renderAt("/registry");

    expect(
      await screen.findByRole("heading", { name: /residents & vehicles/i }, { timeout: 20_000 }),
    ).toBeTruthy();

    // Tabs render once the compound is loaded.
    (await screen.findByRole("tab", { name: /units/i }, { timeout: 20_000 })).click();
    // Seeded units prove the tab reads from the API, not a hardcoded list.
    expect(await screen.findByText("A-101", {}, { timeout: 20_000 })).toBeTruthy();

    // A per-run label keeps repeat runs against the shared demo database green.
    const suffix = String(Date.now()).slice(-6);
    const building = `Z9`;
    const unitNumber = suffix;
    const label = `${building}-${unitNumber}`;

    screen.getByRole("button", { name: /add unit/i }).click();
    fireEvent.change(await screen.findByLabelText(/^building/i), { target: { value: building } });
    fireEvent.change(screen.getByLabelText(/^unit number/i), { target: { value: unitNumber } });
    fireEvent.change(screen.getByLabelText(/^bedrooms/i), { target: { value: "2" } });
    screen.getByRole("button", { name: /create unit/i }).click();

    const created = await screen.findByText(label, {}, { timeout: 20_000 });
    const row = created.closest("tr");
    expect(row).toBeTruthy();

    // The mutation stays pending until its invalidation refetch settles, so wait
    // for the save button to become interactive before typing.
    within(row as HTMLElement).getByLabelText(/edit unit/i).click();
    const saveButton = (await screen.findByRole("button", {
      name: /save changes/i,
    })) as HTMLButtonElement;
    await waitFor(() => expect(saveButton.disabled).toBe(false), { timeout: 20_000 });

    fireEvent.change(screen.getByLabelText(/^bedrooms/i), { target: { value: "4" } });
    saveButton.click();

    // Re-query the row: the table re-renders after the invalidation refetch.
    await waitFor(
      () => {
        const refreshed = screen.getByText(label).closest("tr") as HTMLElement;
        expect(within(refreshed).getByText("4")).toBeTruthy();
      },
      { timeout: 20_000 },
    );

    const refreshedRow = screen.getByText(label).closest("tr") as HTMLElement;
    within(refreshedRow).getByLabelText(/delete unit/i).click();
    const dialog = await screen.findByRole("dialog");
    within(dialog).getByRole("button", { name: /^delete unit$/i }).click();
    await waitFor(() => expect(screen.queryByText(label)).toBeNull(), { timeout: 20_000 });
  });

  it("refuses to delete a unit that still has residents", async () => {
    await signIn("admin");
    renderAt("/registry");

    (await screen.findByRole("tab", { name: /units/i }, { timeout: 20_000 })).click();
    const label = await screen.findByText("A-101", {}, { timeout: 20_000 });
    const row = label.closest("tr") as HTMLElement;

    within(row).getByLabelText(/delete unit/i).click();
    const dialog = await screen.findByRole("dialog");
    within(dialog).getByRole("button", { name: /^delete unit$/i }).click();

    // Only the RESTRICT error copy mentions re-assigning the residents.
    expect(
      await screen.findByText(/move or remove them before deleting/i, {}, { timeout: 20_000 }),
    ).toBeTruthy();
    expect(screen.getByText("A-101")).toBeTruthy();
  });

  it("edits the compound barrier driver and thresholds", async () => {
    await signIn("admin");
    renderAt("/settings");

    expect(
      await screen.findByRole("heading", { name: /^settings$/i }, { timeout: 20_000 }),
    ).toBeTruthy();
    screen.getByRole("tab", { name: /policy & barrier/i }).click();

    expect(await screen.findByText(/compound policy/i, {}, { timeout: 20_000 })).toBeTruthy();
    const driver = (await screen.findByLabelText(/^driver/i)) as HTMLSelectElement;
    // Toggle to a different transport so the form is dirty on every run.
    const original = driver.value;
    const next = original === "webhook" ? "simulator" : "webhook";
    fireEvent.change(driver, { target: { value: next } });

    if (next === "webhook") {
      fireEvent.change(await screen.findByLabelText(/controller url/i), {
        target: { value: "https://barrier.test/open" },
      });
    }
    screen.getByRole("button", { name: /save policy/i }).click();
    await waitFor(
      () => expect(screen.getByText(/policy saved/i)).toBeTruthy(),
      { timeout: 20_000 },
    );

    // Restore the previous driver so the shared demo database stays predictable.
    fireEvent.change(screen.getByLabelText(/^driver/i), { target: { value: original } });
    screen.getByRole("button", { name: /save policy/i }).click();
    await waitFor(
      () => expect((screen.getByLabelText(/^driver/i) as HTMLSelectElement).value).toBe(original),
      { timeout: 20_000 },
    );
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

  it("shows the camera fleet with a stream test and the vision status panel", async () => {
    await signIn("admin");
    renderAt("/settings");

    await screen.findByRole("heading", { name: /^settings$/i }, { timeout: 20_000 });
    // Cameras tab: vision/real-mode panel, camera rows and the per-stream test button.
    const camerasTab = await screen.findByRole("tab", { name: /cameras/i });
    camerasTab.click();

    expect(await screen.findByText("Entry Lane Camera", {}, { timeout: 20_000 })).toBeTruthy();
    expect(screen.getByText(/vision & barrier configuration/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /^test$/i }).length).toBeGreaterThan(0);
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

  it("previews a camera snapshot over the authenticated endpoint", async () => {
    await signIn("admin");
    renderAt("/settings");

    await screen.findByRole("heading", { name: /^settings$/i }, { timeout: 20_000 });
    (await screen.findByRole("tab", { name: /cameras/i })).click();
    const cameraName = await screen.findByText("Entry Lane Camera", {}, { timeout: 20_000 });
    const row = cameraName.closest("tr");
    expect(row).toBeTruthy();
    within(row as HTMLElement).getByRole("button", { name: /^snapshot$/i }).click();

    // The seeded demo cameras have no live frame: the modal must explain the
    // backend reason instead of showing a broken <img>.
    expect(
      await screen.findByText(/could not read a snapshot/i, {}, { timeout: 20_000 }),
    ).toBeTruthy();
    expect(await screen.findByText(/no live snapshot/i, {}, { timeout: 20_000 })).toBeTruthy();
  });

  it("screens an enrollment photo through the quality-check endpoint", async () => {
    await signIn("admin");
    renderAt("/security");

    await screen.findByRole("heading", { name: /blacklist & face recognition/i }, {
      timeout: 20_000,
    });
    (await screen.findByRole("button", { name: /enroll face/i })).click();

    await screen.findByLabelText(/^resident/i, {}, { timeout: 20_000 });
    await waitFor(
      () => {
        const select = screen.getByLabelText(/^resident/i) as HTMLSelectElement;
        expect(select.options.length).toBeGreaterThan(1);
      },
      { timeout: 20_000 },
    );
    const residentSelect = screen.getByLabelText(/^resident/i) as HTMLSelectElement;
    fireEvent.change(residentSelect, { target: { value: residentSelect.options[1].value } });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const bytes = readFileSync(resolve(process.cwd(), "src/test/fixtures/sample-face.jpg"));
    const file = new File([new Uint8Array(bytes)], "face.jpg", { type: "image/jpeg" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    // Either verdict is fine — what matters is that the report from the API is rendered.
    expect(
      await screen.findByText(/quality check/i, {}, { timeout: 20_000 }),
    ).toBeTruthy();
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
