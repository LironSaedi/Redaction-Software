import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { ApiError, buildQuery, configureApi, filenameFromDisposition, formatDetail } from "./api";

type FetchArgs = [string, RequestInit | undefined];

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("buildQuery", () => {
  it("drops empty values and encodes the rest", () => {
    expect(buildQuery({ a: 1, b: "x y", c: undefined, d: null, e: "", f: false })).toBe("?a=1&b=x+y&f=false");
  });
  it("returns an empty string when nothing is left", () => {
    expect(buildQuery({ a: undefined })).toBe("");
    expect(buildQuery()).toBe("");
  });
});

describe("formatDetail", () => {
  it("passes plain FastAPI detail strings through", () => {
    expect(formatDetail({ detail: "invalid username or password" }, 401)).toBe("invalid username or password");
  });
  it("flattens validation errors", () => {
    const body = { detail: [{ loc: ["body", "name"], msg: "field required" }, { loc: ["query", "dpi"], msg: "bad" }] };
    expect(formatDetail(body, 422)).toBe("name: field required; query.dpi: bad");
  });
  it("falls back to the status", () => {
    expect(formatDetail(null, 500)).toBe("request failed (500)");
    expect(formatDetail(null, 0)).toBe("the server could not be reached");
  });
});

describe("filenameFromDisposition", () => {
  it("reads quoted and RFC 5987 names", () => {
    expect(filenameFromDisposition('attachment; filename="report_REDACTED.pdf"', "x")).toBe("report_REDACTED.pdf");
    expect(filenameFromDisposition("attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf", "x")).toBe("résumé.pdf");
    expect(filenameFromDisposition(null, "fallback.bin")).toBe("fallback.bin");
  });
});

describe("request", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let token: string | null;
  const onUnauthorized = vi.fn();

  beforeEach(() => {
    token = "tok-123";
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    configureApi({ getToken: () => token, onUnauthorized });
    onUnauthorized.mockReset();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the bearer token and a JSON body on writes", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 7, name: "Case" }));
    const c = await api.createCase({ name: "Case", request_type: "FOIA" });
    expect(c.id).toBe(7);
    const [url, init] = fetchMock.mock.calls[0] as FetchArgs;
    expect(url).toBe("/api/cases");
    expect(init?.method).toBe("POST");
    const h = init?.headers as Record<string, string>;
    expect(h.Authorization).toBe("Bearer tok-123");
    expect(h["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({ name: "Case", request_type: "FOIA" });
    expect(init?.credentials).toBe("same-origin");
  });

  it("never puts the token in the URL", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listAudit({ case_id: 3, action: "login", limit: 10 });
    const [url] = fetchMock.mock.calls[0] as FetchArgs;
    expect(url).toBe("/api/audit?case_id=3&action=login&limit=10");
    expect(url).not.toContain("tok-123");
    expect(url).not.toContain("token");
  });

  it("maps endpoints to the documented paths and verbs", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ ok: true })));
    await api.patchDetections(5, { select_entities: { PERSON: false } });
    await api.addDetection(5, { page: 0, boxes: [{ x0: 1, y0: 2, x1: 3, y1: 4 }] });
    await api.deleteDetection(5, "abc123");
    await api.patchTrack(9, 2, { enabled: false });
    await api.setWatcherEnabled(4, true);
    await api.bulkExport(2, [1, 2], { effect: "blur" });
    const calls = (fetchMock.mock.calls as FetchArgs[]).map(([u, i]) => `${i?.method} ${u}`);
    expect(calls).toEqual([
      "PATCH /api/files/5/detections",
      "POST /api/files/5/detections",
      "DELETE /api/files/5/detections/abc123",
      "PATCH /api/files/9/video/tracks/2",
      "PATCH /api/watchers/4?enabled=true",
      "POST /api/cases/2/bulk/export",
    ]);
    const bulkBody = JSON.parse(String((fetchMock.mock.calls[5] as FetchArgs)[1]?.body));
    expect(bulkBody).toEqual({ file_ids: [1, 2], params: { effect: "blur" } });
  });

  it("throws ApiError with the server detail", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "analyze the file before exporting" }, 409));
    const err = await api.exportFile(1, {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect((err as ApiError).detail).toBe("analyze the file before exporting");
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("ends the session on 401, except for the login call", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "session revoked" }, 401));
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    fetchMock.mockResolvedValue(jsonResponse({ detail: "invalid username or password" }, 401));
    await expect(api.login("a", "b")).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("reports network failures as status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.listCases()).rejects.toMatchObject({ status: 0 });
  });

  it("omits Authorization when signed out", async () => {
    token = null;
    fetchMock.mockResolvedValue(jsonResponse({ ok: true, version: "1" }));
    await api.health();
    const h = (fetchMock.mock.calls[0] as FetchArgs)[1]?.headers as Record<string, string>;
    expect(h.Authorization).toBeUndefined();
  });

  it("polls a job until it finishes", async () => {
    const states = ["queued", "running", "done"];
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ id: 3, kind: "analyze", status: states.shift(), progress: 0.5, message: "" })),
    );
    const seen: string[] = [];
    const j = await api.waitForJob(3, { intervalMs: 1, onUpdate: (x) => seen.push(String(x.status)) });
    expect(j.status).toBe("done");
    expect(seen).toEqual(["queued", "running", "done"]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("surfaces download errors instead of saving them", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "this export failed verification; a supervisor must review it" }, 409));
    await expect(api.downloadExport(4, "x.pdf")).rejects.toMatchObject({ status: 409 });
  });

  it("starts translations and reads them back with ids / language codes only in the URL", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ job_id: 9, segments: [] })));
    await api.translateTranscript(4, "es", true);
    await api.getTranslation(4, "es", false);
    await api.getTranslation(4, "fr");
    const calls = fetchMock.mock.calls as FetchArgs[];
    expect(`${calls[0][1]?.method} ${calls[0][0]}`).toBe("POST /api/files/4/translate");
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ target: "es", redacted: true });
    expect((calls[0][1]?.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
    expect(calls[1][0]).toBe("/api/files/4/translations/es?redacted=false");
    expect(calls[2][0]).toBe("/api/files/4/translations/fr?redacted=true");
  });

  it("downloads captions per language and the confidence report through fetch + blob", async () => {
    const created: string[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      created.push(this.download);
    });
    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response("1\n00:00:00,000 --> 00:00:01,000\nhi\n", { status: 200, headers: { "content-type": "text/plain" } })),
    );
    await api.downloadCaptions(7, "vtt", { lang: "de", redacted: true });
    await api.downloadCaptions(7, "srt");
    await api.downloadConfidenceReport(7);
    const urls = (fetchMock.mock.calls as FetchArgs[]).map(([u]) => u);
    expect(urls).toEqual([
      "/api/files/7/captions.vtt?redacted=true&lang=de",
      "/api/files/7/captions.srt?redacted=true",
      "/api/files/7/confidence.csv",
    ]);
    expect(created).toEqual(["captions_de.vtt", "captions.srt", "confidence_report_7.csv"]);
    for (const [, init] of fetchMock.mock.calls as FetchArgs[]) {
      expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
    }
    click.mockRestore();
  });

  it("sends the new manual-shape fields as given", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ id: "n1" })));
    await api.addDetection(3, {
      page: 1,
      boxes: [{ x0: 1, y0: 2, x1: 30, y1: 40 }],
      shape: "polygon",
      points: [
        [1, 2],
        [30, 2],
        [10, 40],
      ],
      entity: "FACE",
      effect: "pixelate",
      label_text: "(b)(6)",
      fill: [1, 0, 0],
    });
    await api.addTrack(3, { frame: 10, end_frame: 50, box: [0, 0, 0, 0], mode: "full_frame", effect: "blur" });
    const [[, a], [, b]] = fetchMock.mock.calls as FetchArgs[];
    expect(JSON.parse(String(a?.body))).toMatchObject({ shape: "polygon", effect: "pixelate", label_text: "(b)(6)", fill: [1, 0, 0] });
    expect(JSON.parse(String(b?.body))).toEqual({ frame: 10, end_frame: 50, box: [0, 0, 0, 0], mode: "full_frame", effect: "blur" });
  });

  it("uses the bulk delete / restore endpoints with ids in the body", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ removed: 2, restored: 1, ids: ["a"] })));
    await api.deleteDetections(3, ["a", "b"]);
    const d = { id: "a", entity: "SSN", text: "", score: 0.9, source: "rule:ssn", boxes: [], page: 0, start: 1, end: 5, explanation: "", selected: true, exemption: "", partial: null, kind: "text", meta: {} };
    await api.restoreDetections(3, [d]);
    await api.restoreTrack(3, { id: 4, label: "face", enabled: true, source: "yolo", first: 1, last: 2, max_score: 0.8, boxes: { "1": [0, 0, 1, 1] } });
    await api.listTranslations(3);
    await api.patchDetections(3, { updates: [{ id: "a", label_text: "", fill: [], shape: "rect", points: [] }] });
    const calls = fetchMock.mock.calls as FetchArgs[];
    expect(calls.map(([u, i]) => `${i?.method} ${u}`)).toEqual([
      "POST /api/files/3/detections/delete",
      "POST /api/files/3/detections/restore",
      "POST /api/files/3/video/tracks/restore",
      "GET /api/files/3/translations",
      "PATCH /api/files/3/detections",
    ]);
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ ids: ["a", "b"] });
    expect(JSON.parse(String(calls[1][1]?.body))).toEqual({ detections: [d] });
    expect(JSON.parse(String(calls[2][1]?.body)).track.boxes).toEqual({ "1": [0, 0, 1, 1] });
    expect(JSON.parse(String(calls[4][1]?.body))).toEqual({ updates: [{ id: "a", label_text: "", fill: [], shape: "rect", points: [] }] });
  });

  it("maps the setup, installation and case text endpoints", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ ok: true, path: null, terms: [], files: [] })));
    await api.getSetupState();
    await api.pickFolder("models");
    await api.importModels("/Volumes/USB/models");
    await api.downloadModels();
    await api.getSetupModels();
    await api.completeSetup({
      mode: "single",
      require_login: false,
      admin_username: null,
      admin_password: null,
      admin_full_name: "",
      data_dir: "/Users/pat/Obscura",
      autostart: true,
    });
    await api.getAppInfo();
    await api.updateApp({ require_login: true });
    await api.restartApp();
    await api.uninstallApp(true);
    await api.caseRedactText(4, { terms: [{ text: "Jordan" }], preview: true, remember: true, entity: "CUSTOM", exemption: "", file_ids: null });
    await api.getCaseRedactText(4);
    await api.putCaseRedactText(4, []);
    await api.listCaseExports(4);
    const calls = fetchMock.mock.calls as FetchArgs[];
    expect(calls.map(([u, i]) => `${i?.method} ${u}`)).toEqual([
      "GET /api/setup/state",
      "POST /api/setup/pick-folder?purpose=models",
      "POST /api/setup/models/import",
      "POST /api/setup/models/download",
      "GET /api/setup/models",
      "POST /api/setup/complete",
      "GET /api/system/app",
      "PATCH /api/system/app",
      "POST /api/system/restart",
      "POST /api/system/uninstall",
      "POST /api/cases/4/redact-text",
      "GET /api/cases/4/redact-text",
      "PUT /api/cases/4/redact-text",
      "GET /api/cases/4/exports",
    ]);
    const body = (n: number) => JSON.parse(String(calls[n][1]?.body));
    expect(body(2)).toEqual({ path: "/Volumes/USB/models" });
    expect(body(5)).toMatchObject({ mode: "single", data_dir: "/Users/pat/Obscura", autostart: true });
    expect(body(9)).toEqual({ confirm: "UNINSTALL", remove_data: true });
    expect(body(10)).toMatchObject({ terms: [{ text: "Jordan" }], preview: true, file_ids: null });
    expect(body(12)).toEqual({ terms: [] });
    // the redact-text terms travel in the body, never in the URL
    expect(calls.every(([u]) => !u.includes("Jordan"))).toBe(true);
  });

  it("builds media URLs from ids only", () => {
    expect(api.urls.pageImage(12, 3)).toBe("/api/files/12/pages/3.png?dpi=110");
    expect(api.urls.videoFrame(5, 30, true, "pixelate")).toBe("/api/files/5/video/frame/30.jpg?preview=true&effect=pixelate");
    expect(api.urls.exportPage(2, 0, 72)).toBe("/api/exports/2/pages/0.png?dpi=72");
  });
});
