import { describe, expect, it } from "vitest";
import { completeBody, initialChoices, missingModels, needsAdmin, stepForError, stepProblems, usernameProblem, wizardSteps } from "./setup";
import type { SetupNeeded } from "../types";

const STATE: SetupNeeded = {
  needed: true,
  version: "1.2.0",
  platform: "macOS 15 (arm64)",
  defaults: { mode: "single", data_dir: "/Users/pat/Obscura", port: 8600, autostart: false },
  disk_free_gb: 120,
  models_dir: "/Applications/Obscura/models",
  models: [
    { key: "gliner/nvidia-gliner-pii", label: "GLiNER", size_gb: 1.7, needed_for: "documents", required: true, present: false },
    { key: "vision", label: "Vision", size_gb: 0.12, needed_for: "photos", required: true, present: true },
    { key: "whisper/small", label: "Whisper", size_gb: 0.46, needed_for: "audio", required: false, present: false },
  ],
  spacy_model: true,
  ocr: true,
  second_opinion: true,
  lan_address: "192.168.1.20",
  can_pick_folder: true,
  autostart_available: true,
};

describe("setup wizard steps", () => {
  it("asks for an administrator only for an office server or when a password is wanted", () => {
    const c = initialChoices(STATE);
    expect(wizardSteps(STATE, c)).toEqual(["welcome", "mode", "location", "models", "options", "review"]);
    expect(wizardSteps(STATE, { ...c, requireLogin: true })).toContain("admin");
    expect(wizardSteps(STATE, { ...c, mode: "office" })).toEqual(["welcome", "mode", "location", "models", "admin", "options", "review"]);
    expect(wizardSteps({ autostart_available: false }, c)).not.toContain("options");
    expect(needsAdmin({ mode: "single", requireLogin: false })).toBe(false);
  });

  it("validates each step like the server", () => {
    const c = { ...initialChoices(STATE), mode: "office" as const };
    expect(stepProblems("location", { ...c, dataDir: "" })[0]).toMatch(/Choose a folder/);
    expect(stepProblems("location", { ...c, dataDir: "relative/path" })[0]).toMatch(/full folder path/);
    expect(stepProblems("location", { ...c, dataDir: "C:\\Obscura" })).toEqual([]);
    expect(stepProblems("mode", { ...c, port: 80 })[0]).toMatch(/1024/);
    expect(stepProblems("admin", { ...c, adminUsername: "local" })[0]).toMatch(/reserved/);
    const weak = stepProblems("admin", { ...c, adminUsername: "pat", adminPassword: "short" });
    expect(weak.some((p) => p.startsWith("Password:"))).toBe(true);
    expect(stepProblems("admin", { ...c, adminUsername: "pat", adminPassword: "Correct-Horse-9x", adminConfirm: "x" })[0]).toMatch(/do not match/);
    expect(stepProblems("admin", { ...c, adminUsername: "pat", adminPassword: "Correct-Horse-9x", adminConfirm: "Correct-Horse-9x" })).toEqual([]);
    expect(usernameProblem("Ana.Lopez")).toBeNull();
    expect(usernameProblem("a b")).toMatch(/letters/);
  });

  it("builds the completion body", () => {
    const single = completeBody(initialChoices(STATE), STATE);
    expect(single).toEqual({
      mode: "single",
      require_login: false,
      admin_username: null,
      admin_password: null,
      admin_full_name: "",
      data_dir: "/Users/pat/Obscura",
      autostart: false,
    });
    const office = completeBody(
      { ...initialChoices(STATE), mode: "office", adminUsername: " Pat ", adminPassword: "Correct-Horse-9x", adminFullName: " Pat Q ", port: 8700, autostart: true },
      STATE,
    );
    expect(office).toMatchObject({ mode: "office", require_login: true, admin_username: "pat", admin_full_name: "Pat Q", autostart: true, port: 8700 });
    expect(completeBody({ ...initialChoices(STATE), autostart: true }, { ...STATE, autostart_available: false }).autostart).toBe(false);
  });

  it("routes server errors to the step that can fix them", () => {
    expect(stepForError("password: At least 12 characters")).toBe("admin");
    expect(stepForError("choose an administrator user name (letters, digits, . _ -)")).toBe("admin");
    expect(stepForError("cannot write to that folder: Permission denied")).toBe("location");
    expect(stepForError("port must be between 1024 and 65535")).toBe("mode");
    expect(stepForError("setup has already been completed")).toBe("review");
  });

  it("sums the missing models", () => {
    const m = missingModels(STATE.models);
    expect(m.required.map((x) => x.key)).toEqual(["gliner/nvidia-gliner-pii"]);
    expect(m.optional.length).toBe(1);
    expect(m.downloadGb).toBe(2.2);
  });
});
