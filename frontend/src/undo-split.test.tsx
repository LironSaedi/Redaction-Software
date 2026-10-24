import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { ToastProvider } from "./components/Toast";
import { MetaProvider } from "./meta";
import { OpHistory } from "./lib/history";
import { useDetections } from "./pages/review/useDetections";
import { CaseExports } from "./pages/case/CaseExports";
import { FinalCheckResult } from "./components/FinalCheck";
import type { Detection } from "./types";

const det = (id: string, selected: boolean): Detection => ({
  id, entity: "CUSTOM", text: "Austin", score: 1, source: "term", boxes: [], page: 0, start: 3, end: 9, explanation: "",
  selected, exemption: "", partial: null, kind: "text", meta: {},
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Find & Redact “Redact all” undo", () => {
  it("deletes only the detections it created and un-selects the suggestions it switched", async () => {
    let server = [det("old", false)];
    const calls: { method: string; url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? "GET";
        const body = init?.body ? JSON.parse(String(init.body)) : null;
        calls.push({ method, url, body });
        if (url.endsWith("/detections") && method === "GET") return json({ detections: server, summary: {} });
        if (url.endsWith("/search")) {
          server = [det("old", true), det("new1", true)];
          return json({ matches: [], count: 2, added_ids: ["new1", "old"], new_ids: ["new1"], switched_ids: ["old"] });
        }
        return json({ ok: true, removed: 1, restored: 1, ids: [] });
      }),
    );
    const history = new OpHistory();
    const wrapper = ({ children }: { children: ReactNode }) => <ToastProvider>{children}</ToastProvider>;
    const { result } = renderHook(() => useDetections(5, true, history), { wrapper });
    await waitFor(() => expect(result.current.dets?.length).toBe(1));
    await act(async () => {
      await result.current.ops.searchAdd({ terms: [{ text: "Austin" }] });
    });
    expect(history.snapshot().undoLabel).toBe("Redact 2 matches");
    calls.length = 0;
    await act(async () => {
      await history.undo();
    });
    const writes = calls.filter((c) => c.method !== "GET");
    expect(writes).toEqual([
      { method: "POST", url: "/api/files/5/detections/delete", body: { ids: ["new1"] } },
      { method: "PATCH", url: "/api/files/5/detections", body: { updates: [{ id: "old", selected: false }] } },
    ]);
    expect(result.current.dets?.map((d) => [d.id, d.selected])).toEqual([["old", false]]);
    calls.length = 0;
    await act(async () => {
      await history.redo();
    });
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(["POST /api/files/5/detections/restore", "PATCH /api/files/5/detections"]);
    expect((calls[0].body as { detections: Detection[] }).detections.map((d) => d.id)).toEqual(["new1"]);
  });
});

describe("“Apply to every file in this case”", () => {
  it("is one undo step that reverts every file it changed", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? "GET";
        calls.push(`${method} ${url}${init?.body && method !== "GET" ? " " + String(init.body) : ""}`);
        if (url.endsWith("/redact-text"))
          return json({
            preview: false, total_matches: 3, total_added: 3, remembered: false, list_id: null,
            files: [
              { file_id: 5, name: "this.pdf", matches: 2, added: 2, added_ids: ["n5", "s5"], new_ids: ["n5"], switched_ids: ["s5"] },
              { file_id: 6, name: "other.pdf", matches: 1, added: 1, added_ids: ["n6"], new_ids: ["n6"], switched_ids: [] },
            ],
          });
        if (url.includes("/detections") && method === "GET") return json({ detections: [det("n5", true), det("n6", true)], summary: {} });
        return json({ ok: true });
      }),
    );
    const history = new OpHistory();
    const wrapper = ({ children }: { children: ReactNode }) => <ToastProvider>{children}</ToastProvider>;
    const { result } = renderHook(() => useDetections(5, true, history), { wrapper });
    await waitFor(() => expect(result.current.dets).not.toBeNull());
    await act(async () => {
      await result.current.ops.caseRedact(9, { terms: [{ text: "Austin" }], preview: false, remember: false, entity: "CUSTOM", exemption: "", file_ids: null });
    });
    expect(history.snapshot().undoLabel).toBe("Redact 3 items in 2 files");
    calls.length = 0;
    await act(async () => {
      await history.undo();
    });
    const writes = calls.filter((c) => !c.startsWith("GET"));
    expect(writes).toEqual([
      'POST /api/files/5/detections/delete {"ids":["n5"]}',
      'PATCH /api/files/5/detections {"updates":[{"id":"s5","selected":false}]}',
      'POST /api/files/6/detections/delete {"ids":["n6"]}',
    ]);
  });
});

describe("case exports list", () => {
  it("shows the final check from the list and fetches findings only when a row is expanded", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        urls.push(url);
        if (url.endsWith("/meta")) return json({ entities: [], categories: {}, profiles: [], exemption_codes: {} });
        if (url.endsWith("/cases/4/exports"))
          return json([
            { id: 11, file_id: 1, file_name: "a.pdf", name: "a_REDACTED.pdf", verified: true, marked_copy: false, second_opinion_open: 2, sha256: "", size: 10, created_at: "" },
            { id: 12, file_id: 2, file_name: "b.pdf", name: "b_REDACTED.pdf", verified: true, marked_copy: false, second_opinion_open: 0, sha256: "", size: 10, created_at: "" },
            { id: 13, file_id: 3, file_name: "c.pdf", name: "c_REDACTED.pdf", verified: true, marked_copy: false, second_opinion_open: null, sha256: "", size: 10, created_at: "" },
          ]);
        if (url.endsWith("/exports/11"))
          return json({
            id: 11, file_id: 1, name: "a_REDACTED.pdf", sha256: "", size: 10, settings: {}, verified: true, created_at: "",
            report: { second_opinion: { checked: true, engine: "Microsoft Presidio 2.2", count: 2, open: 2, findings: [{ page: 0, entity: "PERSON", score: 0.8, recognizer: "SpacyRecognizer", reviewed: false }] } },
          });
        return json({});
      }),
    );
    render(
      <MemoryRouter>
        <ToastProvider>
          <MetaProvider>
            <CaseExports caseId={4} canReview />
          </MetaProvider>
        </ToastProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("2 possible items still readable")).toBeTruthy());
    expect(screen.getByText("passed")).toBeTruthy();
    expect(screen.getByText("not checked")).toBeTruthy();
    expect(urls.some((u) => /\/exports\/\d+$/.test(u))).toBe(false);
    fireEvent.click(screen.getByText("2 possible items still readable"));
    await waitFor(() => expect(urls).toContain("/api/exports/11"));
    expect(urls.filter((u) => /\/exports\/\d+$/.test(u))).toEqual(["/api/exports/11"]);
  });
});

describe("final check for viewers", () => {
  it("renders page and type without a text column when the text is withheld", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ entities: [], categories: {}, profiles: [], exemption_codes: {} })));
    render(
      <MemoryRouter>
        <MetaProvider>
          <FinalCheckResult
            report={{ checked: true, engine: "Microsoft Presidio 2.2", count: 1, open: 1, findings: [{ page: 4, entity: "PHONE", score: 0.7, recognizer: "PhoneRecognizer", reviewed: false }] }}
          />
        </MetaProvider>
      </MemoryRouter>,
    );
    expect(screen.getByText("1 possible item still readable")).toBeTruthy();
    expect(screen.queryByText("Text")).toBeNull();
    expect(screen.getByText("5")).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Page", "Type", ""]);
  });
});
