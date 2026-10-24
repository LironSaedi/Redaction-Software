import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SetupWizard } from "./pages/setup/SetupWizard";
import { UninstallDialog } from "./pages/admin/InstallationCard";
import { ToastProvider } from "./components/Toast";
import type { SetupNeeded } from "./types";

const STATE: SetupNeeded = {
  needed: true,
  version: "1.2.0",
  platform: "Windows 11 (AMD64)",
  defaults: { mode: "single", data_dir: "C:\\Users\\pat\\Obscura", port: 8600, autostart: false },
  disk_free_gb: 80,
  models_dir: "C:\\Program Files\\Obscura\\models",
  models: [{ key: "vision", label: "Face detectors", size_gb: 0.12, needed_for: "photos", required: true, present: true }],
  spacy_model: true,
  ocr: false,
  second_opinion: true,
  lan_address: "10.0.0.5",
  can_pick_folder: true,
  autostart_available: false,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("first-run setup wizard", () => {
  it("walks through an office-server setup and shows the address to share", async () => {
    const sent: { url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        sent.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
        if (url.endsWith("/setup/complete"))
          return json({ ok: true, restart: false, require_login: true, autostart: false, url: "http://127.0.0.1:8600/", lan_url: "http://10.0.0.5:8600/" });
        return json({});
      }),
    );
    render(
      <MemoryRouter>
        <SetupWizard state={STATE} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Welcome to Obscura Redaction Studio")).toBeTruthy();
    fireEvent.click(screen.getByText("Get started"));
    fireEvent.click(screen.getByText("Office server"));
    expect(screen.getByRole("button", { name: /Step 5: Administrator/ })).toBeTruthy();
    fireEvent.click(screen.getByText("Continue")); // mode
    fireEvent.click(screen.getByText("Continue")); // location (prefilled)
    fireEvent.click(screen.getByText("Continue")); // models
    // administrator: a weak password keeps the user on the step
    fireEvent.change(screen.getByLabelText("User name"), { target: { value: "pat" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "short" } });
    fireEvent.click(screen.getByText("Continue"));
    expect(screen.getByRole("alert").textContent).toMatch(/Password/);
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Correct-Horse-9x" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "Correct-Horse-9x" } });
    fireEvent.click(screen.getByText("Continue"));
    expect(screen.getByRole("heading", { name: "Review & finish" })).toBeTruthy();
    fireEvent.click(screen.getByText("Finish"));
    await waitFor(() => expect(screen.getByText("Obscura is ready")).toBeTruthy());
    expect(screen.getByText("http://10.0.0.5:8600/")).toBeTruthy();
    const done = sent.find((x) => x.url.endsWith("/setup/complete"));
    expect(done?.body).toEqual({
      mode: "office",
      require_login: true,
      admin_username: "pat",
      admin_password: "Correct-Horse-9x",
      admin_full_name: "",
      data_dir: "C:\\Users\\pat\\Obscura",
      autostart: false,
    });
  });

  it("shows a server error on the step that can fix it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/setup/complete") ? json({ detail: "cannot write to that folder: Permission denied" }, 400) : json({}),
      ),
    );
    render(
      <MemoryRouter>
        <SetupWizard state={STATE} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText("Get started"));
    fireEvent.click(screen.getByText("Continue"));
    fireEvent.click(screen.getByText("Continue"));
    fireEvent.click(screen.getByText("Continue"));
    fireEvent.click(screen.getByText("Finish"));
    await waitFor(() => expect(screen.getByText("Where should case files be kept?")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toMatch(/Permission denied/);
  });
});

describe("uninstall", () => {
  it("needs UNINSTALL typed before it can run, and sends remove_data", async () => {
    const calls: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        calls.push(JSON.parse(String(init?.body)));
        return json({ ok: true, remove_data: true });
      }),
    );
    const done = vi.fn();
    render(
      <ToastProvider>
        <UninstallDialog onClose={() => undefined} onDone={done} />
      </ToastProvider>,
    );
    const button = screen.getByRole("button", { name: /^Uninstall$/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/Also permanently delete/));
    fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: "uninstall" } });
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: "UNINSTALL" } });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(done).toHaveBeenCalledWith(true));
    expect(calls).toEqual([{ confirm: "UNINSTALL", remove_data: true }]);
  });
});
