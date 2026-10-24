import { describe, expect, it } from "vitest";
import { MAX_TERMS, parseTerms, sameTerm, termFlags } from "./redactText";
import { finalCheckHeadline, finalCheckState, isSecondOpinion, recognizerOf } from "./secondOpinion";

const OPTS = { regex: false, case_sensitive: false, whole_word: true, entity: "CUSTOM" };

describe("redact additional text: parsing the list", () => {
  it("keeps one entry per line, trimmed, without blanks or duplicates", () => {
    const r = parseTerms("  Jordan Alvarez \n\n555-0143\njordan alvarez\n", OPTS);
    expect(r.problems).toEqual([]);
    expect(r.terms).toEqual([
      { text: "Jordan Alvarez", regex: false, case_sensitive: false, whole_word: true, entity: "CUSTOM" },
      { text: "555-0143", regex: false, case_sensitive: false, whole_word: true, entity: "CUSTOM" },
    ]);
    expect(parseTerms("Ana\nana", { ...OPTS, case_sensitive: true }).terms.length).toBe(2);
  });

  it("reports the server's limits before sending", () => {
    expect(parseTerms("   \n", OPTS).problems[0]).toMatch(/at least one/);
    expect(parseTerms("x".repeat(501), OPTS).problems[0]).toMatch(/longer than 500/);
    const many = Array.from({ length: MAX_TERMS + 1 }, (_, i) => `term ${i}`).join("\n");
    expect(parseTerms(many, OPTS).problems[0]).toMatch(/At most 500/);
    expect(parseTerms("a*", { ...OPTS, regex: true }).problems[0]).toMatch(/matches empty text/);
    expect(parseTerms("\\bCLM-\\d+\\b", { ...OPTS, regex: true }).problems).toEqual([]);
  });

  it("describes and compares entries", () => {
    expect(termFlags({ text: "x", regex: true, case_sensitive: true, whole_word: false })).toEqual(["pattern", "match case", "partial words"]);
    expect(sameTerm({ text: "a" }, { text: "a", regex: false, whole_word: true })).toBe(true);
    expect(sameTerm({ text: "a" }, { text: "a", regex: true })).toBe(false);
  });
});

describe("second opinion", () => {
  it("recognises Presidio suggestions", () => {
    expect(isSecondOpinion({ source: "presidio:UsSsnRecognizer" })).toBe(true);
    expect(isSecondOpinion({ source: "ner:gliner" })).toBe(false);
    expect(recognizerOf({ source: "presidio:EmailRecognizer" })).toBe("EmailRecognizer");
  });

  it("summarises the export's final check without echoing found text", () => {
    expect(finalCheckState(undefined)).toBeNull();
    expect(finalCheckState({ checked: false, reason: "no readable text in this export" })).toEqual({
      state: "unchecked",
      reason: "no readable text in this export",
    });
    const passed = finalCheckState({ checked: true, engine: "Microsoft Presidio 2.2", count: 1, open: 0, findings: [{ page: 0, entity: "PERSON", text: "Ana", score: 0.8, recognizer: "SpacyRecognizer", reviewed: true }] });
    expect(passed).toMatchObject({ state: "passed", reviewed: 1 });
    expect(finalCheckHeadline(passed!)).toBe("Final check passed — nothing left that looks personal");
    const open = finalCheckState({ checked: true, engine: "Microsoft Presidio 2.2", count: 2, open: 2, findings: [] });
    expect(finalCheckHeadline(open!)).toBe("2 possible items still readable");
    expect(finalCheckHeadline(finalCheckState({ checked: true, engine: "P", count: 1, open: 1, findings: [] })!)).toBe("1 possible item still readable");
  });
});
