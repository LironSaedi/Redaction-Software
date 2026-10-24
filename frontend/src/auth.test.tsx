import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "./auth";

const LOCAL_USER = {
  id: 1, username: "local", full_name: "This computer", email: "", role: "admin", is_active: true,
  must_change_password: false, locked: false, created_at: "", last_login: null, local: true,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function Probe() {
  const { status, user, localMode } = useAuth();
  return <div data-testid="probe">{`${status}|${user?.username ?? ""}|${localMode}`}</div>;
}

describe("sign-in turned off", () => {
  let calls: string[];
  beforeEach(() => {
    calls = [];
    sessionStorage.clear();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  function stub(mode: { require_login: boolean; local_access: boolean }) {
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/auth/mode")) return json(mode);
      if (url.endsWith("/auth/local")) return json({ token: "t-local", user: LOCAL_USER });
      return json({ detail: "not authenticated" }, 401);
    }));
  }

  it("opens straight into the app on this computer", async () => {
    stub({ require_login: false, local_access: true });
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("probe").textContent).toBe("authenticated|local|true"));
    expect(calls).toContain("POST /api/auth/local");
    expect(sessionStorage.getItem("obscura.session")).toBe("t-local");
  });

  it("shows the sign-in screen when the server requires it", async () => {
    stub({ require_login: true, local_access: false });
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("probe").textContent).toBe("anonymous||false"));
    expect(calls).not.toContain("POST /api/auth/local");
  });

  it("asks other computers to sign in", async () => {
    stub({ require_login: false, local_access: false });
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("probe").textContent).toBe("anonymous||false"));
  });

  it("falls back to the sign-in screen when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("probe").textContent).toBe("anonymous||false"));
  });

  it("replaces an expired saved session with a fresh local one", async () => {
    sessionStorage.setItem("obscura.session", "old");
    stub({ require_login: false, local_access: true });
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("probe").textContent).toBe("authenticated|local|true"));
    expect(calls[0]).toBe("GET /api/auth/me");
  });
});
