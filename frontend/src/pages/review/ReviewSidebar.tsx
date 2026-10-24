import { useMemo, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp, SlidersHorizontal } from "lucide-react";
import { useMeta } from "../../meta";
import { Tabs } from "../../components/ui";
import { isPicture } from "../../lib/pictures";
import type { Detection, FileRecord, PageInfo } from "../../types";
import type { DetectionOps } from "./useDetections";
import { DetectionPanel } from "./DetectionPanel";
import { FindRedactPanel } from "./FindRedactPanel";
import { PicturesPanel } from "./PicturesPanel";
import { PropertiesPanel } from "./PropertiesPanel";
import type { DrawDefaults } from "./PagedViewer";

export type SideTab = "detections" | "pictures" | "find";

interface Props {
  file: FileRecord;
  dets: Detection[];
  ops: DetectionOps;
  focusedId: string | null;
  onFocus: (d: Detection) => void;
  clearFocus: () => void;
  showSuggestions: boolean;
  setShowSuggestions: (v: boolean) => void;
  readOnly: boolean;
  chips?: ReactNode;
  pages: PageInfo[];
  currentPage: number | null;
  analyzed: boolean;
  /** why Find & Redact cannot run yet (null = available) */
  searchDisabled: string | null;
  onSearchPreview: (matches: Detection[]) => void;
  onJump: (match: Detection) => void;
  defaults: DrawDefaults;
  setDefaults: (d: DrawDefaults) => void;
  tab: SideTab;
  setTab: (t: SideTab) => void;
  detectionsTitle?: string;
  emptyHint?: ReactNode;
  footer?: ReactNode;
}

export function ReviewSidebar(p: Props) {
  const m = useMeta();
  // null = automatic: open while a redaction is selected, folded otherwise
  const [propsPref, setPropsPref] = useState<boolean | null>(null);
  const pictures = useMemo(() => p.dets.filter(isPicture), [p.dets]);
  const showPictures = pictures.length > 0 || ["pdf", "image", "docx", "pptx", "xlsx", "email"].includes(p.file.kind);
  const focused = p.focusedId ? (p.dets.find((d) => d.id === p.focusedId) ?? null) : null;
  const paged = p.file.kind === "pdf" || p.file.kind === "image";
  const showProps = !!focused || (paged && !p.readOnly);
  const tab = !showPictures && p.tab === "pictures" ? "detections" : p.tab;
  const propsOpen = propsPref ?? !!focused;
  const setPropsOpen = (f: (v: boolean) => boolean) => setPropsPref(f(propsOpen));

  return (
    <aside className="side-col review-side" aria-label="Review panel">
      <Tabs<SideTab>
        label="Review panel"
        idPrefix="side"
        className="side-tabs"
        active={tab}
        onChange={p.setTab}
        tabs={[
          { key: "detections", label: <TabLabel text={p.detectionsTitle ?? "Detections"} n={p.dets.length} /> },
          { key: "pictures", label: <TabLabel text="Pictures" n={pictures.length} />, hidden: !showPictures },
          { key: "find", label: "Find & Redact", hidden: p.readOnly },
        ]}
      />
      <div className="side-main" role="tabpanel" aria-labelledby={`side-${tab}`}>
        {tab === "detections" && (
          <DetectionPanel
            dets={p.dets}
            ops={p.ops}
            focusedId={p.focusedId}
            onFocus={p.onFocus}
            showSuggestions={p.showSuggestions}
            setShowSuggestions={p.setShowSuggestions}
            chips={p.chips}
            readOnly={p.readOnly}
            currentPage={p.currentPage}
            pageCount={p.pages.length}
            title={p.detectionsTitle}
            emptyHint={p.emptyHint}
          />
        )}
        {tab === "pictures" && (
          <PicturesPanel
            fileId={p.file.id}
            pages={p.pages}
            dets={p.dets}
            ops={p.ops}
            focusedId={p.focusedId}
            onFocus={p.onFocus}
            readOnly={p.readOnly}
            analyzed={p.analyzed}
          />
        )}
        {tab === "find" && (
          <FindRedactPanel
            fileId={p.file.id}
            dets={p.dets}
            ops={p.ops}
            onPreview={p.onSearchPreview}
            onJump={p.onJump}
            disabledReason={p.searchDisabled}
            caseId={p.file.case_id}
          />
        )}
      </div>
      {showProps && (
        <div className={`side-props ${propsOpen ? "open" : ""}`}>
          <button className="side-props-toggle" onClick={() => setPropsOpen((v) => !v)} aria-expanded={propsOpen}>
            <SlidersHorizontal size={14} aria-hidden />
            <span className="strong">Properties</span>
            <span className="muted small truncate">
              {focused ? `· ${m.entityLabel(focused.entity)}` : `· new shapes: ${m.entityLabel(p.defaults.entity)}`}
            </span>
            <span className="toolbar-spacer" />
            {propsOpen ? <ChevronDown size={14} aria-hidden /> : <ChevronUp size={14} aria-hidden />}
          </button>
          {propsOpen && (
            <div className="side-props-body">
              <PropertiesPanel
                det={focused}
                fileKind={p.file.kind}
                ops={p.ops}
                readOnly={p.readOnly}
                defaults={p.defaults}
                setDefaults={p.setDefaults}
                onClose={p.clearFocus}
              />
            </div>
          )}
        </div>
      )}
      {p.footer}
    </aside>
  );
}

function TabLabel({ text, n }: { text: string; n: number }) {
  return (
    <span className="tab-label">
      {text} <span className="tab-count">{n}</span>
    </span>
  );
}
