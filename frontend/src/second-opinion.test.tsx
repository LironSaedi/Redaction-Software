import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MetaProvider } from "./meta";
import { DetectionPanel } from "./pages/review/DetectionPanel";
import { FinalCheckResult } from "./components/FinalCheck";
import type { DetectionOps } from "./pages/review/useDetections";
import type { Detection } from "./types";

const META = {
  version: "1",
  entities: [{ key: "SSN", label: "Social Security number", category: "PII", description: "", default_on: true, exemption: "(b)(6)", hipaa: true }],
  categories: { PII: "Personal identifiers" },
  profiles: [],
  exemption_codes: {},
  visual_classes: {},
  effects: [],
  audio_effects: [],
  models: [],
  video_modes: [],
  second_opinion: { available: true, engine: "Microsoft Presidio", version: "2.2" },
};

function det(p: Partial<Detection>): Detection {
  return {
    id: "x",
    entity: "SSN",
    text: "123-45-6789",
    score: 0.85,
    source: "rule:ssn",
    boxes: [],
    page: 0,
    start: 0,
    end: 11,
    explanation: "",
    selected: true,
    exemption: "",
    partial: null,
    kind: "text",
    meta: {},
    ...p,
  };
}

function ops(): DetectionOps {
  const fn = () => vi.fn();
  return {
    toggle: fn(),
    setSelected: fn(),
    update: fn(),
    edit: vi.fn(async () => true),
    selectEntities: fn(),
    add: vi.fn(async () => null),
    remove: fn(),
    removeMany: fn(),
    searchAdd: vi.fn(async () => null),
    caseRedact: vi.fn(async () => null),
    reload: fn(),
    replaceAll: fn(),
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function withMeta(ui: JSX.Element) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(META), { headers: { "content-type": "application/json" } })));
  return render(
    <MemoryRouter>
      <MetaProvider>{ui}</MetaProvider>
    </MemoryRouter>,
  );
}

describe("second-opinion suggestions in the detection panel", () => {
  it("shows the badge, filters, and offers undoable bulk actions on the open ones", async () => {
    const o = ops();
    const dets = [
      det({ id: "rule" }),
      det({ id: "so1", source: "presidio:UsSsnRecognizer", selected: false, explanation: "Second opinion — Microsoft Presidio found this" }),
      det({ id: "so2", source: "presidio:UsSsnRecognizer", selected: false, start: 20, end: 31 }),
      det({ id: "so3", source: "presidio:UsSsnRecognizer", selected: true, start: 40, end: 51 }),
    ];
    withMeta(<DetectionPanel dets={dets} ops={o} focusedId={null} onFocus={() => undefined} showSuggestions setShowSuggestions={() => undefined} />);
    await waitFor(() => expect(screen.getAllByText("2nd opinion").length).toBe(3));
    expect(screen.getByText(/suggests 3 more items/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Redact all/ }));
    expect(o.setSelected).toHaveBeenCalledWith(["so1", "so2"], true, "Redact 2 second-opinion items");
    fireEvent.click(screen.getByRole("button", { name: /Dismiss all/ }));
    expect(o.removeMany).toHaveBeenCalledWith(["so1", "so2"], "Dismiss 2 second-opinion items");
    // the chip filters the list to the second-opinion items
    fireEvent.click(screen.getByRole("button", { name: /Second opinion 3/ }));
    expect(screen.getByText("3 of 4")).toBeTruthy();
  });
});

describe("export final check", () => {
  it("lists what is still readable, with reviewed items marked, and links back to review", async () => {
    withMeta(
      <FinalCheckResult
        fileId={7}
        report={{
          checked: true,
          engine: "Microsoft Presidio 2.2",
          count: 2,
          open: 1,
          findings: [
            { page: 2, entity: "SSN", text: "123-45-6789", score: 0.9, recognizer: "UsSsnRecognizer", reviewed: false },
            { page: 0, entity: "SSN", text: "000-00-0000", score: 0.5, recognizer: "UsSsnRecognizer", reviewed: true },
          ],
        }}
      />,
    );
    expect(screen.getByText("1 possible item still readable")).toBeTruthy();
    expect(screen.getByText("123-45-6789")).toBeTruthy();
    expect(screen.getByText("reviewed")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy(); // page numbers are 1-based
    expect(screen.getByRole("link", { name: /Review the file/ }).getAttribute("href")).toBe("/files/7");
  });

  it("says when the check passed or did not run", () => {
    withMeta(<FinalCheckResult report={{ checked: true, engine: "Microsoft Presidio 2.2", count: 0, open: 0, findings: [] }} />);
    expect(screen.getByText("Final check passed — nothing left that looks personal")).toBeTruthy();
    cleanup();
    withMeta(<FinalCheckResult report={{ checked: false, reason: "no readable text in this export" }} />);
    expect(screen.getByText(/Final check not run: no readable text/)).toBeTruthy();
  });
});
