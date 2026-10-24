import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useParams } from "react-router-dom";
import { ScanSearch } from "lucide-react";
import * as api from "../../api";
import { canSeeOriginals, hasRole, useUser } from "../../auth";
import { useJobs } from "../../jobs";
import { useMeta } from "../../meta";
import { useToast } from "../../components/Toast";
import { AnalyzeDialog } from "../../components/AnalyzeDialog";
import { ExportDialog } from "../../components/ExportDialog";
import { EmptyState, ErrorState, Loading, SkeletonList } from "../../components/ui";
import { useHotkeys } from "../../lib/hotkeys";
import { OpHistory } from "../../lib/history";
import { formatDate, isTextKind } from "../../lib/format";
import type { CaseDetail, Detection, FileRecord, PagesResponse } from "../../types";
import { useDetections } from "./useDetections";
import { PagedViewer, type DrawDefaults } from "./PagedViewer";
import { TextViewer } from "./TextViewer";
import { AudioViewer } from "./AudioViewer";
import { VideoWorkspace } from "./VideoWorkspace";
import { ReviewHeader } from "./ReviewHeader";
import { ReviewSidebar, type SideTab } from "./ReviewSidebar";
import { ShortcutsHelp } from "./ShortcutsHelp";
import { ViewerFileView } from "../ExportViewerPage";
import type { FocusRequest, ViewMode } from "./workspace";

export interface JumpRequest {
  match: Detection;
  nonce: number;
}

function useHistorySnapshot(h: OpHistory) {
  return useSyncExternalStore(
    useCallback((cb) => h.subscribe(cb), [h]),
    () => h.snapshot(),
  );
}

export function ReviewPage() {
  const params = useParams();
  const fileId = Number(params.fileId);
  const user = useUser();
  const toast = useToast();
  const jobs = useJobs();
  const m = useMeta();
  const originals = canSeeOriginals(user);
  const [file, setFile] = useState<FileRecord | null>(null);
  const [caseData, setCaseData] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pages, setPages] = useState<PagesResponse | null>(null);
  const [pagesError, setPagesError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [focus, setFocus] = useState<FocusRequest | null>(null);
  const [jump, setJump] = useState<JumpRequest | null>(null);
  const [mode, setMode] = useState<ViewMode>("edit");
  const [showSuggestions, setShowSuggestions] = useState(true);
  const [searchMatches, setSearchMatches] = useState<Detection[]>([]);
  const [tab, setTab] = useState<SideTab>("detections");
  const [showAnalyze, setShowAnalyze] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [defaults, setDefaults] = useState<DrawDefaults>({ entity: "CUSTOM", exemption: "", effect: "", fill: null, label_text: "" });
  const nonce = useRef(0);

  // one undo history per opened file (detections and video tracks share it)
  const history = useMemo(() => new OpHistory(), [fileId]);
  const snap = useHistorySnapshot(history);

  const loadFile = useCallback(() => {
    api.getFile(fileId).then(
      (f) => {
        setFile(f);
        setError(null);
      },
      (e) => setError(e instanceof Error ? e.message : "could not load file"),
    );
  }, [fileId]);

  useEffect(() => {
    setFile(null);
    setPages(null);
    setFocus(null);
    setPage(0);
    setSearchMatches([]);
    setMode("edit");
    loadFile();
  }, [loadFile]);

  useEffect(() => {
    if (file?.kind === "image") setDefaults((d) => (d.entity === "CUSTOM" ? { ...d, entity: "FACE" } : d));
  }, [file?.kind]);

  useEffect(() => {
    if (!file) return;
    if (caseData?.id === file.case_id) return;
    api.getCase(file.case_id).then(setCaseData, () => undefined);
  }, [file, caseData?.id]);

  const statusRefresh = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onChanged = useCallback(() => {
    // the file moves to "in review" after the first change; refresh it lazily
    if (statusRefresh.current) clearTimeout(statusRefresh.current);
    statusRefresh.current = setTimeout(loadFile, 800);
  }, [loadFile]);

  const { dets, error: detError, ops } = useDetections(fileId, !!file && originals, history, onChanged);
  // edits keep ids, so the selection simply follows the detection
  const liveFocus = focus;

  // page geometry / extracted text
  const pagesKey = file ? `${file.id}:${file.analyzed_at ?? ""}` : "";
  useEffect(() => {
    if (!file || !originals) return;
    if (file.kind === "video" || file.kind === "audio") return;
    const ctl = new AbortController();
    setPagesError(null);
    api.getPages(file.id, ctl.signal).then(setPages, (e: unknown) => {
      if (!(e instanceof DOMException)) setPagesError(e instanceof Error ? e.message : "could not load pages");
    });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pagesKey, originals]);

  // reload everything when a job on this file finishes (started here or elsewhere)
  const job = jobs.jobForFile(fileId);
  const prevJob = useRef<{ id: number; kind: string } | null>(null);
  useEffect(() => {
    const prev = prevJob.current;
    if (prev && !job) {
      loadFile();
      if (prev.kind === "analyze") {
        ops.reload();
        history.clear(); // the detections were replaced
      }
    }
    prevJob.current = job ? { id: job.id, kind: job.kind } : null;
  }, [job, loadFile, ops, history]);

  const onFocus = useCallback((d: Detection | null, source: "panel" | "viewer") => {
    if (!d) {
      setFocus(null);
      return;
    }
    nonce.current += 1;
    setFocus({ id: d.id, nonce: nonce.current, source });
  }, []);

  const onJump = useCallback((match: Detection) => {
    const p = match.boxes[0]?.page ?? match.page;
    if (p >= 0) setPage(p);
    nonce.current += 1;
    setJump({ match, nonce: nonce.current });
  }, []);

  const undo = useCallback(async () => {
    try {
      await history.undo();
    } catch (e) {
      toast.error(e, "Could not undo");
    }
  }, [history, toast]);
  const redo = useCallback(async () => {
    try {
      await history.redo();
    } catch (e) {
      toast.error(e, "Could not redo");
    }
  }, [history, toast]);

  const redactor = hasRole(user, "redactor");
  useHotkeys({
    "?": () => setShowHelp(true),
    // some keyboard layouts / automation report Shift+/ as "/"
    "/": (e) => e.shiftKey && setShowHelp(true),
    "mod+z": () => redactor && undo(),
    "mod+shift+z": () => redactor && redo(),
    "mod+y": () => redactor && redo(),
  });

  const chips = useMemo(() => {
    if (!file) return null;
    const out: JSX.Element[] = [];
    const la = file.info?.last_analysis;
    const stats = pages?.stats;
    const ocr = stats
      ? (stats.ocr_pages ?? 0) + (stats.hybrid_pages ?? 0)
      : (pages?.pages ?? []).filter((p) => p.source === "ocr" || p.source === "hybrid").length;
    if ((file.kind === "pdf" || file.kind === "email") && file.analyzed_at)
      out.push(
        <span key="ocr" className="chip">
          {ocr ? `OCR'd pages: ${ocr}` : "Native text"}
        </span>,
      );
    if (file.kind === "image" && file.analyzed_at && la?.image_text !== false)
      out.push(
        <span key="ocr" className="chip">
          Text read by OCR
        </span>,
      );
    if (la) {
      out.push(
        <span key="ml" className="chip" data-tip="Detectors used in the last analysis">
          {la.use_ml === false ? "Rules only" : "AI models + rules"}
        </span>,
      );
      if (la.profile) {
        const p = m.meta?.profiles.find((x) => x.key === la.profile);
        out.push(
          <span key="prof" className="chip">
            {p ? p.label.split(" — ")[0].split(" (")[0].trim() : la.profile}
          </span>,
        );
      }
    }
    if (file.analyzed_at) out.push(<span key="at" className="chip">Analyzed {formatDate(file.analyzed_at, true)}</span>);
    if (file.status === "approved") out.push(<span key="appr" className="chip chip-ok">Approved</span>);
    return out.length ? <>{out}</> : null;
  }, [file, pages, m.meta]);

  if (error)
    return (
      <div className="page">
        <ErrorState message={error} onRetry={loadFile} />
      </div>
    );
  if (!file) return <Loading label="Opening file…" />;
  if (!originals) return <ViewerFileView file={file} />;

  const analyzed = !!file.analyzed_at || file.has_detections;
  const canExport = file.has_detections || file.kind === "video";
  const readOnly = !redactor;
  const preview = mode === "preview";
  const setPreview = (v: boolean) => setMode(v ? "preview" : "edit");
  const isPaged = file.kind === "pdf" || file.kind === "image" || file.kind === "email";
  const pageList = pages?.pages?.length
    ? pages.pages
    : file.kind === "image" && file.info?.width && file.info?.height
      ? [{ page: 0, width: file.info.width, height: file.info.height, source: "image" }]
      : [];

  const approve = async () => {
    try {
      const f = await api.updateFile(file.id, { status: "approved" });
      setFile(f);
      toast.success("File approved for release");
    } catch (e) {
      toast.error(e, "Could not approve");
    }
  };

  const searchDisabled =
    !analyzed && !isTextKind(file.kind)
      ? "Analyze the file first: Find & Redact searches its extracted text."
      : (file.kind === "audio" || file.kind === "video") && !file.has_transcript
        ? "Transcribe the recording first (analyze it with audio enabled)."
        : null;

  const sidebar = (extra?: { title?: string; emptyHint?: string }) =>
    detError ? (
      <aside className="side-col">
        <ErrorState message={detError} onRetry={ops.reload} />
      </aside>
    ) : !dets ? (
      <aside className="side-col">
        <SkeletonList rows={10} label="Loading detections" />
      </aside>
    ) : (
      <ReviewSidebar
        file={file}
        dets={dets}
        ops={ops}
        focusedId={liveFocus?.id ?? null}
        onFocus={(d) => onFocus(d, "panel")}
        clearFocus={() => setFocus(null)}
        showSuggestions={showSuggestions}
        setShowSuggestions={setShowSuggestions}
        readOnly={readOnly}
        chips={chips}
        pages={pageList}
        currentPage={isPaged && pageList.length ? page : null}
        analyzed={analyzed}
        searchDisabled={searchDisabled}
        onSearchPreview={setSearchMatches}
        onJump={onJump}
        defaults={defaults}
        setDefaults={setDefaults}
        tab={tab}
        setTab={setTab}
        detectionsTitle={extra?.title}
        emptyHint={extra?.emptyHint}
        footer={
          !analyzed && redactor ? (
            <div className="analyze-cta">
              <p className="small">This file has not been analyzed yet.</p>
              <button className="btn btn-primary btn-sm" onClick={() => setShowAnalyze(true)}>
                <ScanSearch size={14} aria-hidden /> Analyze now
              </button>
            </div>
          ) : undefined
        }
      />
    );

  let body: JSX.Element;
  if (file.kind === "video") {
    body = (
      <VideoWorkspace
        file={file}
        dets={dets ?? []}
        ops={ops}
        focus={liveFocus}
        onFocus={onFocus}
        showSuggestions={showSuggestions}
        setShowSuggestions={setShowSuggestions}
        chips={chips}
        history={history}
        readOnly={readOnly}
        jump={jump}
        onJump={onJump}
        onSearchPreview={setSearchMatches}
        onFileChanged={loadFile}
      />
    );
  } else if (file.kind === "audio") {
    body = (
      <div className="review-body">
        <AudioViewer
          file={file}
          dets={dets ?? []}
          ops={ops}
          focus={liveFocus}
          onFocus={onFocus}
          preview={preview}
          setPreview={setPreview}
          showSuggestions={showSuggestions}
          jump={jump}
          readOnly={readOnly}
          onFileChanged={loadFile}
        />
        {sidebar({ title: "Spoken PII", emptyHint: "Select words in the transcript to redact them." })}
      </div>
    );
  } else if (isTextKind(file.kind)) {
    body = (
      <div className="review-body">
        {pagesError ? (
          <div className="viewer-col">
            <ErrorState message={pagesError} />
          </div>
        ) : !pages ? (
          <div className="viewer-col">
            <Loading label="Loading text…" />
          </div>
        ) : pages.text == null ? (
          <div className="viewer-col">
            <EmptyState icon={<ScanSearch size={30} />} title="Text not extracted yet">
              Analyze the document to extract its text and find sensitive information.
            </EmptyState>
          </div>
        ) : (
          <TextViewer
            text={pages.text}
            dets={dets ?? []}
            ops={ops}
            focus={liveFocus}
            onFocus={onFocus}
            preview={preview}
            setPreview={setPreview}
            showSuggestions={showSuggestions}
            setShowSuggestions={setShowSuggestions}
            searchMatches={searchMatches}
            jump={jump}
            readOnly={readOnly}
          />
        )}
        {sidebar({ emptyHint: "Select text in the document to add a redaction." })}
      </div>
    );
  } else {
    body = (
      <div className="review-body">
        {pagesError ? (
          <div className="viewer-col">
            <ErrorState message={pagesError} />
          </div>
        ) : !pages ? (
          <div className="viewer-col">
            <Loading label="Loading pages…" />
          </div>
        ) : pageList.length === 0 ? (
          <div className="viewer-col">
            <EmptyState title="No pages to show">
              {file.kind === "email"
                ? "This server cannot render email files in the page viewer yet. The attachments are listed as separate files in the case."
                : "The page geometry could not be read."}
            </EmptyState>
          </div>
        ) : (
          <PagedViewer
            file={file}
            pages={pageList}
            page={Math.min(page, pageList.length - 1)}
            setPage={setPage}
            dets={dets ?? []}
            ops={ops}
            focus={liveFocus}
            onFocus={onFocus}
            mode={mode}
            setMode={setMode}
            showSuggestions={showSuggestions}
            setShowSuggestions={setShowSuggestions}
            searchMatches={searchMatches}
            analyzed={analyzed}
            readOnly={readOnly}
            defaults={defaults}
          />
        )}
        {sidebar()}
      </div>
    );
  }

  return (
    <div className="review">
      <ReviewHeader
        file={file}
        caseName={caseData?.name ?? null}
        job={job}
        history={snap}
        onUndo={undo}
        onRedo={redo}
        onHelp={() => setShowHelp(true)}
        onAnalyze={() => setShowAnalyze(true)}
        onApprove={approve}
        onExport={() => setShowExport(true)}
        analyzed={analyzed}
        canExport={canExport}
        redactor={redactor}
        supervisor={hasRole(user, "supervisor")}
      />
      {body}
      {showAnalyze && (
        <AnalyzeDialog
          caseId={file.case_id}
          files={[file]}
          defaultProfile={caseData?.default_profile}
          onClose={() => setShowAnalyze(false)}
          onDone={() => {
            loadFile();
            ops.reload();
            history.clear();
          }}
        />
      )}
      {showExport && <ExportDialog caseId={file.case_id} files={[file]} onClose={() => setShowExport(false)} onDone={loadFile} />}
      {showHelp && <ShortcutsHelp kind={file.kind} onClose={() => setShowHelp(false)} />}
    </div>
  );
}
